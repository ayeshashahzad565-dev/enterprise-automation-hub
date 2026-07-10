"""Abstract base repository shared by every repository in this package.

This module implements the common persistence primitives every concrete
repository needs — fetching a single row, paginating a filtered query,
inserting a row, and updating a row under optimistic-locking control (DSD
Section 3.9, WEDD Section 12) — exactly once, so that no concrete
repository duplicates this plumbing.

Per the ADD's layering rules, this class (and every subclass) performs
persistence only. It contains no business rules: it does not decide
*whether* a request should be created, *whether* a stage may be decided,
or *who* should be assigned to a stage — it only knows how to read and
write rows, and how to translate the underlying Supabase client's failures
into the typed exception hierarchy in ``app.database.exceptions``.
"""

from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Generic, TypeVar
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.exceptions import (
    ConcurrentUpdateError,
    ConstraintViolationError,
    RecordNotFoundError,
    RepositoryError,
)

try:  # pragma: no cover - defensive import guard for optional precise error codes
    from postgrest.exceptions import APIError as _PostgrestAPIError
except ImportError:  # pragma: no cover
    _PostgrestAPIError = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Default and maximum page sizes, matching API-ADD Section 3.9 / 12
#: exactly, so that pagination behavior is identical regardless of which
#: repository or endpoint a given list operation is served through.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

#: PostgreSQL error codes this package knows how to translate precisely.
#: See https://www.postgresql.org/docs/current/errcodes-appendix.html
_PG_UNIQUE_VIOLATION = "23505"
_PG_FOREIGN_KEY_VIOLATION = "23503"
_PG_CHECK_VIOLATION = "23514"
_PG_NOT_NULL_VIOLATION = "23502"


@dataclass(frozen=True, slots=True)
class Page:
    """A single, validated page request.

    Attributes:
        number: The 1-indexed page number requested.
        size: The number of records requested per page.

    Raises:
        ValueError: If ``number`` is less than 1, or ``size`` is outside
            ``[1, MAX_PAGE_SIZE]`` — matching API-ADD Section 12's rule
            that an out-of-range page size is rejected outright, never
            silently clamped.
    """

    number: int = 1
    size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError(f"Page.number must be >= 1, got {self.number}.")
        if not (1 <= self.size <= MAX_PAGE_SIZE):
            raise ValueError(
                f"Page.size must be between 1 and {MAX_PAGE_SIZE}, got {self.size}."
            )

    @property
    def offset(self) -> int:
        """The zero-indexed offset of the first record on this page."""
        return (self.number - 1) * self.size

    @property
    def upper_bound(self) -> int:
        """The zero-indexed offset of the last record on this page.

        Supabase's ``.range(start, end)`` is inclusive of ``end``, so this
        is ``offset + size - 1``, not ``offset + size``.
        """
        return self.offset + self.size - 1


