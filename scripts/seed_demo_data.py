"""Seed a development administrator user and the default workflow definitions.

Creates (or promotes, if it already exists) a Supabase Auth user with
``role="admin"``, so a freshly migrated Supabase project has at least
one account that can sign in and reach every page in the application
(``app/pages/navigation.py``'s ``NAV_ITEMS`` gates ``admin``,
``workflows``, and ``analytics`` behind ``UserRole.ADMIN``/``APPROVER``).
It then seeds an active workflow definition for every request type this
application ships a documented default for — currently
``expense_reimbursement`` (the worked example throughout the API Design
Document and DSD Section 5.2) — since a request can never be submitted
for a type with no active definition
(``app.workflow.definition_resolver.DefinitionResolver.resolve`` raises
``NoActiveDefinitionError``, by design; this script does not, and must
not, weaken that check).

This script uses only the existing, single Supabase client boundary —
``app.database.client.SupabaseClientFactory`` — exactly as
``app.py``'s composition root does; it constructs no client of its own.
Workflow definitions are created through the real
``app.services.workflow_definition_service.WorkflowDefinitionService``
(the same authorization and structural/assignee validation a real
administrator's request would go through), never via a raw repository
insert — seeding is not a license to bypass validation.

It relies on the ``on_auth_user_created`` trigger from migration
``0002_auth_profile_trigger`` to create the matching ``profiles`` row
automatically (passing ``role`` via ``user_metadata`` so the trigger
provisions it as an admin directly); if that trigger is missing for any
reason (e.g. this script is run against a project where migrations
haven't been applied yet), it falls back to creating the profile row
itself via ``ProfileRepository``, so the script is not silently
dependent on migration state it cannot see.

The admin-user step refuses to run against Staging or Production (any
environment where ``Environment.requires_production_grade_hardening`` is
``True``), since a well-known development password has no place outside
a local or CI database — and since that step never runs there,
workflow-definition seeding (which depends on its resulting admin
identity in this script) does not either. The workflow-definition
seeding logic itself (``seed_default_workflow_definitions``) carries no
such restriction of its own — it writes ordinary, idempotent business
configuration, not a credential — so it remains reusable by a future
production-bootstrap script that supplies a real administrator's
identity instead of this script's dev admin.

Usage:
    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --email dev@example.com --password "S0meP@ss" --full-name "Dev Admin"
"""

from __future__ import annotations

import argparse
import logging
import sys
from uuid import UUID

from app.auth.authentication import AuthenticatedIdentity
from app.config.logging_config import configure_logging, get_logger
from app.config.settings import load_settings
from app.database.client import SupabaseClientFactory
from app.database.exceptions import RecordNotFoundError
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.user_repository import ProfileRepository, UserRole
from app.database.repositories.workflow_repository import WorkflowDefinitionRepository
from app.services.workflow_definition_service import WorkflowDefinitionService
from app.workflow.engine import WorkflowEngine

logger = get_logger(__name__)

#: Every request type this application ships a documented, production-
#: quality default workflow definition for. ``expense_reimbursement`` is
#: the sole worked example specified throughout the API Design Document
#: and DSD Section 5.2 — the exact three-stage structure defined there
#: is what DEFAULT_WORKFLOW_DEFINITIONS reproduces below. Add an entry
#: here (and a matching stage list) if this application comes to support
#: additional request types with their own documented default workflow.
DEFAULT_WORKFLOW_DEFINITIONS: dict[str, list[dict[str, object]]] = {
    "expense_reimbursement": [
        {
            "order": 1,
            "name": "Manager Review",
            "assigned_role": "approver",
            "assignment_strategy": "requester_manager",
            "escalation_hours": 48,
        },
        {
            "order": 2,
            "name": "Finance Review",
            "assigned_role": "approver",
            "assignment_strategy": "department_queue",
            "department": "finance",
            "escalation_hours": 72,
        },
        {
            "order": 3,
            "name": "Final Sign-off",
            "assigned_role": "admin",
            "assignment_strategy": "specific_user",
            # assigned_user_id is filled in at seed time with a real,
            # existing administrator's profile id (see
            # seed_default_workflow_definitions) — WorkflowDefinitionService
            # rejects a specific_user stage referencing an unknown profile
            # (WEDD Section 13.3), so this can never be a placeholder value.
            "assigned_user_id": None,
            "escalation_hours": 24,
        },
    ],
}

