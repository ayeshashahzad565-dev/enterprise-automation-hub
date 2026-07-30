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

import contextvars
import logging
from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

import httpx

from app.database.client import DatabaseClient
from app.database.exceptions import (
    ConcurrentUpdateError,
    ConstraintViolationError,
    RecordNotFoundError,
    RepositoryError,
)
from app.utils.exceptions import RetryExhaustedError
from app.utils.retry import RetryPolicy, retry_call

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

#: Transport-level failures only — the request never reached the server,
#: or its response was lost in transit, distinct from any exception that
#: means the server actually responded (constraint violation, etc.),
#: which must never be retried here. postgrest-py (2.x) hardcodes
#: ``http2=True`` on its internal httpx client with no supported way to
#: disable it via the public API; a single dropped HTTP/2 stream can
#: surface as ``RemoteProtocolError``/``ReadError`` on an otherwise-healthy
#: connection. Implements the ADD's own Error Handling Strategy ("transient
#: failures are retried a bounded number of times at the repository
#: boundary"), which this method previously did not actually do.
_TRANSIENT_TRANSPORT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)

_TRANSIENT_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay_seconds=0.25,
    backoff_multiplier=2.0,
    max_delay_seconds=2.0,
    jitter=True,
    retryable_exceptions=_TRANSIENT_TRANSPORT_EXCEPTIONS,
)

#: The current request's tenant-scoped, RLS-enforcing database client, if
#: one has been bound. Set for the duration of a request by
#: ``app.api.dependencies.bind_tenant_database_client`` (an async
#: dependency, so the ``.set()`` below happens on the request's own
#: event-loop task, before any sync/threadpooled code runs — a plain
#: ``.set()`` made *inside* a sync dependency or endpoint would not
#: propagate out, since FastAPI/Starlette dispatch sync code through a
#: copied `contextvars.Context`). Left unset (``None``) outside an HTTP
#: request — the Scheduler and background jobs never bind it, so
#: ``BaseRepository._client`` transparently falls back to the
#: constructor-injected default client for them, exactly as before this
#: mechanism existed.
_current_tenant_client: contextvars.ContextVar[DatabaseClient | None] = contextvars.ContextVar(
    "_current_tenant_client", default=None
)


def bind_current_tenant_client(client: DatabaseClient) -> contextvars.Token[DatabaseClient | None]:
    """Bind ``client`` as the current request's tenant-scoped database client.

    The only intended caller is
    ``app.api.dependencies.bind_tenant_database_client`` — an async
    dependency, so this runs on the request's own event-loop task, before
    any threadpooled sync code (see that dependency's docstring for why
    that matters). ``_current_tenant_client`` itself stays module-private;
    this function and ``reset_current_tenant_client`` are the only
    supported way to affect it from outside this module.

    Args:
        client: The per-request, caller-scoped client to bind (typically
            constructed via ``SupabaseClientFactory.create_user_scoped_client``).

    Returns:
        A token that must be passed to ``reset_current_tenant_client`` once
        the request completes, to restore the prior (unset) value.
    """
    return _current_tenant_client.set(client)


def reset_current_tenant_client(token: contextvars.Token[DatabaseClient | None]) -> None:
    """Undo a prior ``bind_current_tenant_client`` call.

    Args:
        token: The token returned by the matching ``bind_current_tenant_client`` call.
    """
    _current_tenant_client.reset(token)


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
            raise ValueError(f"Page.size must be between 1 and {MAX_PAGE_SIZE}, got {self.size}.")

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
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
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


