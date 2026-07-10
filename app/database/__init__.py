"""Database access layer for the Enterprise Automation Hub.

Per the Architecture Design Document, this package is the Repository
Layer: the only part of the codebase permitted to construct a Supabase
client or issue a query against it. It contains:

- ``client``: the ``DatabaseClient`` abstraction and the
  ``SupabaseClientFactory`` used to construct production instances of it,
  supporting dependency injection throughout ``repositories``.
- ``exceptions``: the typed exception hierarchy every repository raises,
  translating the underlying Supabase client's failures into a stable,
  package-owned vocabulary.
- ``repositories``: one repository class per table (or closely related
  pair of tables) defined in the Database Schema Design Document,
  performing persistence only — no business logic, no orchestration
  across repositories, and no HTTP-layer concerns.
- ``migrations``: the designated location for this package's Alembic
  migration history (see ``migrations/README.md``).

This package introduces no technology beyond what the fixed stack already
specifies: Supabase (PostgreSQL, Auth, Storage) as the sole persistence
backend, and Alembic as the sole schema-migration tool.
"""

from __future__ import annotations

from app.database.client import (
    DatabaseClient,
    SupabaseClientFactory,
    SupabaseConnectionSettings,
    SupabaseDatabaseClient,
)
from app.database.exceptions import (
    ConcurrentUpdateError,
    ConstraintViolationError,
    DatabaseConnectionError,
    DatabaseError,
    InvalidQueryError,
    RecordNotFoundError,
    RepositoryError,
)

__all__ = [
    "ConcurrentUpdateError",
    "ConstraintViolationError",
    "DatabaseClient",
    "DatabaseConnectionError",
    "DatabaseError",
    "InvalidQueryError",
    "RecordNotFoundError",
    "RepositoryError",
    "SupabaseClientFactory",
    "SupabaseConnectionSettings",
    "SupabaseDatabaseClient",
]