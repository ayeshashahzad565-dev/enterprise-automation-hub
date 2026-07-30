"""Initialize a Supabase project's database schema from version control.

A production-quality wrapper around this project's existing migration
and seed tooling — it defines no schema and issues no SQL of its own.
Per ``app/database/migrations/README.md``, Alembic (``alembic upgrade
head``) is the single place this project's schema is created; this
script's only job is to verify configuration is present before calling
it, then optionally hand off to ``scripts/seed_demo_data.py`` (also
reused as-is, not reimplemented here).

Steps:
    1. Verify environment variables by loading ``AppSettings`` through
       ``app.config.settings.load_settings`` — the codebase's single,
       existing source of environment-variable validation.
    2. Run every pending migration (``alembic upgrade head``).
    3. If ``--seed`` was passed and the detected environment is
       Development or Testing, seed a development admin user via
       ``scripts/seed_demo_data.py``'s own ``main``.

Usage:
    python scripts/initialize_db.py
    python scripts/initialize_db.py --seed
    python scripts/initialize_db.py --seed --email dev@example.com --password "S0meP@ss"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config.exceptions import ConfigurationError
from app.config.logging_config import configure_logging, get_logger
from app.config.paths import PROJECT_ROOT
from app.config.settings import AppSettings, load_settings

logger = get_logger(__name__)

ALEMBIC_INI_PATH = PROJECT_ROOT / "alembic.ini"

#: This script's own directory, added to sys.path so it can import its
#: sibling scripts.seed_demo_data module by name regardless of the
#: current working directory the caller invokes it from — mirroring the
#: same "python scripts/<name>.py" invocation convention
#: seed_demo_data.py's own module docstring documents.
_SCRIPTS_DIR = Path(__file__).resolve().parent


def verify_environment() -> AppSettings:
    """Validate that every required environment variable is present and well-formed.

    Reuses ``app.config.settings.load_settings`` as the single source of
    environment-variable validation in this codebase (per that module's
    own docstring: "the only place in app.config that reads
    os.environ") — this function performs no validation of its own, it
    only adds initialization-specific logging around that call.

    Returns:
        The loaded, validated ``AppSettings``.

    Raises:
        ConfigurationError: If a required environment variable is
            missing or invalid.
    """
    logger.info("Verifying environment configuration...")
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        logger.error("Environment verification failed: %s", exc.message)
        raise
    logger.info(
        "Environment verified.",
        extra={"environment": settings.environment.value, "supabase_url": settings.supabase.url},
    )
    return settings


def build_alembic_config() -> Config:
    """Construct the Alembic ``Config`` pointing at this project's ``alembic.ini``.

    Returns:
        A ``Config`` equivalent to invoking the ``alembic`` CLI from the
        project root — this introduces no migration behavior of its
        own, only locates the existing configuration Alembic itself
        reads (``alembic.ini`` → ``app/database/migrations/env.py``).
    """
    return Config(str(ALEMBIC_INI_PATH))


def run_migrations() -> None:
    """Apply every pending migration up to the latest revision.

    Delegates entirely to Alembic's own ``upgrade`` command — the
    project's single migration-execution path. This function defines no
    schema and issues no SQL of its own; every table, enum, trigger, and
    policy is created by the revision scripts under
    ``app/database/migrations/versions/``.
    """
    logger.info("Running migrations (alembic upgrade head)...")
    command.upgrade(build_alembic_config(), "head")
    logger.info("Migrations applied successfully.")


def seed_if_requested(*, seed: bool, settings: AppSettings, seed_argv: list[str]) -> None:
    """Seed a development admin user, if requested and permitted.

    Reuses ``scripts/seed_demo_data.py``'s own ``main`` entry point
    unchanged, rather than reimplementing user creation here — this
    function only decides *whether* to call it.

    Args:
        seed: Whether the caller asked to seed (``--seed``).
        settings: The already-loaded application settings, consulted
            here only to skip the call early with a clear log message;
            ``seed_demo_data.seed_admin_user`` enforces the actual
            Development/Testing-only guard regardless, so this is a
            second, defense-in-depth check, not the sole one.
        seed_argv: The argument list to forward to
            ``seed_demo_data.main`` (``--email``/``--password``/
            ``--full-name``, only for flags the caller explicitly
            supplied — see ``_build_seed_argv``).

    Raises:
        RuntimeError: If seeding was attempted and
            ``seed_demo_data.main`` reported failure.
    """
    if not seed:
        logger.info("Skipping demo data seed (--seed not passed).")
        return
    if settings.environment.requires_production_grade_hardening:
        logger.warning(
            "Skipping demo data seed: environment '%s' requires "
            "production-grade hardening; seed_demo_data.py would refuse "
            "this regardless.",
            settings.environment.value,
        )
        return

    logger.info("Seeding development admin user...")
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    import seed_demo_data  # local import: sibling script, see module docstring

    exit_code = seed_demo_data.main(seed_argv)
    if exit_code != 0:
        raise RuntimeError("Seeding the development admin user failed.")
    logger.info("Demo data seed complete.")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for this script.

    Args:
        argv: The argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Also seed a development admin user (Development/Testing only).",
    )
    parser.add_argument(
        "--email", default=None, help="Admin email for --seed (forwarded to seed_demo_data.py)."
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Admin password for --seed (forwarded to seed_demo_data.py).",
    )
    parser.add_argument(
        "--full-name",
        default=None,
        help="Admin display name for --seed (forwarded to seed_demo_data.py).",
    )
    return parser.parse_args(argv)


def _build_seed_argv(args: argparse.Namespace) -> list[str]:
    """Translate this script's ``--email``/``--password``/``--full-name``
    into ``seed_demo_data.main``'s argv, omitting any flag the caller
    did not explicitly pass so ``seed_demo_data.py``'s own defaults
    apply — this script deliberately does not duplicate those defaults.

    Args:
        args: This script's parsed arguments.

    Returns:
        The argv list to pass to ``seed_demo_data.main``.
    """
    argv: list[str] = []
    if args.email is not None:
        argv += ["--email", args.email]
    if args.password is not None:
        argv += ["--password", args.password]
    if args.full_name is not None:
        argv += ["--full-name", args.full_name]
    return argv


def main(argv: list[str] | None = None) -> int:
    """Entry point: verify configuration, migrate, and optionally seed.

    Args:
        argv: The argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: ``0`` on success, ``1`` on any failure.
    """
    configure_logging("INFO")
    args = _parse_args(argv)
    try:
        settings = verify_environment()
        run_migrations()
        seed_if_requested(seed=args.seed, settings=settings, seed_argv=_build_seed_argv(args))
    except ConfigurationError as exc:
        logger.error("Database initialization aborted: %s", exc.message)
        return 1
    except Exception as exc:  # noqa: BLE001 - top-level CLI failure boundary
        logger.error("Database initialization failed: %s", exc, exc_info=exc)
        return 1

    logger.info("Database initialization complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
