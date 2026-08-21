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
from sqlalchemy import Connection, engine_from_config, pool, text

# Alembic hardcodes `alembic_version.version_num` as VARCHAR(32) in
# `alembic.ddl.impl.DefaultImpl._version_table_impl`. Several revision ids
# in this project's history exceed that — the longest,
# "0008_user_invitations_status_expires_at_index", is 45 characters — so
# `alembic upgrade head` against a fresh database got as far as recording
# revision 0008 and then failed with:
#
#   psycopg.errors.StringDataRightTruncation:
#   value too long for type character varying(32)
#
# There is no `context.configure()` option for this. An earlier attempt
# passed `version_table_column_type=String(128)`, but no such parameter
# exists in Alembic; unrecognized keywords are absorbed into the opts dict
# and silently ignored, so it never had any effect and the truncation
# remained. Alembic only *creates* the version table when one is not
# already present, so creating it ourselves first — wide enough for the
# ids this project actually uses — is what genuinely fixes it.
_VERSION_TABLE = "alembic_version"
_VERSION_NUM_LENGTH = 128

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


def _ensure_wide_version_table(connection: Connection) -> None:
    """Create or widen ``alembic_version`` so long revision ids fit.

    Both statements are idempotent, so this is safe on every run:

    * ``CREATE TABLE IF NOT EXISTS`` wins the race on a fresh database —
      Alembic finds a version table already present and skips its own
      VARCHAR(32) creation.
    * ``ALTER COLUMN ... TYPE`` repairs a database that Alembic already
      created narrowly, and is a no-op when the column is already wide.
    """
    connection.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {_VERSION_TABLE} ("
            f"  version_num VARCHAR({_VERSION_NUM_LENGTH}) NOT NULL,"
            f"  CONSTRAINT {_VERSION_TABLE}_pkc PRIMARY KEY (version_num)"
            f")"
        )
    )
    connection.execute(
        text(
            f"ALTER TABLE {_VERSION_TABLE} "
            f"ALTER COLUMN version_num TYPE VARCHAR({_VERSION_NUM_LENGTH})"
        )
    )


def run_migrations_offline() -> None:
    """Emit migration SQL without opening a live database connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        # Offline mode never connects, so `_ensure_wide_version_table`
        # cannot run here. Alembic emits its own VARCHAR(32) version-table
        # DDL into the generated script, and adding a second CREATE for the
        # same table would only make that script fail on execution. Anyone
        # running `alembic upgrade --sql` must widen version_num by hand
        # before applying the output; the online path below, which is what
        # CI and every documented deployment uses, handles it directly.
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live database connection."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # Must precede context.configure(): Alembic inspects for the version
        # table as part of running migrations, and only creates its own
        # narrow one when nothing is there yet.
        _ensure_wide_version_table(connection)
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
