"""Filesystem path management for the Enterprise Automation Hub.

This module centralizes every filesystem path the application needs to
reference — the project root, the Alembic migrations directory (owned by
``app.database.migrations``, per DSD Section 15), and the location of the
``.env`` file — so that no other module in the codebase constructs a
``Path`` relative to ``__file__`` on its own.

Per the Deployment Guide (DG Section 4), EAH's deployment artifact is a
plain Python source tree with no build step; every path here is derived
purely from this file's own location within that tree, with no
environment-variable or configuration dependency, which is what allows
this module to be imported before configuration has been loaded at all.

This module performs no I/O at import time — no directory is created and
no file is read merely by importing this module. Directory creation, where
needed, is performed only by the explicit ``ensure_directory`` function
below, called by startup code that has decided it actually needs the
directory to exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

#: The project's root directory, computed relative to this file's own
#: location (``<project_root>/app/config/paths.py``), so that this
#: constant is correct regardless of the current working directory the
#: application happens to be started from.
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: The ``app`` package's own directory.
APP_DIR: Final[Path] = PROJECT_ROOT / "app"

#: The ``app.database`` package's directory.
DATABASE_PACKAGE_DIR: Final[Path] = APP_DIR / "database"

#: The Alembic migrations directory owned by ``app.database.migrations``
#: (DSD Section 15, DG Section 11). This module only references the
#: location; it neither creates migration files nor imports Alembic.
DATABASE_MIGRATIONS_DIR: Final[Path] = DATABASE_PACKAGE_DIR / "migrations"

#: The ``app.config`` package's own directory.
CONFIG_PACKAGE_DIR: Final[Path] = APP_DIR / "config"

#: The expected location of the populated ``.env`` file, per the
#: repository's ``.env.example`` convention. This module does not read
#: this file itself — reading and parsing it is the responsibility of
#: whatever process bootstraps the environment before
#: ``settings.load_settings`` is called (for example, ``python-dotenv``
#: invoked at process entry, per the project's declared dependencies).
ENV_FILE_PATH: Final[Path] = PROJECT_ROOT / ".env"

#: The example environment file committed to source control.
ENV_EXAMPLE_FILE_PATH: Final[Path] = PROJECT_ROOT / ".env.example"

#: A default local log directory, used only if a future file-based log
#: handler is configured; the Deployment Guide's default logging strategy
#: (DG Section 14) writes to stdout/stderr for hosting-platform log
#: aggregation and does not require this directory to exist.
LOG_DIR: Final[Path] = PROJECT_ROOT / "logs"


def ensure_directory(path: Path) -> Path:
    """Ensure a directory exists, creating it (and any missing parents) if not.

    This is the only function in this module that performs filesystem
    I/O. It is never called automatically at import time; a caller
    invokes it explicitly when it has determined a given directory is
    actually needed (for example, before attaching a file-based log
    handler).

    Args:
        path: The directory path to ensure exists.

    Returns:
        The same ``path``, for convenient chaining at the call site.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_within_project(*parts: str) -> Path:
    """Resolve a path relative to the project root.

    Args:
        *parts: One or more path components to join onto
            ``PROJECT_ROOT``.

    Returns:
        The resolved, absolute ``Path``.
    """
    return PROJECT_ROOT.joinpath(*parts)