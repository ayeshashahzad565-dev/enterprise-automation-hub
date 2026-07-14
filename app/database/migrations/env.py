"""Alembic environment configuration for Enterprise Automation Hub.

Per this directory's own README and DSD Section 15 / Deployment Guide
Section 11, Alembic is used strictly as a development-time and
deployment-time schema-versioning tool, connected directly to Postgres
via ``DATABASE_URL`` — the same variable
``app.config.settings.load_settings`` reads for the running
application, but read here independently via ``os.environ``/
``python-dotenv`` rather than through ``app.config.settings`` itself, so
that running a migration never needs to import Streamlit, the Supabase
SDK, or any other application-layer dependency this package has no need
of (per the README's "no migration script in this directory should
import anything from app.database.repositories" rule).

No SQLAlchemy ORM models exist anywhere in this project — the schema is
authored directly as SQL in each revision script under ``versions/``,
matching this project's fixed technology stack (Supabase/PostgREST, not
an ORM). ``target_metadata`` is therefore ``None`` and Alembic's
``--autogenerate`` is never used against this environment.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _database_url() -> str:
    """Resolve the migration target's connection string from ``DATABASE_URL``.

    Normalizes a plain ``postgresql://`` URL (Supabase's own connection
    string format, as shown on a project's Database Settings page) to
    the ``postgresql+psycopg://`` dialect this project's installed
    driver (``psycopg`` 3, per ``pyproject.toml``) expects — SQLAlchemy
    otherwise defaults an unqualified ``postgresql://`` URL to
    ``psycopg2``, which is not part of this project's fixed technology
    stack.

    Returns:
        The normalized SQLAlchemy connection URL.

    Raises:
        RuntimeError: If ``DATABASE_URL`` is not set.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Alembic migrations connect directly to "
            "Postgres (Deployment Guide Section 11), independent of the "
            "Supabase client used by the running application. Set it in "
            "the environment or in a .env file at the repository root."
        )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    """Emit migration SQL without opening a live database connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live database connection."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