def escape_ilike_special_characters(value: str) -> str:
    """Escape ``%``, ``_``, and ``\\`` so ``value`` is matched literally by
    a PostgreSQL ``ILIKE`` pattern rather than as a wildcard.

    Per Milestone 9's Search/Filter Injection audit, this is the single
    shared implementation of a fix originally written locally in
    ``invitation_repository.py`` (the Milestone 1-5 cleanup pass) — every
    repository below that builds a free-text ``ILIKE`` pattern from
    caller-supplied text now imports this function rather than
    re-implementing it, so the escaping rule is defined exactly once.

    Without this, a search term containing a literal ``%`` or ``_``
    (both valid, if unusual, characters — e.g. in an email local part or
    a comment body) is silently reinterpreted by Postgres as "any
    sequence of characters" / "any single character," causing a search
    to match rows it should not (or fail to match ones it should) rather
    than behaving predictably. ``\\`` is PostgreSQL's default
    ``LIKE``/``ILIKE`` escape character, so a literal backslash in the
    input must itself be escaped first, before ``%``/``_`` are escaped,
    so the escaping sequences this function introduces are never
    themselves reinterpreted.

    Args:
        value: The raw value to embed in an ``ILIKE`` pattern.

    Returns:
        ``value`` with ``\\``, ``%``, and ``_`` escaped for literal
        matching. The caller is still responsible for adding its own,
        intentional ``%`` wildcards around the result, if any.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def quote_postgrest_filter_value(value: str) -> str:
    """Quote and escape a value for safe embedding in a raw PostgREST
    combined-filter expression string (``.or_()``/``.and_()``).

    Per Milestone 9's Search/Filter Injection audit: unlike a plain
    ``.ilike(column, value)``/``.eq(column, value)`` call — where the
    underlying ``postgrest-py`` client accepts ``value`` as a genuine,
    separately-encoded parameter — ``.or_()``/``.and_()`` take one raw,
    caller-built string in PostgREST's own combined-filter syntax
    (``column.op.value,column2.op2.value2``, with ``,``/``.``/``(``/``)``
    as syntactically significant characters). A caller-supplied value
    embedded in that string *unescaped* can break out of its intended
    ``column.op.value`` clause and inject additional filter clauses —
    the same class of risk as unescaped SQL string concatenation, though
    still bounded to whatever columns/rows the issuing repository method
    already queries (this application's repositories always run on the
    service-role client, which bypasses RLS, so this is a real
    authorization-relevant boundary, not just a data-shape nuisance —
    see ``RequestRepository.search_requests``/
    ``InvitationRepository.list_invitations``, the two call sites this
    was fixed for).

    PostgREST's documented escape hatch is to double-quote a filter
    value that must contain one of those reserved characters, with any
    embedded ``"``/``\\`` itself backslash-escaped — exactly what this
    function does. Every caller is expected to apply
    ``escape_ilike_special_characters`` *first* if the quoted value will
    also be used as an ``ilike`` pattern, then wrap the result with this
    function before interpolating it into a ``.or_()``/``.and_()`` string
    — the two concerns are independent (Postgres's own ``ILIKE``
    wildcard semantics vs. PostgREST's filter-string syntax) and both
    apply simultaneously to a value embedded in an OR'd ``ilike`` clause.

    Args:
        value: The raw (or already ``ILIKE``-escaped) value to embed as
            one filter clause's value in a ``.or_()``/``.and_()`` string.

    Returns:
        ``value`` wrapped in double quotes, with any embedded ``"`` or
        ``\\`` backslash-escaped, safe to interpolate directly into a
        combined-filter expression string.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        """Initialize the repository with an injected database client.

        Args:
            client: Any object satisfying the ``DatabaseClient`` protocol.
                Production code supplies a ``SupabaseDatabaseClient``
                constructed via ``SupabaseClientFactory``; tests may
                supply a lightweight fake (TSD Section 3.3). Used as this
                repository's *default* client — always used verbatim when
                ``always_use_injected_client`` is ``True``, and used as the
                fallback (outside an HTTP request, e.g. the Scheduler) when
                it is ``False``.
            always_use_injected_client: Required, no default, so every
                concrete repository must make an explicit, conscious
                choice rather than silently inheriting one:

                - ``True`` for a repository whose table's Row-Level
                  Security policy does not (yet) match how this codebase's
                  service layer actually reads or writes it (for example,
                  a cross-actor write, or a table with no ``INSERT`` grant
                  for the ``authenticated`` role at all) — this
                  repository's queries always run on ``client`` (typically
                  the shared service-role client), unaffected by any
                  per-request tenant-scoped client. Tenant isolation for
                  these tables is enforced entirely in application code
                  (see ``_scoped_query``), not RLS.
                - ``False`` for a repository verified safe to run under
                  the caller's own RLS context: it resolves the per-request
                  tenant-scoped client bound by
                  ``app.api.dependencies.bind_tenant_database_client`` when
                  one is bound (a real HTTP request from an authenticated
                  caller), falling back to ``client`` otherwise (the
                  Scheduler, background jobs, or any code path outside a
                  request — there is no "caller" to scope to).

        Raises:
            ValueError: If the concrete subclass did not set
                ``table_name``, which would indicate a programming error
                rather than a runtime condition.
        """
        if not getattr(self, "table_name", None):
            raise ValueError(
                f"{self.__class__.__name__} must define a non-empty 'table_name' attribute."
            )
        self._default_client = client
        self._always_use_injected_client = always_use_injected_client
        self._logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")

    @property
    def _client(self) -> DatabaseClient:
        """Resolve the database client this repository's next query should use.

        See ``always_use_injected_client``'s docstring above for the exact
        rule. Reading this property has no side effect and is safe to call
        any number of times per request.
        """
        if self._always_use_injected_client:
            return self._default_client
        return _current_tenant_client.get() or self._default_client

    def _query(self) -> Any:
        """Return a fresh PostgREST query builder scoped to this repository's table."""
        return self._client.table(self.table_name)

    def _scoped_query(self, *, company_id: UUID, count: str | None = "exact") -> Any:
        """Start a SELECT query pre-scoped to one company (tenant).

        Used by repositories whose table stays on the service-role client
        (``always_use_injected_client=True``) for their company-wide
        listing/search entry points — the ones most consequential to leave
        unscoped, since they are designed to span every row a tenant owns.
        Chaining ``.eq("company_id", ...)`` here, immediately, before any
        other filter, makes omitting the tenant filter a signature-level
        impossibility at these call sites rather than a convention a future
        edit could accidentally drop — the mechanical, CI-enforced half of
        this package's tenant-isolation architecture (the other half being
        the per-request RLS client for repositories where that's safe; see
        ``always_use_injected_client``).

        Args:
            company_id: The company (tenant) to scope this query to.
            count: The count method to request (e.g. ``"exact"``), or
                ``None`` to omit a count — forwarded to ``_select``.

        Returns:
            A query builder with the tenant filter already applied, ready
            for further ``.eq()``/``.order()``/etc. calls.
        """
        return self._select("*", count=count).eq("company_id", str(company_id))

    def _select(self, *columns: str, count: str | None = None) -> Any:
        """Start a filtered SELECT query, returning a filter-capable builder.

        The installed postgrest-py (2.x) client's table-level builder
        (``self._query()``) exposes only ``select``/``insert``/``update``/
        ``upsert``/``delete`` — filter methods (``.eq``, ``.gte``,
        ``.order``, ``.range``, etc.) exist only on the builder object one
        of *those* calls returns. ``.select()`` must therefore be the
        first call in the chain for any read query; every repository
        method building a filtered list/count query starts here, never
        from ``self._query()`` directly, so a caller can never
        accidentally chain a filter before ``.select()`` has run.

        Args:
            *columns: The columns to select (``"*"`` for all).
            count: The count method to request (e.g. ``"exact"``), or
                ``None`` to omit a count.

        Returns:
            A query builder ready for ``.eq()``/``.order()``/etc.
        """
        return self._query().select(*columns, count=count)

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
            return retry_call(builder.execute, policy=_TRANSIENT_RETRY_POLICY)
        except RetryExhaustedError as exc:
            assert isinstance(exc.last_exception, Exception)  # noqa: S101 - all _TRANSIENT_TRANSPORT_EXCEPTIONS are
            self._translate_and_raise(exc.last_exception, operation=operation)
            raise  # pragma: no cover - _translate_and_raise always raises
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
                raise ConstraintViolationError(self.table_name, "foreign_key", cause=exc) from exc
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

    def find_by_id(self, record_id: UUID, *, mapper: Callable[[dict[str, Any]], T]) -> T | None:
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
            builder: A query builder already started via
                ``self._select("*", count="exact")``, with filters
                (``.eq``, ``.gte``, etc.) and ordering (``.order``)
                already applied by the caller, but with ``.range`` not
                yet applied — that is applied by this method so that
                every paginated query in the codebase requests an
                inclusive range consistently.
            page: The requested page.
            mapper: A callable translating each raw row dict into this
                repository's record type.

        Returns:
            A ``PagedResult`` containing the mapped items and pagination
            metadata (API-ADD Section 9).
        """
        response = self._execute(
            builder.range(page.offset, page.upper_bound),
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
            builder: A query builder already started via
                ``self._select("id", count="exact")``, with filters
                already applied.

        Returns:
            The number of rows matching the filters.
        """
        response = self._execute(
            builder.limit(1),
            operation="count",
        )
        return self._count(response)

    def insert(self, values: dict[str, Any], *, mapper: Callable[[dict[str, Any]], T]) -> T:
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
