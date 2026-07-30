"""Enterprise demo dataset seeder.

Populates a freshly migrated (empty) database with a realistic,
multi-department enterprise dataset for demoing the application: seven
departments, 50-100 users spanning employee/approver/admin roles, active
workflow definitions for nine request types, and several hundred requests
with a realistic status/type/department mix spread across the last six
months, plus the comments, audit-log entries, and notifications that
naturally result from driving those requests through the real
Application Service layer.

Safe to re-run against a database this script has already seeded:
``seed_users`` upserts by email, ``seed_workflow_definitions`` skips a
request type that already has an active definition, and ``main`` refuses
outright to seed another batch of requests if this company already has
any (pass ``--force`` to add more on purpose) — see each function's own
docstring.

Design principle: every entity that has a real Application Service
method is created *through* that service — ``WorkflowDefinitionService``,
``RequestService``, ``ApprovalService``, ``CommentService`` — never via a
raw repository insert, so every row this script produces is exactly as
valid as one a real user's action would have produced. The one
deliberate exception is backdating ``created_at``/``decided_at``-style
timestamps after creation, via a narrow, direct table update: a fresh
Supabase project has no history, and "every request was submitted in the
last ten minutes" is not a realistic demo dataset. This does not weaken
any business rule — the row is fully valid at the moment the real
service created it; only the recorded timestamp is adjusted afterward.

Refuses to run against Staging/Production, matching every other script
in this package (``scripts/seed_demo_data.py``, ``scripts/reset_database.py``).

Usage:
    python scripts/seed_enterprise_demo.py
    python scripts/seed_enterprise_demo.py --requests 700 --users 80
    python scripts/seed_enterprise_demo.py --admin-email dev@example.com --admin-password "S0meP@ss"
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.auth.authentication import AuthenticatedIdentity
from app.bootstrap import ApplicationResources, build_application_resources
from app.config.logging_config import configure_logging, get_logger
from app.config.settings import AppSettings, load_settings
from app.database.client import SupabaseClientFactory
from app.database.repositories.base_repository import Page
from app.models.enums import UserRole

logger = get_logger(__name__)

DEPARTMENTS: list[str] = [
    "Finance",
    "HR",
    "Procurement",
    "IT",
    "Operations",
    "Legal",
    "Marketing",
]

FIRST_NAMES = [
    "Olivia",
    "Liam",
    "Emma",
    "Noah",
    "Ava",
    "Ethan",
    "Sophia",
    "Mason",
    "Isabella",
    "Lucas",
    "Mia",
    "Elijah",
    "Amelia",
    "James",
    "Harper",
    "Benjamin",
    "Evelyn",
    "Henry",
    "Abigail",
    "Alexander",
    "Ella",
    "Michael",
    "Scarlett",
    "Daniel",
    "Grace",
    "Matthew",
    "Chloe",
    "Samuel",
    "Victoria",
    "David",
    "Lily",
    "Joseph",
    "Hannah",
    "Owen",
    "Zoey",
    "Wyatt",
    "Nora",
    "John",
    "Layla",
    "Jack",
    "Aria",
    "Luke",
    "Riley",
    "Jayden",
    "Zara",
    "Dylan",
    "Maya",
    "Isaac",
    "Aisha",
    "Ryan",
    "Priya",
    "Arjun",
    "Fatima",
    "Kevin",
    "Sana",
    "Omar",
    "Leah",
    "Carlos",
    "Elena",
    "Ahmed",
    "Nadia",
]
LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Hernandez",
    "Lopez",
    "Gonzalez",
    "Wilson",
    "Anderson",
    "Thomas",
    "Taylor",
    "Moore",
    "Jackson",
    "Martin",
    "Lee",
    "Perez",
    "Thompson",
    "White",
    "Harris",
    "Sanchez",
    "Clark",
    "Ramirez",
    "Lewis",
    "Robinson",
    "Walker",
    "Young",
    "Allen",
    "King",
    "Wright",
    "Scott",
    "Torres",
    "Nguyen",
    "Hill",
    "Flores",
    "Green",
    "Adams",
    "Nelson",
    "Baker",
    "Hall",
    "Rivera",
    "Campbell",
    "Mitchell",
    "Carter",
    "Roberts",
    "Khan",
    "Patel",
    "Shah",
    "Malik",
    "Iqbal",
]

#: Two stages, uniform across every request type for simplicity: a
#: department-scoped manager review, then a named final sign-off. Mirrors
#: the shape of the one pre-existing default (``expense_reimbursement``,
#: see ``scripts/seed_demo_data.py``), trimmed to two stages so all nine
#: types share one easy-to-reason-about structure.
REQUEST_TYPES: dict[str, str] = {
    "leave_request": "Leave",
    "expense_reimbursement": "Expense",
    "purchase_order": "Purchase",
    "access_request": "Access",
    "hardware_request": "Hardware",
    "software_request": "Software",
    "travel_request": "Travel",
    "contract_request": "Contract",
    "recruitment_request": "Recruitment",
}

TITLE_TEMPLATES: dict[str, list[str]] = {
    "leave_request": [
        "Annual leave — {n} days",
        "Sick leave request",
        "Parental leave request",
        "Unpaid leave — personal reasons",
    ],
    "expense_reimbursement": [
        "Client dinner reimbursement",
        "Conference travel expenses",
        "Office supplies reimbursement",
        "Team offsite expenses",
    ],
    "purchase_order": [
        "Laptop replacement order",
        "Office furniture purchase",
        "Software license purchase",
        "Vendor services purchase order",
    ],
    "access_request": [
        "VPN access request",
        "Production database read access",
        "Shared drive access request",
        "Admin console access request",
    ],
    "hardware_request": [
        "New monitor request",
        "Replacement laptop request",
        "Docking station request",
        "Mobile phone upgrade",
    ],
    "software_request": [
        "Design software license",
        "Analytics tool subscription",
        "IDE license request",
        "Project management tool seat",
    ],
    "travel_request": [
        "Client site visit — travel approval",
        "Conference travel approval",
        "Regional office visit",
        "Training travel approval",
    ],
    "contract_request": [
        "Vendor contract renewal",
        "New supplier contract review",
        "Consulting agreement approval",
        "NDA approval request",
    ],
    "recruitment_request": [
        "New headcount approval — {dept}",
        "Backfill approval — {dept}",
        "Contractor-to-FTE conversion",
        "Intern hire approval",
    ],
}

#: Roughly the outcome mix the sprint asked for: mostly resolved
#: (completed/rejected), a meaningful pending/in-review backlog, a small
#: escalated slice, and a small withdrawn slice.
OUTCOME_WEIGHTS: list[tuple[str, float]] = [
    ("completed", 0.45),
    ("rejected", 0.20),
    ("pending", 0.15),
    ("in_review", 0.10),
    ("escalated", 0.05),
    ("withdrawn", 0.05),
]


@dataclass(frozen=True, slots=True)
class SeedUser:
    """A user created by this script, with everything later steps need."""

    id: UUID
    email: str
    full_name: str
    role: UserRole
    department: str | None

    def identity(self) -> AuthenticatedIdentity:
        return AuthenticatedIdentity.from_claims({"sub": str(self.id), "role": self.role.value})


def _require_non_production(settings: AppSettings) -> None:
    if settings.environment.requires_production_grade_hardening:
        raise RuntimeError(
            f"Refusing to seed the enterprise demo dataset: environment "
            f"'{settings.environment.value}' requires production-grade hardening. "
            f"This script is for local/demo use only."
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--users", type=int, default=70, help="Total users to create (50-100 recommended)."
    )
    parser.add_argument(
        "--requests", type=int, default=650, help="Total requests to create (500-1000 recommended)."
    )
    parser.add_argument("--admin-email", default="admin@example.com")
    parser.add_argument("--admin-password", default="ChangeMe123!")
    parser.add_argument("--admin-full-name", default="Jordan Blake (CEO)")
    parser.add_argument(
        "--seed", type=int, default=None, help="Random seed, for reproducible runs."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Create --requests more requests even if this company already has "
            "requests from a prior run (the default refuses, to avoid silently "
            "piling up duplicate demo data)."
        ),
    )
    return parser.parse_args(argv)


def _unique_name_pool(count: int) -> list[str]:
    """Generate ``count`` unique "First Last" names from the pools above."""
    seen: set[str] = set()
    names: list[str] = []
    while len(names) < count:
        candidate = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        if candidate in seen:
            continue
        seen.add(candidate)
        names.append(candidate)
    return names


def _slugify_email(full_name: str, index: int) -> str:
    local = full_name.lower().replace(" ", ".").replace("'", "")
    return f"{local}.{index}@enterprise-automation-hub.demo"


def seed_users(
    resources: ApplicationResources,
    settings: AppSettings,
    *,
    admin_email: str,
    admin_password: str,
    admin_full_name: str,
    total_users: int,
) -> list[SeedUser]:
    """Create the CEO admin plus a realistic role/department roster.

    Distribution: 1 CEO (admin), 1 CIO (admin, IT), two approver-level
    "managers" per department, and the remainder as employees spread
    evenly across departments.
    """
    from app.database.repositories.user_repository import ProfileRepository

    client = SupabaseClientFactory.create_service_role_client(settings.supabase)
    profile_repo = ProfileRepository(client)

    def create_user(
        *, email: str, password: str, full_name: str, role: UserRole, department: str | None
    ) -> SeedUser:
        existing = None
        try:
            users = client.auth.admin.list_users(page=1, per_page=200)
            existing = next((u for u in users if getattr(u, "email", None) == email), None)
        except Exception:  # noqa: BLE001 - listing is best-effort; creation below still validates
            existing = None

        if existing is not None:
            user_id = UUID(existing.id)
        else:
            response = client.auth.admin.create_user(
                {
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": {"full_name": full_name, "role": role.value},
                }
            )
            user_id = UUID(response.user.id)

        try:
            profile = profile_repo.get_by_id(user_id)
            if (
                profile.role is not role
                or profile.full_name != full_name
                or profile.department != department
            ):
                profile_repo.update_profile(
                    user_id,
                    expected_version=profile.version,
                    full_name=full_name,
                    role=role,
                    department=department,
                )
        except Exception:  # noqa: BLE001 - the auth trigger may not have provisioned it yet
            profile_repo.create_profile(
                profile_id=user_id, full_name=full_name, role=role, department=department
            )

        return SeedUser(
            id=user_id, email=email, full_name=full_name, role=role, department=department
        )

    users: list[SeedUser] = []

    ceo = create_user(
        email=admin_email,
        password=admin_password,
        full_name=admin_full_name,
        role=UserRole.ADMIN,
        department=None,
    )
    users.append(ceo)
    logger.info("Seeded CEO admin: %s (id=%s)", ceo.email, ceo.id)

    cio_name = "Priya Chandra (CIO)"
    cio = create_user(
        email="cio@enterprise-automation-hub.demo",
        password="ChangeMe123!",
        full_name=cio_name,
        role=UserRole.ADMIN,
        department="IT",
    )
    users.append(cio)

    remaining = max(total_users - len(users), 0)
    approvers_per_dept = 2
    employee_slots = max(remaining - approvers_per_dept * len(DEPARTMENTS), 0)
    employees_per_dept = max(employee_slots // len(DEPARTMENTS), 3)

    name_pool = iter(
        _unique_name_pool(
            approvers_per_dept * len(DEPARTMENTS) + employees_per_dept * len(DEPARTMENTS) + 10
        )
    )
    index = 0

    for department in DEPARTMENTS:
        for _ in range(approvers_per_dept):
            index += 1
            name = f"{next(name_pool)} ({department} Manager)"
            user = create_user(
                email=_slugify_email(name.split(" (")[0], index),
                password="ChangeMe123!",
                full_name=name,
                role=UserRole.APPROVER,
                department=department,
            )
            users.append(user)

        for _ in range(employees_per_dept):
            index += 1
            name = next(name_pool)
            user = create_user(
                email=_slugify_email(name, index),
                password="ChangeMe123!",
                full_name=name,
                role=UserRole.EMPLOYEE,
                department=department,
            )
            users.append(user)

    logger.info(
        "Seeded %d users (%d admin, %d approver, %d employee).",
        len(users),
        sum(1 for u in users if u.role is UserRole.ADMIN),
        sum(1 for u in users if u.role is UserRole.APPROVER),
        sum(1 for u in users if u.role is UserRole.EMPLOYEE),
    )
    return users


def seed_workflow_definitions(resources: ApplicationResources, ceo: SeedUser) -> None:
    """Create and activate a two-stage workflow definition for every request type.

    Idempotent: a request type that already has an active definition
    (from a prior run of this script against the same database) is left
    untouched rather than given a redundant new version — safe to re-run
    against a non-empty database, not only a freshly reset one.
    """
    from app.services.exceptions import NotFoundError

    ceo_identity = ceo.identity()
    for request_type in REQUEST_TYPES:
        try:
            resources.workflow_definition_service.get_active_version(
                request_type, company_id=ceo_identity.company_id
            )
        except NotFoundError:
            pass
        else:
            logger.info("Skipping %s: an active workflow definition already exists.", request_type)
            continue

        stages = [
            {
                "order": 1,
                "name": "Manager Review",
                "assigned_role": "approver",
                "assignment_strategy": "requester_manager",
                "escalation_hours": 48,
            },
            {
                "order": 2,
                "name": "Final Sign-off",
                "assigned_role": "admin",
                "assignment_strategy": "specific_user",
                "assigned_user_id": str(ceo.id),
                "escalation_hours": 72,
            },
        ]
        created = resources.workflow_definition_service.create_definition(
            ceo_identity, request_type=request_type, definition={"stages": stages}
        )
        resources.workflow_definition_service.activate_version(ceo_identity, created.id)
        logger.info(
            "Seeded and activated workflow definition for %s (version %d).",
            request_type,
            created.version,
        )


def _title_for(request_type: str, department: str) -> str:
    template = random.choice(TITLE_TEMPLATES[request_type])
    return template.format(n=random.choice([1, 2, 3, 5]), dept=department)


def _random_past_datetime(days_back_min: int = 0, days_back_max: int = 182) -> datetime:
    days_back = random.randint(days_back_min, days_back_max)
    seconds_of_day = random.randint(0, 86_399)
    return datetime.now(UTC) - timedelta(days=days_back, seconds=seconds_of_day)


def _backdate(client, table: str, filters: dict[str, str], fields: dict[str, str]) -> None:
    query = client.table(table).update(fields)
    for column, value in filters.items():
        query = query.eq(column, value)
    query.execute()


def _backdate_new_rows(
    client, table: str, *, request_id: UUID, since: datetime, to: datetime
) -> None:
    """Backdate only the rows for ``request_id`` created at/after ``since``.

    A request accumulates multiple audit_logs/notifications rows over its
    lifecycle (creation, each decision, ...). Filtering by ``request_id``
    alone would re-stamp *every* row for that request each time this is
    called, collapsing the whole history onto the latest timestamp.
    Scoping by "created since the real wall-clock moment just before this
    action" isolates only the row(s) that action just inserted.
    """
    (
        client.table(table)
        .update({"created_at": to.isoformat()})
        .eq("request_id", str(request_id))
        .gte("created_at", since.isoformat())
        .execute()
    )


def seed_requests(
    resources: ApplicationResources,
    settings: AppSettings,
    users: list[SeedUser],
    *,
    total_requests: int,
) -> None:
    client = SupabaseClientFactory.create_service_role_client(settings.supabase)

    requesters = [u for u in users if u.role in (UserRole.EMPLOYEE, UserRole.APPROVER)]
    approvers_by_department: dict[str, list[SeedUser]] = {}
    admins = [u for u in users if u.role is UserRole.ADMIN]
    for user in users:
        if user.role is UserRole.APPROVER and user.department:
            approvers_by_department.setdefault(user.department, []).append(user)

    outcomes, weights = zip(*OUTCOME_WEIGHTS, strict=True)

    created_count = 0
    failed_count = 0

    for i in range(total_requests):
        requester = random.choice(requesters)
        request_type = random.choice(list(REQUEST_TYPES))
        department = requester.department or random.choice(DEPARTMENTS)
        title = _title_for(request_type, department)
        outcome = random.choices(outcomes, weights=weights, k=1)[0]
        # The "escalated" outcome calls the real escalate_stage transition,
        # which requires the stage to already be genuinely past its
        # escalation_hours deadline (48h) relative to *now* — since the
        # stage's created_at is backdated to match submitted_at below,
        # submitted_at itself must already be old enough for that to be
        # true by construction, not just "somewhere in the last 6 months."
        submitted_at = (
            _random_past_datetime(days_back_min=10)
            if outcome == "escalated"
            else _random_past_datetime()
        )

        try:
            request = resources.request_service.create_request(
                requester.identity(),
                request_type=request_type,
                title=title,
                description=f"{title} — submitted by {requester.full_name} ({department}).",
                department=department,
            )
        except Exception as exc:  # noqa: BLE001 - one bad request must not abort the whole run
            failed_count += 1
            logger.warning("Failed to create request #%d: %s", i, exc)
            continue

        submitted_at_iso = submitted_at.isoformat()
        _backdate(
            client,
            "requests",
            {"id": str(request.id)},
            {"created_at": submitted_at_iso, "updated_at": submitted_at_iso},
        )
        _backdate(
            client,
            "workflow_stages",
            {"request_id": str(request.id)},
            {"created_at": submitted_at_iso},
        )
        _backdate(
            client,
            "audit_logs",
            {"request_id": str(request.id)},
            {"created_at": submitted_at_iso},
        )
        _backdate(
            client,
            "notifications",
            {"request_id": str(request.id)},
            {"created_at": submitted_at_iso},
        )

        try:
            _advance_request(
                resources,
                client,
                request_id=request.id,
                outcome=outcome,
                submitted_at=submitted_at,
                requester=requester,
                admins=admins,
                approvers_by_department=approvers_by_department,
                users_by_id={u.id: u for u in users},
            )
        except Exception as exc:  # noqa: BLE001 - lifecycle progression is best-effort per request
            logger.warning(
                "Failed to progress request %s to outcome=%s: %s", request.id, outcome, exc
            )

        if random.random() < 0.25:
            try:
                comment = resources.comment_service.add_comment(
                    requester.identity(),
                    request.id,
                    body=random.choice(
                        [
                            "Following up — any update on this?",
                            "Added the missing details as requested.",
                            "Please let me know if you need anything else.",
                            "This is time-sensitive, appreciate a quick look.",
                        ]
                    ),
                )
                comment_at = (submitted_at + timedelta(hours=random.randint(1, 96))).isoformat()
                _backdate(client, "comments", {"id": str(comment.id)}, {"created_at": comment_at})
            except (
                Exception
            ):  # noqa: BLE001 - comments are pure flavor, never worth failing the request over
                pass

        created_count += 1
        if created_count % 50 == 0:
            logger.info("Progress: %d/%d requests created.", created_count, total_requests)

    logger.info("Requests done: %d created, %d failed.", created_count, failed_count)


def _resolve_decider(
    stage_row: dict,
    *,
    admins: list[SeedUser],
    approvers_by_department: dict[str, list[SeedUser]],
    department: str,
    users_by_id: dict[UUID, SeedUser],
) -> SeedUser:
    assigned_to = stage_row.get("assigned_to")
    if assigned_to:
        user = users_by_id.get(UUID(assigned_to))
        if user is not None:
            return user
    candidates = approvers_by_department.get(department) or admins
    return random.choice(candidates or admins)


def _advance_request(
    resources: ApplicationResources,
    client,
    *,
    request_id: UUID,
    outcome: str,
    submitted_at: datetime,
    requester: SeedUser,
    admins: list[SeedUser],
    approvers_by_department: dict[str, list[SeedUser]],
    users_by_id: dict[UUID, SeedUser],
) -> None:
    """Drive a freshly-created request to the target outcome via real ApprovalService calls."""
    if outcome == "pending":
        return  # leave stage 1 exactly as create_request left it

    stage_1 = (
        client.table("workflow_stages")
        .select("*")
        .eq("request_id", str(request_id))
        .eq("stage_order", 1)
        .limit(1)
        .execute()
    ).data
    if not stage_1:
        return
    stage_1 = stage_1[0]
    department = requester.department or ""
    decider_1 = _resolve_decider(
        stage_1,
        admins=admins,
        approvers_by_department=approvers_by_department,
        department=department,
        users_by_id=users_by_id,
    )
    decided_at_1 = submitted_at + timedelta(hours=random.randint(1, 48))

    if outcome == "escalated":
        # stage_1's created_at was already backdated to submitted_at (see
        # seed_requests, which forces submitted_at >= 10 days old for
        # this outcome specifically) — genuinely past the 48h escalation
        # deadline already, so the real transition can be invoked as-is.
        t0 = datetime.now(UTC)
        resources.approval_service.escalate_stage(UUID(stage_1["id"]))
        _backdate_new_rows(client, "audit_logs", request_id=request_id, since=t0, to=decided_at_1)
        _backdate_new_rows(
            client, "notifications", request_id=request_id, since=t0, to=decided_at_1
        )
        return

    if outcome == "withdrawn":
        t0 = datetime.now(UTC)
        # The earlier backdating of created_at/updated_at above bumps this
        # row's version (an UPDATE trigger, not just an app-level concern as
        # its neighboring migration comment implies) — expected_version must
        # be re-read rather than assumed to still be 1 from creation.
        current = (
            client.table("requests").select("version").eq("id", str(request_id)).limit(1).execute()
        ).data[0]
        resources.request_service.withdraw_request(
            requester.identity(), request_id, expected_version=current["version"]
        )
        _backdate_new_rows(client, "audit_logs", request_id=request_id, since=t0, to=submitted_at)
        return

    if outcome == "rejected":
        t0 = datetime.now(UTC)
        resources.approval_service.reject_stage(
            decider_1.identity(),
            UUID(stage_1["id"]),
            decision_note="Does not meet policy requirements.",
        )
        _backdate(
            client,
            "workflow_stages",
            {"id": stage_1["id"]},
            {"decided_at": decided_at_1.isoformat()},
        )
        _backdate_new_rows(client, "audit_logs", request_id=request_id, since=t0, to=decided_at_1)
        _backdate_new_rows(
            client, "notifications", request_id=request_id, since=t0, to=decided_at_1
        )
        return

    # in_review or completed both start by approving stage 1.
    t0 = datetime.now(UTC)
    resources.approval_service.approve_stage(decider_1.identity(), UUID(stage_1["id"]))
    _backdate(
        client, "workflow_stages", {"id": stage_1["id"]}, {"decided_at": decided_at_1.isoformat()}
    )
    # Stage 2 is generated as a side effect of this approval — its own
    # created_at defaults to "real now," which reads as incoherent for a
    # months-old request (a stage "created today" but "decided months
    # ago"). Backdate it to when it was actually generated.
    _backdate(
        client,
        "workflow_stages",
        {"request_id": str(request_id), "stage_order": 2},
        {"created_at": decided_at_1.isoformat()},
    )
    _backdate_new_rows(client, "audit_logs", request_id=request_id, since=t0, to=decided_at_1)
    _backdate_new_rows(client, "notifications", request_id=request_id, since=t0, to=decided_at_1)

    if outcome == "in_review":
        return

    stage_2 = (
        client.table("workflow_stages")
        .select("*")
        .eq("request_id", str(request_id))
        .eq("stage_order", 2)
        .limit(1)
        .execute()
    ).data
    if not stage_2:
        return
    stage_2 = stage_2[0]
    decider_2 = _resolve_decider(
        stage_2,
        admins=admins,
        approvers_by_department=approvers_by_department,
        department=department,
        users_by_id=users_by_id,
    )
    decided_at_2 = decided_at_1 + timedelta(hours=random.randint(1, 48))
    t1 = datetime.now(UTC)
    resources.approval_service.approve_stage(decider_2.identity(), UUID(stage_2["id"]))
    _backdate(
        client, "workflow_stages", {"id": stage_2["id"]}, {"decided_at": decided_at_2.isoformat()}
    )
    _backdate(
        client, "requests", {"id": str(request_id)}, {"completed_at": decided_at_2.isoformat()}
    )
    _backdate_new_rows(client, "audit_logs", request_id=request_id, since=t1, to=decided_at_2)
    _backdate_new_rows(client, "notifications", request_id=request_id, since=t1, to=decided_at_2)


def main(argv: list[str] | None = None) -> int:
    configure_logging("INFO")
    args = _parse_args(argv)
    if args.seed is not None:
        random.seed(args.seed)

    settings = load_settings()
    try:
        _require_non_production(settings)
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1

    resources = build_application_resources(settings)

    users = seed_users(
        resources,
        settings,
        admin_email=args.admin_email,
        admin_password=args.admin_password,
        admin_full_name=args.admin_full_name,
        total_users=args.users,
    )
    ceo = users[0]
    seed_workflow_definitions(resources, ceo)

    # Requests have no natural identity to dedupe against (randomly
    # generated titles/data each run), so — unlike seed_users' per-user
    # upsert and seed_workflow_definitions' per-request-type skip — the
    # only safe default against a database this script has already
    # seeded is to refuse outright rather than silently pile on another
    # --requests worth of duplicates. --force opts back into the
    # original "always create more" behavior for a deliberate top-up.
    existing = resources.request_service.list_requests(ceo.identity(), page=Page(size=1))
    if existing.total_records > 0 and not args.force:
        logger.error(
            "This company already has %d request(s) — refusing to seed %d more "
            "(pass --force to add more anyway).",
            existing.total_records,
            args.requests,
        )
        return 1

    seed_requests(resources, settings, users, total_requests=args.requests)

    print(
        f"Enterprise demo dataset seeded. Admin login — email: {args.admin_email}  password: {args.admin_password}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
