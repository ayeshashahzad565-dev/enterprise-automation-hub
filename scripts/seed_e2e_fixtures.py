"""Seed deterministic fixtures for the Playwright E2E suite (``frontend/e2e/``).

Unlike ``scripts/seed_demo_data.py``/``seed_enterprise_demo.py`` (large,
randomized, human-facing demo datasets), this script produces a small,
fully deterministic fixture set the E2E suite's spec files assert
against by fixed email — see ``frontend/e2e/fixtures/test-users.ts``,
which must be kept in sync with the constants below.

Creates two companies (tenants):

- **Acme Corp** (the primary tenant every spec file except
  ``tenant-isolation.spec.ts`` exercises): an employee, an approver, a
  company admin, and a platform admin, plus one active, single-stage
  ``leave_request`` workflow definition whose sole stage is assigned
  directly to Acme's approver (``specific_user``) — deliberately
  simpler than ``seed_demo_data.py``'s multi-stage default, since a
  single deterministic assignee keeps every approve/reject test
  unambiguous about who must act.
- **Globex Inc**: one employee and one approver only, used solely by
  ``tenant-isolation.spec.ts`` to prove Acme's users can never see
  Globex's data (and vice versa). Its own ``leave_request`` workflow
  definition mirrors Acme's so a Globex request can be submitted and
  routed at all.

Follows this package's established seeding conventions: every entity is
created through the real Application Service where one exists
(``CompanyService``, ``WorkflowDefinitionService`` — never a raw
repository insert for business data), refuses to run outside the
``testing`` environment (stricter than ``seed_demo_data.py``'s
``requires_production_grade_hardening`` check, since these fixed,
publicly-known test credentials have no purpose outside a disposable
local/CI Supabase stack), and is idempotent/safe to re-run.

Acme Corp is bootstrapped directly via ``CompanyRepository`` (mirroring
``tests/integration/conftest.py``'s ``make_test_company`` fixture) since
no platform admin identity can exist yet to call the real,
platform-admin-gated ``CompanyService`` — Globex is then created
*through* that service using Acme's freshly-seeded platform admin, the
same bootstrapping order a real deployment's first platform admin would
follow.

Usage:
    python scripts/seed_e2e_fixtures.py
"""

from __future__ import annotations

import sys
from uuid import UUID

from app.auth.authentication import AuthenticatedIdentity
from app.config.environment import Environment
from app.config.logging_config import configure_logging, get_logger
from app.config.settings import load_settings
from app.database.client import SupabaseClientFactory, SupabaseDatabaseClient
from app.database.exceptions import RecordNotFoundError
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page
from app.database.repositories.company_license_repository import CompanyLicenseRepository
from app.database.repositories.company_repository import CompanyRepository
from app.database.repositories.user_repository import ProfileRepository, UserRole
from app.database.repositories.workflow_repository import WorkflowDefinitionRepository
from app.services.company_service import CompanyService
from app.services.workflow_definition_service import WorkflowDefinitionService
from app.workflow.engine import WorkflowEngine

logger = get_logger(__name__)

#: A single fixed, disposable password for every seeded E2E persona —
#: never valid outside a local/CI Supabase stack this script is allowed
#: to run against at all (see ``_guard_environment``).
PASSWORD = "E2eTest123!"  # noqa: S105 - fixed, disposable, local-only test password

ACME = "Acme Corp"
GLOBEX = "Globex Inc"

ACME_EMPLOYEE_EMAIL = "e2e.acme.employee@example.invalid"
ACME_APPROVER_EMAIL = "e2e.acme.approver@example.invalid"
ACME_ADMIN_EMAIL = "e2e.acme.admin@example.invalid"
ACME_PLATFORM_ADMIN_EMAIL = "e2e.platform.admin@example.invalid"
GLOBEX_EMPLOYEE_EMAIL = "e2e.globex.employee@example.invalid"
GLOBEX_APPROVER_EMAIL = "e2e.globex.approver@example.invalid"
GLOBEX_ADMIN_EMAIL = "e2e.globex.admin@example.invalid"


def _guard_environment() -> None:
    settings = load_settings()
    if settings.environment is not Environment.TESTING:
        raise RuntimeError(
            "Refusing to seed E2E fixtures outside the 'testing' environment "
            f"(APP_ENVIRONMENT is currently '{settings.environment.value}'). These "
            "fixtures use fixed, publicly-known credentials that must never exist "
            "against a real hosted project."
        )


