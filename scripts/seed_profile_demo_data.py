"""Populate personal demo data for two specific, individually-created test profiles.

``scripts/seed_enterprise_demo.py`` seeds the whole enterprise dataset in
one pass, spreading requests across ~70 randomly-created users. It never
touches accounts created *after* that run — including
``test@example.com`` (employee, IT) and the temp-approver account (approver,
HR), both backfilled by hand once their original ``profiles`` rows were
lost in this session's database reset. Left alone, those two accounts
have zero requests, notifications, or approval history, so every
personal metric/dashboard/queue they see is empty.

This script drives realistic activity through the real Application
Service layer for exactly those two accounts:

- The employee account submits a batch of its own requests (a mix of
  types, statuses, and departments' natural approvers deciding them),
  populating "my requests" / personal activity metrics.
- The approver account is force-assigned as the first-stage decider on a
  batch of new HR-department requests (submitted by real seeded HR
  employees) — there is no Application Service API to choose a specific
  ``requester_manager`` target, so this one row's ``assigned_to`` is set
  directly, the same documented exception class as backdating in
  ``seed_enterprise_demo.py``. From there, every decision (approve/
  reject/escalate) is made via the real ``ApprovalService``, populating
  the approver's personal queue and decision history.

Design principle and backdating approach: identical to
``seed_enterprise_demo.py`` (see its own docstring) — reused directly
rather than re-derived, via a same-directory import.

Refuses to run against Staging/Production, matching every other script
in this package.

Usage:
    python scripts/seed_profile_demo_data.py
    python scripts/seed_profile_demo_data.py --employee-requests 25 --approver-requests 30
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seed_enterprise_demo as base  # noqa: E402

from app.bootstrap import build_application_resources  # noqa: E402
from app.config.logging_config import configure_logging, get_logger  # noqa: E402
from app.config.settings import load_settings  # noqa: E402
from app.database.client import SupabaseClientFactory  # noqa: E402
from app.models.enums import UserRole  # noqa: E402

logger = get_logger(__name__)

TARGET_EMPLOYEE_EMAIL = "test@example.com"
TARGET_APPROVER_EMAIL = "temp-approver-cb0da8c7@example.com"

#: Biased toward outcomes that actually produce a decision by the target
#: approver (unlike seed_enterprise_demo.py's mix, which is tuned for
#: realistic aggregate department stats, not one specific person's
#: activity history).
APPROVER_OUTCOME_WEIGHTS: list[tuple[str, float]] = [
    ("completed", 0.35),
    ("rejected", 0.25),
    ("in_review", 0.15),
    ("pending", 0.20),
    ("escalated", 0.05),
]

COMMENT_BODIES = [
    "Following up — any update on this?",
    "Added the missing details as requested.",
    "Please let me know if you need anything else.",
    "This is time-sensitive, appreciate a quick look.",
]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--employee-requests", type=int, default=18)
    parser.add_argument("--approver-requests", type=int, default=20)
    parser.add_argument("--seed", type=int, default=None)
    return parser.parse_args(argv)


def _list_all_auth_users(client) -> list:
    all_users = []
    page = 1
    while True:
        resp = client.auth.admin.list_users(page=page, per_page=100)
        if not resp:
            break
        all_users.extend(resp)
        if len(resp) < 100:
            break
        page += 1
    return all_users


def _find_user_id_by_email(client, email: str) -> UUID:
    for user in _list_all_auth_users(client):
        if user.email == email:
            return UUID(user.id)
    raise RuntimeError(f"No auth.users row found for {email!r}.")


def _fetch_profiles(client, **filters: str) -> list[dict]:
    query = client.table("profiles").select("id,full_name,role,department")
    for column, value in filters.items():
        query = query.eq(column, value)
    return query.execute().data


def _seed_user_from_profile(row: dict, email: str = "") -> base.SeedUser:
    return base.SeedUser(
        id=UUID(row["id"]),
        email=email,
        full_name=row["full_name"],
        role=UserRole(row["role"]),
        department=row.get("department"),
    )


def _create_and_backdate_request(
    resources, client, requester: base.SeedUser, *, request_type: str, department: str, submitted_at
):
    title = base._title_for(request_type, department)
    request = resources.request_service.create_request(
        requester.identity(),
        request_type=request_type,
        title=title,
        description=f"{title} — submitted by {requester.full_name} ({department}).",
        department=department,
    )
    submitted_at_iso = submitted_at.isoformat()
    base._backdate(
        client,
        "requests",
        {"id": str(request.id)},
        {"created_at": submitted_at_iso, "updated_at": submitted_at_iso},
    )
    base._backdate(
        client, "workflow_stages", {"request_id": str(request.id)}, {"created_at": submitted_at_iso}
    )
    base._backdate(
        client, "audit_logs", {"request_id": str(request.id)}, {"created_at": submitted_at_iso}
    )
    base._backdate(
        client, "notifications", {"request_id": str(request.id)}, {"created_at": submitted_at_iso}
    )
    return request


def _maybe_add_comment(
    resources, client, author: base.SeedUser, request_id: UUID, submitted_at
) -> None:
    if random.random() >= 0.3:
        return
    try:
        comment = resources.comment_service.add_comment(
            author.identity(), request_id, body=random.choice(COMMENT_BODIES)
        )
        comment_at = (submitted_at + timedelta(hours=random.randint(1, 96))).isoformat()
        base._backdate(client, "comments", {"id": str(comment.id)}, {"created_at": comment_at})
    except Exception:  # noqa: BLE001 - comments are pure flavor, never worth failing over
        pass


def seed_for_employee(
    resources,
    client,
    employee: base.SeedUser,
    *,
    total_requests: int,
    admins: list[base.SeedUser],
    approvers_by_department: dict[str, list[base.SeedUser]],
    users_by_id: dict[UUID, base.SeedUser],
) -> int:
    """Submit a batch of requests as ``employee``, decided by the real department approvers."""
    department = employee.department or ""
    outcomes, weights = zip(*base.OUTCOME_WEIGHTS, strict=True)
    created = 0
    for _ in range(total_requests):
        request_type = random.choice(list(base.REQUEST_TYPES.keys()))
        outcome = random.choices(outcomes, weights=weights, k=1)[0]
        submitted_at = base._random_past_datetime(
            days_back_min=10 if outcome == "escalated" else 0, days_back_max=90
        )
        try:
            request = _create_and_backdate_request(
                resources,
                client,
                employee,
                request_type=request_type,
                department=department,
                submitted_at=submitted_at,
            )
        except Exception as exc:  # noqa: BLE001 - one bad request must not abort the run
            logger.warning("Failed to create employee demo request: %s", exc)
            continue

        try:
            base._advance_request(
                resources,
                client,
                request_id=request.id,
                outcome=outcome,
                submitted_at=submitted_at,
                requester=employee,
                admins=admins,
                approvers_by_department=approvers_by_department,
                users_by_id=users_by_id,
            )
        except Exception as exc:  # noqa: BLE001 - lifecycle progression is best-effort
            logger.warning(
                "Failed to progress employee request %s to outcome=%s: %s", request.id, outcome, exc
            )

        _maybe_add_comment(resources, client, employee, request.id, submitted_at)
        created += 1
    return created


def seed_for_approver(
    resources,
    client,
    approver: base.SeedUser,
    hr_employees: list[base.SeedUser],
    *,
    total_requests: int,
    admins: list[base.SeedUser],
    approvers_by_department: dict[str, list[base.SeedUser]],
    users_by_id: dict[UUID, base.SeedUser],
) -> int:
    """Route a batch of new HR-department requests to ``approver`` for decision."""
    department = approver.department or ""
    outcomes, weights = zip(*APPROVER_OUTCOME_WEIGHTS, strict=True)
    created = 0
    for _ in range(total_requests):
        requester = random.choice(hr_employees)
        request_type = random.choice(list(base.REQUEST_TYPES.keys()))
        outcome = random.choices(outcomes, weights=weights, k=1)[0]
        submitted_at = base._random_past_datetime(
            days_back_min=10 if outcome == "escalated" else 0, days_back_max=75
        )
        try:
            request = _create_and_backdate_request(
                resources,
                client,
                requester,
                request_type=request_type,
                department=department,
                submitted_at=submitted_at,
            )
        except Exception as exc:  # noqa: BLE001 - one bad request must not abort the run
            logger.warning("Failed to create HR demo request: %s", exc)
            continue

        # No Application Service API exists to choose a specific
        # requester_manager target — the same documented, narrow
        # exception class as backdating (see module docstring).
        client.table("workflow_stages").update({"assigned_to": str(approver.id)}).eq(
            "request_id", str(request.id)
        ).eq("stage_order", 1).execute()

        # The reassignment above bypasses whatever assignment notification
        # create_request already sent to the originally-resolved approver
        # (now nobody's real reviewer for this stage) — dispatch the real
        # one to the actual new assignee via the same NotificationService
        # call (and message format) RequestService.create_request itself
        # uses, then backdate it.
        notification = resources.notification_service.notify_assignment(
            recipient_id=approver.id,
            request_id=request.id,
            message=f"You have been assigned to review '{request.title}'.",
        )
        if notification is not None:
            base._backdate(
                client,
                "notifications",
                {"id": str(notification.id)},
                {"created_at": submitted_at.isoformat()},
            )

        try:
            base._advance_request(
                resources,
                client,
                request_id=request.id,
                outcome=outcome,
                submitted_at=submitted_at,
                requester=requester,
                admins=admins,
                approvers_by_department=approvers_by_department,
                users_by_id=users_by_id,
            )
        except Exception as exc:  # noqa: BLE001 - lifecycle progression is best-effort
            logger.warning(
                "Failed to progress HR request %s to outcome=%s: %s", request.id, outcome, exc
            )

        _maybe_add_comment(resources, client, requester, request.id, submitted_at)
        created += 1
    return created


def main(argv: list[str] | None = None) -> int:
    configure_logging("INFO")
    args = _parse_args(argv)
    if args.seed is not None:
        random.seed(args.seed)

    settings = load_settings()
    base._require_non_production(settings)
    resources = build_application_resources(settings)
    client = SupabaseClientFactory.create_service_role_client(settings.supabase)

    employee_id = _find_user_id_by_email(client, TARGET_EMPLOYEE_EMAIL)
    approver_id = _find_user_id_by_email(client, TARGET_APPROVER_EMAIL)
    employee = _seed_user_from_profile(
        _fetch_profiles(client, id=str(employee_id))[0], TARGET_EMPLOYEE_EMAIL
    )
    approver = _seed_user_from_profile(
        _fetch_profiles(client, id=str(approver_id))[0], TARGET_APPROVER_EMAIL
    )

    admins = [_seed_user_from_profile(row) for row in _fetch_profiles(client, role="admin")]
    it_approvers = [
        _seed_user_from_profile(row)
        for row in _fetch_profiles(client, role="approver", department="IT")
    ]
    hr_approvers = [
        _seed_user_from_profile(row)
        for row in _fetch_profiles(client, role="approver", department="HR")
    ] + [approver]
    approvers_by_department = {"IT": it_approvers, "HR": hr_approvers}

    hr_employees = [
        _seed_user_from_profile(row)
        for row in _fetch_profiles(client, role="employee", department="HR")
    ]
    if not hr_employees:
        raise RuntimeError("No HR employees found in the seeded dataset to act as requesters.")

    users_by_id = {
        u.id: u for u in [*admins, *it_approvers, *hr_approvers, employee, approver, *hr_employees]
    }

    employee_created = seed_for_employee(
        resources,
        client,
        employee,
        total_requests=args.employee_requests,
        admins=admins,
        approvers_by_department=approvers_by_department,
        users_by_id=users_by_id,
    )
    approver_created = seed_for_approver(
        resources,
        client,
        approver,
        hr_employees,
        total_requests=args.approver_requests,
        admins=admins,
        approvers_by_department=approvers_by_department,
        users_by_id=users_by_id,
    )

    logger.info(
        "Created %d requests for employee %s and %d requests routed to approver %s.",
        employee_created,
        TARGET_EMPLOYEE_EMAIL,
        approver_created,
        TARGET_APPROVER_EMAIL,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