@dataclass(frozen=True, slots=True)
class PagedResult(Generic[T]):
    """The result of a paginated query, matching API-ADD Section 9's
    pagination metadata shape exactly.

    Attributes:
        items: The records returned for the requested page.
        page: The page number that was served.
        page_size: The page size that was served.
        total_records: The total number of records matching the query,
            across all pages.
    """

    items: list[T]
    page: int
    page_size: int
    total_records: int

    @property
    def total_pages(self) -> int:
        """The total number of pages, computed as ``ceil(total_records / page_size)``."""
        if self.page_size <= 0:
            return 0
        return -(-self.total_records // self.page_size)


def parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse a Supabase-returned timestamp value into a timezone-aware ``datetime``.

    Supabase/PostgREST returns ``timestamptz`` columns as ISO-8601 strings.
    This helper centralizes that parsing so no individual repository
    re-implements it, and guarantees the result is always timezone-aware
    UTC, matching the ISO-8601/UTC convention fixed throughout the API-ADD
    (API-ADD Section 8).

    Args:
        value: The raw value returned by the Supabase client — typically a
            string, occasionally already a ``datetime`` (e.g. in a
            hand-constructed test fixture), or ``None`` for a nullable
            column with no value.

    Returns:
        A timezone-aware ``datetime`` in UTC, or ``None`` if ``value`` was
        ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_uuid(value: str | UUID | None) -> UUID | None:
    """Parse a Supabase-returned identifier value into a ``UUID``.

    Args:
        value: The raw value returned by the Supabase client — typically a
            string, occasionally already a ``UUID``, or ``None`` for a
            nullable foreign key column with no value.

    Returns:
        A ``UUID`` instance, or ``None`` if ``value`` was ``None``.
    """
    if value is None:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


class BaseRepository(ABC, Generic[T]):
    """Abstract base class for every repository in ``app.database.repositories``.

    Responsibilities of this class and its subclasses (the Repository
    Layer, per ADD Section 3.4):

    - Translate between plain Python/Pydantic-shaped values and the raw
      dict rows the Supabase client returns.
    - Issue exactly the query the caller asked for — no repository method
      silently applies a business rule (e.g. "only show non-deleted
      rows") unless that filter is explicitly named in the method's own
      signature and docstring.
    - Translate the underlying Supabase client's failures into the typed
      exception hierarchy in ``app.database.exceptions``, so that no
      caller outside this package ever needs to catch a raw third-party
      exception type.

    Explicitly **not** a responsibility of this class or any subclass:
    - Enforcing business rules (the Application Layer's responsibility,
      per the ADD).
    - Deciding *who* is authorized to perform an operation (Row-Level
      Security and the Application Layer's own checks handle this, per
      DSD Section 9 and API-ADD Section 6 — this package assumes the
      ``DatabaseClient`` it was given already carries the correct
      credential for the caller's context).
    - Sending notifications or writing audit entries as a side effect of
      an unrelated write (each of those is its own repository, invoked
      explicitly by the orchestrating Application Service).
    """

    #: The exact table name this repository operates against, as declared
    #: in the DSD. Must be set by every concrete subclass.
    table_name: str

    def __init__(self, client: DatabaseClient) -> None:
        """Initialize the repository with an injected database client.

        Args:
            client: Any object satisfying the ``DatabaseClient`` protocol.
                Production code supplies a ``SupabaseDatabaseClient``
                constructed via ``SupabaseClientFactory``; tests may
                supply a lightweight fake (TSD Section 3.3).

        Raises:
            ValueError: If the concrete subclass did not set
                ``table_name``, which would indicate a programming error
                rather than a runtime condition.
        """
        if not getattr(self, "table_name", None):
            raise ValueError(
                f"{self.__class__.__name__} must define a non-empty 'table_name' attribute."
            )
        self._client = client
        self._logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )

    def _query(self) -> Any:
        """Return a fresh PostgREST query builder scoped to this repository's table."""
        return self._client.table(self.table_name)

    def _execute(self, builder: Any, *, operation: str) -> Any:
        """Execute a query builder, translating any failure into a typed exception.

        Args:
            builder: A PostgREST query builder with its terminal
                ``.execute()`` call not yet invoked.
            operation: A short, human-readable name for the operation
                being performed (e.g. ``"get_by_id"``), used only for
                logging and exception messages.

        Returns:
            The raw response object returned by the Supabase client.

        Raises:
            ConstraintViolationError: If the database rejects the
                operation due to a unique, foreign key, check, or
                not-null constraint.
            RepositoryError: For any other unexpected failure.
        """
        try:
            return builder.execute()
        except Exception as exc:  # noqa: BLE001 - translated below
            self._translate_and_raise(exc, operation=operation)
            raise  # pragma: no cover - _translate_and_raise always raises

    def _translate_and_raise(self, exc: Exception, *, operation: str) -> None:
        """Translate an underlying client exception into this package's hierarchy.

        Prefers precise translation via the PostgREST/PostgreSQL error
        code (when the underlying exception exposes one) over string
        matching, falling back to string matching only for exception
        types that do not carry a structured code (e.g. a raw network
        error).

        Args:
            exc: The exception raised by the underlying Supabase client.
            operation: A short, human-readable operation name, used for
                logging context.

        Raises:
            ConstraintViolationError: On a recognized constraint violation.
            RepositoryError: On any other failure.
        """
        code = getattr(exc, "code", None)
        if _PostgrestAPIError is not None and isinstance(exc, _PostgrestAPIError):
            if code == _PG_UNIQUE_VIOLATION:
                self._logger.warning(
                    "Unique constraint violation during %s on '%s': %s",
                    operation,
                    self.table_name,
                    exc,
                )
                raise ConstraintViolationError(self.table_name, "unique", cause=exc) from exc
            if code == _PG_FOREIGN_KEY_VIOLATION:
                self._logger.warning(
                    "Foreign key violation during %s on '%s': %s",
                    operation,
                    self.table_name,
                    exc,
                )
                raise ConstraintViolationError(
                    self.table_name, "foreign_key", cause=exc
                ) from exc
            if code == _PG_CHECK_VIOLATION:
                self._logger.warning(
                    "Check constraint violation during %s on '%s': %s",
                    operation,
                    self.table_name,
                    exc,
                )
                raise ConstraintViolationError(self.table_name, "check", cause=exc) from exc
            if code == _PG_NOT_NULL_VIOLATION:
                self._logger.warning(
                    "Not-null constraint violation during %s on '%s': %s",
                    operation,
                    self.table_name,
                    exc,
                )
                raise ConstraintViolationError(self.table_name, "not_null", cause=exc) from exc

        # Fallback: string-based detection for exception types that do not
        # expose a structured PostgreSQL error code (e.g. network-layer
        # errors surfaced by the underlying HTTP client).
        message = str(exc).lower()
        if "duplicate key" in message or "unique constraint" in message:
            self._logger.warning(
                "Unique constraint violation during %s on '%s': %s", operation, self.table_name, exc
            )
            raise ConstraintViolationError(self.table_name, "unique", cause=exc) from exc
        if "foreign key" in message:
            self._logger.warning(
                "Foreign key violation during %s on '%s': %s", operation, self.table_name, exc
            )
            raise ConstraintViolationError(self.table_name, "foreign_key", cause=exc) from exc
        if "check constraint" in message:
            self._logger.warning(
                "Check constraint violation during %s on '%s': %s", operation, self.table_name, exc
            )
            raise ConstraintViolationError(self.table_name, "check", cause=exc) from exc

        self._logger.error(
            "Unexpected database error during %s on '%s': %s",
            operation,
            self.table_name,
            exc,
            exc_info=exc,
        )
        raise RepositoryError(
            f"Database operation '{operation}' failed on '{self.table_name}'."
        ) from exc

    @staticmethod
    def _rows(response: Any) -> list[dict[str, Any]]:
        """Normalize a Supabase response's ``data`` attribute into a list of dict rows."""
        data = getattr(response, "data", None)
        if data is None:
            return []
        if isinstance(data, list):
            return data
        return [data]

    def _single_row(self, response: Any, *, identifier: Any) -> dict[str, Any]:
        """Extract exactly one row from a response, or raise ``RecordNotFoundError``.

        Args:
            response: The raw response returned by ``_execute``.
            identifier: The identifier used in the query, included in the
                raised exception for a precise error message.

        Returns:
            The single matching row as a dict.

        Raises:
            RecordNotFoundError: If the response contains no rows.
        """
        rows = self._rows(response)
        if not rows:
            raise RecordNotFoundError(self.table_name, identifier)
        return rows[0]

    @staticmethod
    def _count(response: Any) -> int:
        """Extract the total-match count from a response requested with ``count="exact"``."""
        count = getattr(response, "count", None)
        return int(count) if count is not None else 0

    def get_by_id(self, record_id: UUID, *, mapper: Callable[[dict[str, Any]], T]) -> T:
        """Fetch exactly one row by primary key.

        Args:
            record_id: The row's ``id`` column value.
            mapper: A callable translating the raw row dict into this
                repository's record type.

        Returns:
            The mapped record.

        Raises:
            RecordNotFoundError: If no row with this ``id`` exists (or is
                visible under the current client's Row-Level Security
                context, per DSD Section 9).
            RepositoryError: On any unexpected failure.
        """
        response = self._execute(
            self._query().select("*").eq("id", str(record_id)).limit(1),
            operation="get_by_id",
        )
        row = self._single_row(response, identifier=record_id)
        return mapper(row)

    def find_by_id(
        self, record_id: UUID, *, mapper: Callable[[dict[str, Any]], T]
    ) -> T | None:
        """Fetch exactly one row by primary key, tolerating absence.

        Identical to ``get_by_id`` except that a missing row results in
        ``None`` rather than a raised exception — appropriate for callers
        that treat "not found" as a normal outcome rather than an error
        condition (for example, an existence check prior to a
        conditional insert).

        Args:
            record_id: The row's ``id`` column value.
            mapper: A callable translating the raw row dict into this
                repository's record type.

        Returns:
            The mapped record, or ``None`` if no matching row exists.
        """
        response = self._execute(
            self._query().select("*").eq("id", str(record_id)).limit(1),
            operation="find_by_id",
        )
        rows = self._rows(response)
        return mapper(rows[0]) if rows else None

    def paginate(
        self,
        builder: Any,
        page: Page,
        *,
        mapper: Callable[[dict[str, Any]], T],
    ) -> PagedResult[T]:
        """Execute a filtered, paginated query and map its results.

        Args:
            builder: A query builder with filters (``.eq``, ``.gte``,
                etc.) and ordering (``.order``) already applied by the
                caller, but with ``.select`` and ``.range`` not yet
                applied — those are applied by this method so that every
                paginated query in the codebase requests an exact count
                and an inclusive range consistently.
            page: The requested page.
            mapper: A callable translating each raw row dict into this
                repository's record type.

        Returns:
            A ``PagedResult`` containing the mapped items and pagination
            metadata (API-ADD Section 9).
        """
        response = self._execute(
            builder.select("*", count="exact").range(page.offset, page.upper_bound),
            operation="paginate",
        )
        rows = self._rows(response)
        total = self._count(response)
        return PagedResult(
            items=[mapper(row) for row in rows],
            page=page.number,
            page_size=page.size,
            total_records=total,
        )

    def count(self, builder: Any) -> int:
        """Execute a filtered query and return only the matching row count.

        Used by repositories that need a count without fetching rows (for
        example, ``NotificationRepository.get_unread_count``, API-ADD
        Section 19.8.3), issuing a minimal request rather than fetching
        and discarding full rows.

        Args:
            builder: A query builder with filters already applied, but
                with ``.select`` not yet applied.

        Returns:
            The number of rows matching the filters.
        """
        response = self._execute(
            builder.select("id", count="exact").limit(1),
            operation="count",
        )
        return self._count(response)

    def insert(
        self, values: dict[str, Any], *, mapper: Callable[[dict[str, Any]], T]
    ) -> T:
        """Insert a single row.

        Args:
            values: The column values to insert. UUID and datetime values
                must already be serialized to strings by the caller (each
                concrete repository owns this translation for its own
                table, since the correct serialization is table-specific).
            mapper: A callable translating the inserted row (as returned
                by Supabase, including any server-generated defaults such
                as ``id`` and ``created_at``) into this repository's
                record type.

        Returns:
            The newly inserted record, as returned by the database.

        Raises:
            ConstraintViolationError: If the insert violates a unique,
                foreign key, check, or not-null constraint.
            RepositoryError: On any other unexpected failure.
        """
        response = self._execute(self._query().insert(values), operation="insert")
        row = self._single_row(response, identifier=values.get("id", "<generated>"))
        return mapper(row)

    def update_with_optimistic_lock(
        self,
        record_id: UUID,
        *,
        expected_version: int,
        values: dict[str, Any],
        mapper: Callable[[dict[str, Any]], T],
        version_column: str = "version",
    ) -> T:
        """Update a row under optimistic-locking control.

        Issues ``UPDATE ... WHERE id = :record_id AND
        :version_column = :expected_version``, incrementing
        ``version_column`` by one as part of the same statement — the
        exact pattern specified in DSD Section 3.9 and WEDD Section 12.

        Args:
            record_id: The row's ``id`` column value.
            expected_version: The version value the caller last observed.
                If the row's current version no longer matches this
                value, zero rows are affected and a
                ``ConcurrentUpdateError`` is raised.
            values: The column values to update, not including the
                version column itself (this method manages that).
            mapper: A callable translating the updated row into this
                repository's record type.
            version_column: The name of the optimistic-locking column on
                this table — ``"version"`` for every table except
                ``workflow_definitions``, which uses ``"row_version"``
                (DSD Section 3.2).

        Returns:
            The updated record, reflecting the new version value.

        Raises:
            ConcurrentUpdateError: If no row matched both ``record_id``
                and ``expected_version`` at the moment of the update —
                meaning another writer already changed this row.
            ConstraintViolationError: If the update itself violates a
                constraint.
            RepositoryError: On any other unexpected failure.
        """
        payload = dict(values)
        payload[version_column] = expected_version + 1
        response = self._execute(
            self._query()
            .update(payload)
            .eq("id", str(record_id))
            .eq(version_column, expected_version),
            operation="update_with_optimistic_lock",
        )
        rows = self._rows(response)
        if not rows:
            raise ConcurrentUpdateError(self.table_name, record_id, expected_version)
        return mapper(rows[0])