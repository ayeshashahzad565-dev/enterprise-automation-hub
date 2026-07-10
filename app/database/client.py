"""Supabase database client abstraction for the Enterprise Automation Hub.

This module is the single place in the entire codebase that constructs a
connection to Supabase (per the ADD's Repository Layer description: "the
only place SQL/PostgREST query syntax and storage-bucket calls appear").
It defines:

- ``SupabaseConnectionSettings``: an immutable value object carrying the
  connection parameters a client needs. This module never reads
  environment variables itself — per the ADD, only the Configuration
  Loader (outside this package) reads `os.environ`, and it is expected to
  construct a ``SupabaseConnectionSettings`` instance and hand it to the
  factory below. This keeps the database layer trivially testable: a test
  constructs its own settings pointing at a disposable test project,
  entirely independent of how production configuration is sourced.

- ``DatabaseClient``: a structural (``typing.Protocol``) interface that
  every repository in ``app.database.repositories`` depends on, rather
  than depending on the concrete Supabase SDK type directly. This is what
  makes "database client should support dependency injection" concrete: a
  repository's constructor accepts anything satisfying this protocol,
  including a hand-written fake used in unit tests (TSD Section 3.3),
  without any repository needing to import the Supabase SDK itself.

- ``SupabaseDatabaseClient``: the production implementation of
  ``DatabaseClient``, backed by the official ``supabase-py`` client.

- ``SupabaseClientFactory``: constructs the two distinct client types the
  DSD and ADD require — an anon-key client (subject to Row-Level
  Security) and a service-role client (used only by trusted, server-side
  code paths, per DSD Section 9.3) — from a single settings object.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from supabase import Client, create_client

from app.database.exceptions import DatabaseConnectionError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SupabaseConnectionSettings:
    """Immutable connection settings for a single Supabase project.

    Instances of this class are expected to be constructed by the
    application's Configuration Loader (per the ADD) from environment
    variables, and then passed into ``SupabaseClientFactory``. This class
    deliberately performs no environment-variable access of its own, so
    that the database layer remains fully decoupled from *how*
    configuration is sourced.

    Attributes:
        url: The Supabase project's API URL.
        anon_key: The client-facing key, subject to Row-Level Security
            (DSD Section 9).
        service_role_key: The elevated, server-side-only key used for the
            narrow set of legitimately cross-cutting operations described
            in DSD Section 9.3 (for example, the Scheduler's Escalation
            Check job). ``None`` when only anon-key access is required
            (e.g. in a test constructing a client for RLS verification
            specifically, per TSD Section 6.4, which must *not* use the
            service-role key).
    """

    url: str
    anon_key: str
    service_role_key: str | None = None

    def __post_init__(self) -> None:
        if not self.url or not self.url.strip():
            raise ValueError("SupabaseConnectionSettings.url must not be empty.")
        if not self.anon_key or not self.anon_key.strip():
            raise ValueError("SupabaseConnectionSettings.anon_key must not be empty.")


@runtime_checkable
class DatabaseClient(Protocol):
    """Structural interface that every repository depends on.

    Repositories are constructed with an object satisfying this protocol,
    never with a concrete Supabase SDK client directly (ADD Section 7's
    constructor-injection pattern, applied to the database boundary). This
    is what allows a unit test to supply a lightweight fake implementing
    only this interface, without importing or mocking the Supabase SDK.
    """

    @property
    def is_service_role(self) -> bool:
        """Whether this client connection uses the elevated service-role
        credential (and therefore bypasses Row-Level Security, per DSD
        Section 9.3) rather than the RLS-subject anon key."""
        ...

    def table(self, name: str) -> Any:
        """Return a query builder scoped to the given table name.

        The returned object is expected to expose the standard
        PostgREST-style fluent query interface (``select``, ``insert``,
        ``update``, ``eq``, ``order``, ``range``, ``execute``, etc.), as
        provided by the underlying ``supabase-py`` client.
        """
        ...

    def health_check(self) -> bool:
        """Return ``True`` if this client can successfully reach the
        configured Supabase project, ``False`` otherwise.

        Used by the Deployment Guide's startup sequence (DG Section 5.4)
        and health endpoint (API-ADD Section 27) to determine readiness.
        This method is expected never to raise; connectivity failures are
        caught internally and reported as ``False``.
        """
        ...


class SupabaseDatabaseClient:
    """Production ``DatabaseClient`` implementation backed by ``supabase-py``.

    Instances of this class are constructed exclusively through
    ``SupabaseClientFactory`` (never directly), so that the distinction
    between an anon-key and a service-role connection is always explicit
    and intentional at the call site that created it.
    """

    def __init__(self, client: Client, *, is_service_role: bool) -> None:
        """Initialize the wrapper around an already-constructed Supabase client.

        Args:
            client: A fully constructed ``supabase.Client`` instance.
            is_service_role: Whether ``client`` was constructed using the
                service-role key. Stored so that repositories and calling
                Application Services can assert on the expected privilege
                level of a given client instance where that matters (for
                example, refusing to run a Scheduler-only operation
                against an anon-key client).
        """
        self._client = client
        self._is_service_role = is_service_role
        self._logger = logging.getLogger(self.__class__.__module__)

    @property
    def is_service_role(self) -> bool:
        """Whether this client connection uses the elevated service-role
        credential, per DSD Section 9.3."""
        return self._is_service_role

    def table(self, name: str) -> Any:
        """Return a PostgREST query builder scoped to ``name``.

        Args:
            name: The exact table name as declared in the DSD (e.g.
                ``"requests"``, ``"workflow_stages"``).
        """
        return self._client.table(name)

    @property
    def storage(self) -> Any:
        """Expose the underlying Supabase Storage client.

        Used only by attachment-handling code (outside this package's
        current scope) that needs to read or write objects per DSD
        Section 7 and API-ADD Section 23's file-handling discipline.
        """
        return self._client.storage

    @property
    def auth(self) -> Any:
        """Expose the underlying Supabase Auth (GoTrue) client.

        Used only by authentication-handling code (outside this package's
        current scope), per the ADD's ``AuthService`` description.
        """
        return self._client.auth

    def health_check(self) -> bool:
        """Confirm this client can reach the configured Supabase project.

        Performs a minimal, cheap read (a single-row, single-column select
        against ``profiles``, the smallest table with a stable, always-
        present shape) rather than attempting a write, since a health
        check must never have a side effect.

        Returns:
            ``True`` if the read succeeds, ``False`` if any exception is
            raised while attempting it. This method never raises.
        """
        try:
            self._client.table("profiles").select("id").limit(1).execute()
        except Exception as exc:  # noqa: BLE001 - health checks must not raise
            self._logger.warning("Supabase health check failed: %s", exc, exc_info=exc)
            return False
        return True


class SupabaseClientFactory:
    """Factory responsible for constructing ``SupabaseDatabaseClient`` instances.

    This is the only place in the codebase where ``supabase.create_client``
    is called. Repositories never construct their own client; they always
    receive one via constructor injection (ADD Section 7, DG Section 9),
    and this factory is the boundary that turns connection *settings* into
    a usable, typed *client*.
    """

    @staticmethod
    def create_anon_client(settings: SupabaseConnectionSettings) -> SupabaseDatabaseClient:
        """Construct a client authenticated with the RLS-subject anon key.

        This is the client type used by every request-scoped Application
        Service call in the normal request lifecycle (ADD Section 5),
        where Row-Level Security (DSD Section 9) is the intended
        enforcement mechanism.

        Args:
            settings: The target Supabase project's connection settings.

        Returns:
            A ``SupabaseDatabaseClient`` with ``is_service_role`` set to
            ``False``.

        Raises:
            DatabaseConnectionError: If the underlying client cannot be
                constructed (e.g. a malformed URL). Note that client
                construction itself does not perform network I/O in
                ``supabase-py``; this exception path exists to give
                callers a single, typed failure mode regardless of the
                underlying SDK's own exception types.
        """
        logger.info("Constructing Supabase anon-key client for %s", settings.url)
        try:
            raw_client = create_client(settings.url, settings.anon_key)
        except Exception as exc:  # noqa: BLE001 - translated into a typed error below
            logger.error("Failed to construct Supabase anon-key client: %s", exc, exc_info=exc)
            raise DatabaseConnectionError(
                "Failed to construct a Supabase client using the anon key.",
                details={"url": settings.url},
            ) from exc
        return SupabaseDatabaseClient(raw_client, is_service_role=False)

    @staticmethod
    def create_service_role_client(settings: SupabaseConnectionSettings) -> SupabaseDatabaseClient:
        """Construct a client authenticated with the elevated service-role key.

        Per DSD Section 9.3 and API-ADD Section 24, this client type
        bypasses Row-Level Security entirely and must be confined to
        trusted, server-side operations only (for example, the
        Scheduler's Escalation Check job). It must never be constructed
        for, or exposed to, any client-facing/browser-reachable code path.

        Args:
            settings: The target Supabase project's connection settings.
                ``settings.service_role_key`` must be populated.

        Returns:
            A ``SupabaseDatabaseClient`` with ``is_service_role`` set to
            ``True``.

        Raises:
            ValueError: If ``settings.service_role_key`` is ``None``,
                since constructing a service-role client without one
                would be a programming error, not a runtime condition to
                degrade gracefully from.
            DatabaseConnectionError: If the underlying client cannot be
                constructed.
        """
        if not settings.service_role_key:
            raise ValueError(
                "Cannot construct a service-role Supabase client: "
                "SupabaseConnectionSettings.service_role_key was not provided."
            )
        logger.info("Constructing Supabase service-role client for %s", settings.url)
        try:
            raw_client = create_client(settings.url, settings.service_role_key)
        except Exception as exc:  # noqa: BLE001 - translated into a typed error below
            logger.error(
                "Failed to construct Supabase service-role client: %s", exc, exc_info=exc
            )
            raise DatabaseConnectionError(
                "Failed to construct a Supabase client using the service-role key.",
                details={"url": settings.url},
            ) from exc
        return SupabaseDatabaseClient(raw_client, is_service_role=True)