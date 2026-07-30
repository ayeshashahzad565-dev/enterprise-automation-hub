"""Routes for the admin Departments module.

``department`` is a free-text string on ``Profile`` — no formal
``Department`` entity, table, or repository exists anywhere in this
codebase (confirmed by audit), so there is no manager-assignment concept
to expose either (honestly omitted). The department list and per-role
member counts are composed via ``app.api.routers.admin_shared`` (see that
module's docstring for the composition rationale); per-department
workload reuses ``AnalyticsProvider.get_department_metrics`` — the same
call ``DepartmentComparePanel`` already uses via the analytics router —
rather than querying ``AnalyticsRepository`` a second, parallel way.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.analytics.interfaces import AnalyticsProvider
from app.api.dependencies import (
    get_analytics_provider,
    get_current_identity,
    get_profile_repository,
)
from app.api.routers.admin_shared import fetch_all_profiles, group_profiles_by_department
from app.api.schemas.admin import UserOut
from app.auth import rbac
from app.auth.authentication import AuthenticatedIdentity
from app.database.repositories.user_repository import ProfileRepository
from app.models.enums import UserRole
from app.utils.response import build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["admin-departments"])


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _require_admin(identity: AuthenticatedIdentity) -> None:
    rbac.require_role(identity.role, UserRole.ADMIN)


@router.get("/admin/departments")
def list_departments(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
) -> dict[str, Any]:
    """Composed department list with per-role member counts. Admin only."""
    _require_admin(identity)
    grouped = group_profiles_by_department(
        fetch_all_profiles(profile_repo, company_id=identity.company_id)
    )
    data = [
        {
            "department": department,
            "member_count": sum(counts.values()),
            "roles": {role.value: count for role, count in counts.items()},
        }
        for department, counts in sorted(grouped.items())
    ]
    return build_success_response(data, request_id=_request_id_of(request))


@router.get("/admin/departments/{department}/workload")
def get_department_workload(
    request: Request,
    department: str,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
    analytics_provider: AnalyticsProvider = Depends(get_analytics_provider),
) -> dict[str, Any]:
    """One department's member list plus its request-volume workload. Admin only."""
    _require_admin(identity)
    members = [
        profile
        for profile in fetch_all_profiles(profile_repo, company_id=identity.company_id)
        if (profile.department or "Unassigned") == department
    ]
    metrics = analytics_provider.get_department_metrics(department, company_id=identity.company_id)
    data = {
        "department": department,
        "member_count": len(members),
        "workload": metrics.workload,
        "members": [serialize(UserOut.model_validate(profile)) for profile in members],
    }
    return build_success_response(data, request_id=_request_id_of(request))
