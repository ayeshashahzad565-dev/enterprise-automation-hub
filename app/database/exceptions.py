"""Custom exception hierarchy for the app.database package.

Every exception a repository or the database client can raise is defined
here. Application Services (outside this package) are expected to catch
these exceptions and translate them into the ADD's documented error
handling behavior (ADD Section 8) and, where relevant, the API-ADD's
standardized error codes (API-ADD Section 11.3).

This module intentionally defines no exception related to business rules
(e.g. "a stage cannot be decided twice") — those are Application Layer
concerns. Every exception here corresponds to a persistence-level failure:
a missing row, a violated database constraint, a lost optimistic-locking
race, or a connectivity problem.
"""

from __future__ import annotations

from typing import Any


class DatabaseError(Exception):
    """Base class for every exception raised by the app.database package.

    Attributes:
        message: A human-readable description of the failure. Safe to
            include in internal logs; not guaranteed safe to return
            verbatim to an end user (per the ADD's error-handling
            philosophy, that translation is the Application Layer's
            responsibility, not this package's).
        details: A structured, machine-inspectable payload describing the
            failure (table name, identifiers, constraint name, etc.),
            useful for logging and for tests asserting on failure cause
            without parsing the exception's string representation.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{self.__class__.__name__}(message={self.message!r}, details={self.details!r})"


class DatabaseConnectionError(DatabaseError):
    """Raised when a connection to Supabase cannot be established or is lost.

    This covers both initial client construction failures (e.g. an
    unreachable Supabase URL at startup) and mid-operation connectivity
    failures. Per the ADD's error-handling strategy, a transient failure
    of this kind is expected to be retried a bounded number of times by
    the caller before being surfaced further; this package itself performs
    no retries, since retry policy is an Application Layer concern.
    """


class RepositoryError(DatabaseError):
    """Raised when a repository operation fails for a reason not covered by
    a more specific exception in this module.

    This is the catch-all translation target for an unexpected database
    error (per ADD Section 8's `RepositoryError`), used so that callers
    outside this package never need to catch a raw third-party exception
    type from the underlying Supabase client library.
    """


class RecordNotFoundError(DatabaseError):
    """Raised when a query expected exactly one row and found none.

    Attributes:
        table: The table the lookup was performed against.
        identifier: The identifier (typically a UUID) that was searched
            for and not found.
    """

    def __init__(self, table: str, identifier: Any) -> None:
        message = f"No record found in '{table}' matching identifier: {identifier!r}"
        super().__init__(message, details={"table": table, "identifier": str(identifier)})
        self.table = table
        self.identifier = identifier


class ConstraintViolationError(DatabaseError):
    """Raised when a write violates a database-level constraint.

    This corresponds to the foreign key, unique, and check constraints
    declared throughout the Database Schema Design Document (DSD Sections
    3-4) — for example, a duplicate `(request_type, version)` pair on
    `workflow_definitions`, or a `stage_order <= 0` value rejected by its
    check constraint. This exception is raised only when the underlying
    database itself rejects the write; it is not raised for validation
    failures caught before a query is ever issued (those are Application
    Layer / Domain Layer concerns per the ADD).

    Attributes:
        table: The table the write was attempted against.
        constraint: The kind of constraint violated ("unique",
            "foreign_key", "check"), when it can be determined from the
            underlying database error; ``None`` if it cannot be
            determined precisely.
    """

    def __init__(
        self,
        table: str,
        constraint: str | None,
        *,
        cause: Exception | None = None,
    ) -> None:
        message = f"Constraint violation on '{table}'" + (f" ({constraint})" if constraint else "")
        super().__init__(message, details={"table": table, "constraint": constraint})
        self.table = table
        self.constraint = constraint
        if cause is not None:
            self.__cause__ = cause


class ConcurrentUpdateError(DatabaseError):
    """Raised when an optimistic-locking update affects zero rows.

    This is the direct realization of the optimistic concurrency control
    strategy specified in DSD Section 3.9 and elaborated in WEDD Section
    12: every mutable table carries a `version` (or, for
    `workflow_definitions`, `row_version`) column, and every update is
    issued with a `WHERE id = :id AND version = :expected_version`
    predicate. When that predicate matches zero rows, it means another
    writer already changed the row since the caller last read it, and this
    exception is raised so the caller can decide whether to retry against
    fresh state.

    Attributes:
        table: The table the update was attempted against.
        record_id: The identifier of the row that could not be updated.
        expected_version: The version value the caller supplied, which no
            longer matched the row's current version at the moment of the
            update.
    """

    def __init__(self, table: str, record_id: Any, expected_version: int) -> None:
        message = (
            f"Optimistic lock conflict on '{table}' id={record_id!r}: "
            f"expected version {expected_version} did not match the current row version."
        )
        super().__init__(
            message,
            details={
                "table": table,
                "id": str(record_id),
                "expected_version": expected_version,
            },
        )
        self.table = table
        self.record_id = record_id
        self.expected_version = expected_version


class InvalidQueryError(DatabaseError):
    """Raised when a repository method receives parameters that cannot form
    a valid, safe query.

    This exists to fail fast on programmer error (e.g. calling a filtered
    list method with no filter at all, where at least one is required to
    keep the query bounded and index-backed per DSD Section 10), rather
    than allowing an unbounded or malformed query to reach Supabase.
    """


class StorageError(DatabaseError):
    """Raised when a Supabase Storage operation (upload, download, remove,
    or signed-URL generation) fails.

    Supabase Storage is a distinct subsystem from the PostgREST-backed
    tables every other repository in this package operates on — its
    Python SDK (``storage3``) raises its own ``StorageApiError``, not a
    Postgrest/PostgreSQL exception, so it cannot be translated by
    ``BaseRepository._translate_and_raise``. ``AttachmentStorageGateway``
    is the sole place a raw ``storage3`` exception is caught and
    translated into this type, exactly mirroring the role
    ``BaseRepository`` plays for every table-backed repository — no
    caller outside ``app.database`` ever needs to catch a raw
    third-party Storage exception type.

    Attributes:
        bucket: The Storage bucket the operation was attempted against.
        path: The object path (or paths, joined, for a bulk operation)
            the operation was attempted against.
    """

    def __init__(self, message: str, *, bucket: str, path: str) -> None:
        super().__init__(message, details={"bucket": bucket, "path": path})
        self.bucket = bucket
        self.path = path