def _find_existing_user_id(client: SupabaseDatabaseClient, email: str) -> UUID | None:
    """Look up an existing ``auth.users`` id by email, if one exists.

    Mirrors ``scripts/seed_demo_data.py``'s ``_find_existing_user_id``.
    """
    users = client.auth.admin.list_users(page=1, per_page=200)
    for user in users:
        if getattr(user, "email", None) == email:
            return UUID(user.id)
    return None


def _ensure_user(
    client: SupabaseDatabaseClient,
    profile_repo: ProfileRepository,
    *,
    email: str,
    full_name: str,
    role: UserRole,
    company_id: UUID,
    is_platform_admin: bool = False,
) -> UUID:
    """Create (or repair) a single seeded persona, returning its id.

    Idempotent: a second run against the same stack finds the existing
    ``auth.users`` row by email and repairs its profile (company,
    role, name, platform-admin flag) rather than erroring or duplicating.
    ``company_id``/``is_platform_admin`` have no Application Service
    update path (they are infra-level seed concerns, not fields an
    ordinary API caller may change about themselves or another user) —
    a direct, service-role table update is used for those two fields
    only, matching ``seed_enterprise_demo.py``'s precedent for
    seed-only writes with no corresponding service method.
    """
    user_id = _find_existing_user_id(client, email)
    if user_id is None:
        logger.info("Creating new Supabase Auth user for %s.", email)
        response = client.auth.admin.create_user(
            {
                "email": email,
                "password": PASSWORD,
                "email_confirm": True,
                "user_metadata": {
                    "full_name": full_name,
                    "role": role.value,
                    "company_id": str(company_id),
                },
            }
        )
        user_id = UUID(response.user.id)
    else:
        logger.info("Supabase Auth user for %s already exists (id=%s).", email, user_id)

    try:
        profile_repo.get_by_id(user_id)
    except RecordNotFoundError:
        logger.warning(
            "No profile row was auto-created for %s; the on_auth_user_created "
            "trigger (migration 0002) may not be applied. Creating it directly.",
            email,
        )
        profile_repo.create_profile(
            profile_id=user_id,
            full_name=full_name,
            company_id=company_id,
            role=role,
            is_platform_admin=is_platform_admin,
        )
        return user_id

    client.table("profiles").update(
        {
            "full_name": full_name,
            "role": role.value,
            "company_id": str(company_id),
            "is_platform_admin": is_platform_admin,
        }
    ).eq("id", str(user_id)).execute()
    return user_id


def _find_company_by_name(company_repo: CompanyRepository, name: str) -> UUID | None:
    match = next(
        (c for c in company_repo.list_companies(page=Page(size=100)).items if c.name == name),
        None,
    )
    return match.id if match is not None else None


def _ensure_acme_company(company_repo: CompanyRepository) -> UUID:
    existing_id = _find_company_by_name(company_repo, ACME)
    if existing_id is not None:
        return existing_id
    created = company_repo.create_company(name=ACME, slug="e2e-acme-corp")
    logger.info("Created company %s (%s).", ACME, created.id)
    return created.id


def _ensure_company_via_service(
    company_service: CompanyService,
    company_repo: CompanyRepository,
    identity: AuthenticatedIdentity,
    *,
    name: str,
) -> UUID:
    existing_id = _find_company_by_name(company_repo, name)
    if existing_id is not None:
        return existing_id
    created = company_service.create_company(identity, name=name)
    logger.info("Created company %s (%s) via CompanyService.", name, created.id)
    return created.id


def _ensure_leave_request_definition(
    workflow_service: WorkflowDefinitionService,
    workflow_definition_repo: WorkflowDefinitionRepository,
    identity: AuthenticatedIdentity,
    *,
    approver_id: UUID,
) -> None:
    if (
        workflow_definition_repo.find_active_for_request_type(
            "leave_request", company_id=identity.company_id
        )
        is not None
    ):
        logger.info(
            "leave_request already has an active definition for company %s; skipping.",
            identity.company_id,
        )
        return

    definition = {
        "stages": [
            {
                "order": 1,
                "name": "Manager Approval",
                "assigned_role": "approver",
                "assignment_strategy": "specific_user",
                "assigned_user_id": str(approver_id),
                "escalation_hours": 48,
            }
        ]
    }
    created = workflow_service.create_definition(
        identity, request_type="leave_request", definition=definition
    )
    workflow_service.activate_version(identity, created.id)
    logger.info(
        "Seeded and activated leave_request workflow definition for company %s (version %d).",
        identity.company_id,
        created.version,
    )


