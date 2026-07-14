"""Seed a development administrator user.

Creates (or promotes, if it already exists) a Supabase Auth user with
``role="admin"``, so a freshly migrated Supabase project has at least
one account that can sign in and reach every page in the application
(``app/pages/navigation.py``'s ``NAV_ITEMS`` gates ``admin``,
``workflows``, and ``analytics`` behind ``UserRole.ADMIN``/``APPROVER``).

This script uses only the existing, single Supabase client boundary —
``app.database.client.SupabaseClientFactory`` — exactly as
``app.py``'s composition root does; it constructs no client of its own.
It relies on the ``on_auth_user_created`` trigger from migration
``0002_auth_profile_trigger`` to create the matching ``profiles`` row
automatically (passing ``role`` via ``user_metadata`` so the trigger
provisions it as an admin directly); if that trigger is missing for any
reason (e.g. this script is run against a project where migrations
haven't been applied yet), it falls back to creating the profile row
itself via ``ProfileRepository``, so the script is not silently
dependent on migration state it cannot see.

Refuses to run against Staging or Production (any environment where
``Environment.requires_production_grade_hardening`` is ``True``), since
a well-known development password has no place outside a local or CI
database.

Usage:
    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --email dev@example.com --password "S0meP@ss" --full-name "Dev Admin"
"""

from __future__ import annotations

import argparse
import logging
import sys
from uuid import UUID

from app.config.logging_config import configure_logging, get_logger
from app.config.settings import load_settings
from app.database.client import SupabaseClientFactory
from app.database.exceptions import RecordNotFoundError
from app.database.repositories.user_repository import ProfileRepository, UserRole

logger = get_logger(__name__)

DEFAULT_EMAIL = "admin@example.com"
DEFAULT_PASSWORD = "ChangeMe123!"  # noqa: S105 - a dev-only default, never valid outside Development/Testing
DEFAULT_FULL_NAME = "Development Admin"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for this script.

    Args:
        argv: The argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="The admin user's email address.")
    parser.add_argument(
        "--password", default=DEFAULT_PASSWORD, help="The admin user's password."
    )
    parser.add_argument(
        "--full-name", default=DEFAULT_FULL_NAME, help="The admin user's display name."
    )
    return parser.parse_args(argv)


def _find_existing_user_id(client: object, email: str) -> UUID | None:
    """Look up an existing ``auth.users`` id by email, if one exists.

    Args:
        client: A ``SupabaseDatabaseClient`` constructed with the
            service-role key (required for the Admin API this function
            calls).
        email: The address to search for.

    Returns:
        The matching user's id, or ``None`` if no ``auth.users`` row has
        this email. Only the first page of users is searched, which is
        sufficient for a development/seed-time lookup against a small
        project; this is not a general-purpose user search.
    """
    users = client.auth.admin.list_users(page=1, per_page=200)
    for user in users:
        if getattr(user, "email", None) == email:
            return UUID(user.id)
    return None


def seed_admin_user(*, email: str, password: str, full_name: str) -> UUID:
    """Create or promote a development administrator user.

    Args:
        email: The admin user's email address.
        password: The admin user's password.
        full_name: The admin user's display name.

    Returns:
        The resulting user's id.

    Raises:
        RuntimeError: If the detected environment requires
            production-grade hardening (Staging or Production).
    """
    settings = load_settings()
    if settings.environment.requires_production_grade_hardening:
        raise RuntimeError(
            f"Refusing to seed a development admin user in "
            f"'{settings.environment.value}'. This script is for "
            f"Development/Testing use only."
        )

    client = SupabaseClientFactory.create_service_role_client(settings.supabase)
    profile_repo = ProfileRepository(client)

    user_id = _find_existing_user_id(client, email)
    if user_id is None:
        logger.info("Creating new Supabase Auth user for %s.", email)
        response = client.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"full_name": full_name, "role": UserRole.ADMIN.value},
            }
        )
        user_id = UUID(response.user.id)
    else:
        logger.info("Supabase Auth user for %s already exists (id=%s).", email, user_id)

    # The on_auth_user_created trigger (migration 0002) should already
    # have provisioned the profile as an admin via user_metadata above.
    # Promote/repair it explicitly regardless, so this script's outcome
    # does not silently depend on that trigger having been applied.
    try:
        profile = profile_repo.get_by_id(user_id)
        if profile.role is not UserRole.ADMIN or profile.full_name != full_name:
            profile_repo.update_profile(
                user_id,
                expected_version=profile.version,
                full_name=full_name,
                role=UserRole.ADMIN,
            )
            logger.info("Promoted existing profile for %s to admin.", email)
    except RecordNotFoundError:
        logger.warning(
            "No profile row was auto-created for %s; the "
            "on_auth_user_created trigger (migration 0002) may not be "
            "applied. Creating the profile directly.",
            email,
        )
        profile_repo.create_profile(
            profile_id=user_id, full_name=full_name, role=UserRole.ADMIN
        )

    logger.info("Development admin ready: %s (id=%s)", email, user_id)
    return user_id


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse arguments, seed the admin user, report the result."""
    configure_logging("INFO")
    args = _parse_args(argv)
    try:
        seed_admin_user(email=args.email, password=args.password, full_name=args.full_name)
    except RuntimeError as exc:
        logging.getLogger(__name__).error(str(exc))
        return 1
    print(f"Development admin ready — email: {args.email}  password: {args.password}")
    print("Change this password before using this project for anything but local development.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
