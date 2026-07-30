"""Verify requirements.txt/requirements-dev.txt still satisfy pyproject.toml.

This is the mechanism that actually prevents `pyproject.toml` and the
generated lockfiles from silently drifting apart again — not a full
`pip-compile` re-resolution diff. A byte-for-byte diff against a freshly
resolved lockfile would flag routine upstream patch releases as "drift"
even though nothing is actually wrong (a lockfile is expected to pin a
point in time); what actually matters is narrower and doesn't need network
access at all: every dependency `pyproject.toml` declares must still be
present in the corresponding lockfile, pinned to a version that satisfies
the declared specifier.

Usage:
    python scripts/check_lockfile_sync.py
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from app.config.paths import PROJECT_ROOT

_PIN_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]+\])?==([^\s;]+)")


def _parse_lockfile_pins(path: Path) -> dict[str, str]:
    """Return {normalized package name: pinned version} for a lockfile."""
    pins: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _PIN_LINE.match(line)
        if match is None:
            continue
        name, _extra, version = match.groups()
        pins[canonicalize_name(name)] = version
    return pins


def _check_group(requirement_strings: list[str], lockfile: Path) -> list[str]:
    """Return a list of human-readable problems, empty if all satisfied."""
    problems: list[str] = []
    pins = _parse_lockfile_pins(lockfile)
    for raw in requirement_strings:
        req = Requirement(raw)
        name = canonicalize_name(req.name)
        pinned = pins.get(name)
        if pinned is None:
            problems.append(f"{lockfile.name}: {req.name} is declared in pyproject.toml but has no pin")
            continue
        if not req.specifier.contains(pinned, prereleases=True):
            problems.append(
                f"{lockfile.name}: {req.name}=={pinned} no longer satisfies "
                f"pyproject.toml's constraint '{req.specifier}'"
            )
    return problems


def main() -> int:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    prod_deps: list[str] = pyproject["project"]["dependencies"]
    dev_deps: list[str] = pyproject["project"]["optional-dependencies"]["dev"]

    problems = _check_group(prod_deps, PROJECT_ROOT / "requirements.txt")
    # requirements-dev.txt covers the full dev closure, which is a superset
    # of the production dependencies (the app is installed editable
    # alongside its own runtime deps) — check both groups against it.
    problems += _check_group(prod_deps + dev_deps, PROJECT_ROOT / "requirements-dev.txt")

    if problems:
        print("Lockfiles are out of sync with pyproject.toml:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nRegenerate with pip-compile (see requirements.txt's own header "
            "comment for the exact command), then commit the result.",
            file=sys.stderr,
        )
        return 1

    print("requirements.txt and requirements-dev.txt are in sync with pyproject.toml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