DEFAULT_EMAIL = "admin@example.com"
DEFAULT_PASSWORD = (
    "ChangeMe123!"  # noqa: S105 - a dev-only default, never valid outside Development/Testing
)
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
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="The admin user's password.")
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
        profile_repo.create_profile(profile_id=user_id, full_name=full_name, role=UserRole.ADMIN)

    logger.info("Development admin ready: %s (id=%s)", email, user_id)
    return user_id


def seed_default_workflow_definitions(*, admin_user_id: UUID) -> None:
    """Seed an active workflow definition for every request type this
    application ships a documented default for (see
    ``DEFAULT_WORKFLOW_DEFINITIONS``).

    Idempotent: a request type that already has an active definition is
    left untouched and skipped, rather than creating a redundant new
    version on every run. Every definition is created and activated
    through the real ``WorkflowDefinitionService`` — the same
    authorization check (administrator-only) and structural/assignee
    validation a real administrator's request would go through — never
    via a raw repository insert.

    Args:
        admin_user_id: The id of an existing ``profiles`` row with
            ``role="admin"``, used both to authorize the creation/
            activation calls and to resolve the ``Final Sign-off``
            stage's ``specific_user`` assignee.

    Raises:
        AuthenticationError-adjacent service exceptions: whatever
            ``WorkflowDefinitionService.create_definition``/
            ``activate_version`` themselves raise on a genuine failure
            (e.g. ``AssignmentError`` if ``admin_user_id`` does not
            resolve to a real profile) — never swallowed here, since a
            seed that silently fails to produce a usable workflow
            definition is worse than one that fails loudly.
    """
    settings = load_settings()
    client = SupabaseClientFactory.create_service_role_client(settings.supabase)

    workflow_definition_repo = WorkflowDefinitionRepository(client)
    profile_repo = ProfileRepository(client)
    audit_repo = AuditRepository(client)
    workflow_engine = WorkflowEngine()
    service = WorkflowDefinitionService(
        workflow_definition_repo=workflow_definition_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        workflow_engine=workflow_engine,
    )

    admin_identity = AuthenticatedIdentity.from_claims(
        {"sub": str(admin_user_id), "role": UserRole.ADMIN.value}
    )

    for request_type, stages in DEFAULT_WORKFLOW_DEFINITIONS.items():
        if workflow_definition_repo.find_active_for_request_type(request_type) is not None:
            logger.info(
                "Workflow definition for request_type=%s is already active; skipping.",
                request_type,
            )
            continue

        resolved_stages = [
            (
                {**stage, "assigned_user_id": str(admin_user_id)}
                if stage.get("assignment_strategy") == "specific_user"
                else stage
            )
            for stage in stages
        ]
        created = service.create_definition(
            admin_identity,
            request_type=request_type,
            definition={"stages": resolved_stages},
        )
        service.activate_version(admin_identity, created.id)
        logger.info(
            "Seeded and activated workflow definition for request_type=%s (version %d).",
            request_type,
            created.version,
        )


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse arguments, seed the admin user and default
    workflow definitions, report the result."""
    configure_logging("INFO")
    args = _parse_args(argv)
    try:
        admin_user_id = seed_admin_user(
            email=args.email, password=args.password, full_name=args.full_name
        )
        seed_default_workflow_definitions(admin_user_id=admin_user_id)
    except RuntimeError as exc:
        logging.getLogger(__name__).error(str(exc))
        return 1
    print(f"Development admin ready — email: {args.email}  password: {args.password}")
    print("Change this password before using this project for anything but local development.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
