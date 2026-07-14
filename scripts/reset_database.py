"""Reset the local development database: tear down and rebuild the
entire schema, then optionally reseed it.

This script issues no schema-defining SQL of its own. "Tear down and
rebuild" here means running every migration's own, already-reviewed
``downgrade()`` path in reverse (``alembic downgrade base``) and then
every ``upgrade()`` path forward again (``alembic upgrade head``) —
reusing exactly the same migration logic
``app/database/migrations/versions/`` already defines, rather than a
separate hand-written ``DROP SCHEMA public CASCADE`` (which would also
remove Supabase's own default setup on the ``public`` schema, not just
this project's own tables). ``initialize_db.py``'s ``verify_environment``,
``build_alembic_config``, and ``seed_if_requested`` are reused directly
rather than re-implemented here.

Guarded against Staging and Production identically (per
``Environment.requires_production_grade_hardening`` — the same boundary
``scripts/seed_demo_data.py`` and ``app/config/settings.py``'s SMTP
loading already use): a reset that only blocked "Production" by name
would leave Staging's database one flag away from being wiped, which is
not a meaningfully safer script. This guard cannot be bypassed by any
flag.

Even in Development/Testing, a reset additionally requires interactive
confirmation (type the environment name back) unless ``--yes`` is
passed, since this is an irreversible, destructive operation against
whatever database ``DATABASE_URL`` currently points at.

Usage:
    python scripts/reset_database.py
    python scripts/reset_database.py --yes              # skip the interactive prompt (e.g. CI)
    python scripts/reset_database.py --seed
    python scripts/reset_database.py --yes --seed --email dev@example.com
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic import command

from app.config.exceptions import ConfigurationError
from app.config.logging_config import configure_logging, get_logger
from app.config.settings import AppSettings

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from initialize_db import (  # noqa: E402 - path must be set up first, see above
    build_alembic_config,
    seed_if_requested,
    verify_environment,
)

logger = get_logger(__name__)


class ProductionResetRefusedError(RuntimeError):
    """Raised when a reset is attempted against an environment that
    requires production-grade hardening (Staging or Production).

    Attributes:
        message: A human-readable description of the refusal.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ResetNotConfirmedError(RuntimeError):
    """Raised when a reset proceeds without the required confirmation.

    Attributes:
        message: A human-readable description of the refusal.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _require_non_production(settings: AppSettings) -> None:
    """Refuse outright if the detected environment requires production-grade hardening.

    Args:
        settings: The loaded application settings.

    Raises:
        ProductionResetRefusedError: If ``settings.environment`` is
            Staging or Production. There is no flag that overrides this.
    """
    if settings.environment.requires_production_grade_hardening:
        raise ProductionResetRefusedError(
            f"Refusing to reset the database: environment "
            f"'{settings.environment.value}' requires production-grade "
            f"hardening. This script is for local development use only "
            f"and has no override for this check."
        )


def _confirm(settings: AppSettings, *, assume_yes: bool) -> None:
    """Require explicit confirmation before destroying the schema.

    Args:
        settings: The loaded settings, used to name the target
            environment and project in the confirmation prompt.
        assume_yes: If ``True``, skip the interactive prompt (for
            scripted/CI use) — the caller is responsible for having
            decided that is appropriate.

    Raises:
        ResetNotConfirmedError: If confirmation is required but not
            given (a non-interactive session without ``--yes``, or a
            typed response that does not match).
    """
    if assume_yes:
        logger.warning("--yes passed; skipping interactive confirmation.")
        return
    if not sys.stdin.isatty():
        raise ResetNotConfirmedError(
            "Refusing to reset the database non-interactively without --yes."
        )

    prompt = (
        f"This will PERMANENTLY DROP every table this project manages in "
        f"the '{settings.environment.value}' database at "
        f"{settings.supabase.url} and recreate them empty.\n"
        f"Type the environment name ('{settings.environment.value}') to confirm: "
    )
    response = input(prompt).strip()
    if response != settings.environment.value:
        raise ResetNotConfirmedError("Confirmation did not match; aborting reset.")


def reset_schema() -> None:
    """Tear down and rebuild the schema via Alembic's own downgrade/upgrade paths.

    Delegates entirely to Alembic's ``downgrade``/``upgrade`` commands —
    this function issues no SQL of its own. Every object dropped and
    recreated is exactly what ``app/database/migrations/versions/``'s
    own ``upgrade()``/``downgrade()`` functions already define.
    """
    logger.info("Reverting all migrations (alembic downgrade base)...")
    command.downgrade(build_alembic_config(), "base")
    logger.info("Reapplying all migrations (alembic upgrade head)...")
    command.upgrade(build_alembic_config(), "head")
    logger.info("Schema reset complete.")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for this script.

    Args:
        argv: The argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt (e.g. for CI).",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Reseed a development admin user after reset (Development/Testing only).",
    )
    parser.add_argument(
        "--email", default=None, help="Admin email for --seed (forwarded to seed_demo_data.py)."
    )
    parser.add_argument(
        "--password", default=None, help="Admin password for --seed (forwarded to seed_demo_data.py)."
    )
    parser.add_argument(
        "--full-name",
        default=None,
        help="Admin display name for --seed (forwarded to seed_demo_data.py).",
    )
    return parser.parse_args(argv)


def _build_seed_argv(args: argparse.Namespace) -> list[str]:
    """Translate this script's seed-related flags into ``seed_demo_data.main``'s argv.

    Identical in shape to ``initialize_db.py``'s own helper of the same
    name — kept local rather than imported, since it depends only on
    this script's own ``argparse.Namespace`` shape, not on any shared
    state ``initialize_db.py`` owns.

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
    """Entry point: verify configuration, guard, confirm, reset, and optionally reseed.

    Args:
        argv: The argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: ``0`` on success, ``1`` on any failure or refusal.
    """
    configure_logging("INFO")
    args = _parse_args(argv)
    try:
        settings = verify_environment()
        _require_non_production(settings)
        _confirm(settings, assume_yes=args.yes)
        reset_schema()
        seed_if_requested(seed=args.seed, settings=settings, seed_argv=_build_seed_argv(args))
    except (ConfigurationError, ProductionResetRefusedError, ResetNotConfirmedError) as exc:
        logger.error("Database reset aborted: %s", exc.message)
        return 1
    except Exception as exc:  # noqa: BLE001 - top-level CLI failure boundary
        logger.error("Database reset failed: %s", exc, exc_info=exc)
        return 1

    logger.info("Database reset complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