def main() -> int:
    configure_logging("INFO")
    _guard_environment()

    settings = load_settings()
    client = SupabaseClientFactory.create_service_role_client(settings.supabase)

    # Every repository is constructed with always_use_injected_client=True
    # (mirroring tests/integration/conftest.py's real_repos fixture): this
    # script runs outside any per-request context, so the service-role
    # client passed here must always be the one used, never whatever the
    # per-request-scoped default would otherwise resolve to.
    profile_repo = ProfileRepository(client, always_use_injected_client=True)
    company_repo = CompanyRepository(client, always_use_injected_client=True)
    license_repo = CompanyLicenseRepository(client, always_use_injected_client=True)
    audit_repo = AuditRepository(client, always_use_injected_client=True)
    workflow_definition_repo = WorkflowDefinitionRepository(client, always_use_injected_client=True)
    workflow_engine = WorkflowEngine()

    workflow_service = WorkflowDefinitionService(
        workflow_definition_repo=workflow_definition_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        workflow_engine=workflow_engine,
    )
    company_service = CompanyService(
        company_repo=company_repo,
        license_repo=license_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
    )

    acme_id = _ensure_acme_company(company_repo)

    platform_admin_id = _ensure_user(
        client,
        profile_repo,
        email=ACME_PLATFORM_ADMIN_EMAIL,
        full_name="E2E Platform Admin",
        role=UserRole.ADMIN,
        company_id=acme_id,
        is_platform_admin=True,
    )
    platform_admin_identity = AuthenticatedIdentity.from_claims(
        {
            "sub": str(platform_admin_id),
            "role": UserRole.ADMIN.value,
            "company_id": str(acme_id),
            "is_platform_admin": True,
        }
    )

    globex_id = _ensure_company_via_service(
        company_service, company_repo, platform_admin_identity, name=GLOBEX
    )

    _ensure_user(
        client,
        profile_repo,
        email=ACME_EMPLOYEE_EMAIL,
        full_name="E2E Acme Employee",
        role=UserRole.EMPLOYEE,
        company_id=acme_id,
    )
    acme_approver_id = _ensure_user(
        client,
        profile_repo,
        email=ACME_APPROVER_EMAIL,
        full_name="E2E Acme Approver",
        role=UserRole.APPROVER,
        company_id=acme_id,
    )
    acme_admin_id = _ensure_user(
        client,
        profile_repo,
        email=ACME_ADMIN_EMAIL,
        full_name="E2E Acme Admin",
        role=UserRole.ADMIN,
        company_id=acme_id,
    )
    _ensure_user(
        client,
        profile_repo,
        email=GLOBEX_EMPLOYEE_EMAIL,
        full_name="E2E Globex Employee",
        role=UserRole.EMPLOYEE,
        company_id=globex_id,
    )
    globex_approver_id = _ensure_user(
        client,
        profile_repo,
        email=GLOBEX_APPROVER_EMAIL,
        full_name="E2E Globex Approver",
        role=UserRole.APPROVER,
        company_id=globex_id,
    )
    globex_admin_id = _ensure_user(
        client,
        profile_repo,
        email=GLOBEX_ADMIN_EMAIL,
        full_name="E2E Globex Admin",
        role=UserRole.ADMIN,
        company_id=globex_id,
    )

    acme_admin_identity = AuthenticatedIdentity.from_claims(
        {"sub": str(acme_admin_id), "role": UserRole.ADMIN.value, "company_id": str(acme_id)}
    )
    _ensure_leave_request_definition(
        workflow_service,
        workflow_definition_repo,
        acme_admin_identity,
        approver_id=acme_approver_id,
    )

    globex_admin_identity = AuthenticatedIdentity.from_claims(
        {"sub": str(globex_admin_id), "role": UserRole.ADMIN.value, "company_id": str(globex_id)}
    )
    _ensure_leave_request_definition(
        workflow_service,
        workflow_definition_repo,
        globex_admin_identity,
        approver_id=globex_approver_id,
    )

    print("E2E fixtures ready. Every seeded persona shares one password.")
    print(f"  password: {PASSWORD}")
    print(f"  Acme employee:       {ACME_EMPLOYEE_EMAIL}")
    print(f"  Acme approver:       {ACME_APPROVER_EMAIL}")
    print(f"  Acme admin:          {ACME_ADMIN_EMAIL}")
    print(f"  Platform admin:      {ACME_PLATFORM_ADMIN_EMAIL}")
    print(f"  Globex employee:     {GLOBEX_EMPLOYEE_EMAIL}")
    print(f"  Globex approver:     {GLOBEX_APPROVER_EMAIL}")
    print(f"  Globex admin:        {GLOBEX_ADMIN_EMAIL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
