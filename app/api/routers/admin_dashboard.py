"""Routes for the admin Dashboard: composed at request time from existing
services/repositories, per this phase's "reuse Analytics components
wherever possible" instruction. No new aggregation logic beyond simple
composition of already-existing reads:

- ``total_users``/``department_count``: the same ``admin_shared``
  composition the Users/Departments modules use.
- ``pending_approvals_count``: ``ApprovalService.list_pending_approvals``,
  the same method the existing per-caller dashboard already calls (here
  called with the admin caller's own identity, since no organization-wide
  "all pending, regardless of assignee" method exists either).
- ``workflow_definition_counts``: one ``list_versions`` call per known
  request type (the frontend's own ``REQUEST_TYPES`` list) — there is no
  cross-type "count every definition" method anywhere in
  ``WorkflowDefinitionService`` (confirmed by audit), so this is honestly
  scoped to "definitions for known request types," not "all definitions."
- ``recent_activity``: ``AuditRepository.list_all``, the same call and
  actor-name-resolution technique ``list_recent_activity`` already uses
  in ``app.api.routers.analytics``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import (
    get_approval_service,
    get_audit_repository,
    get_current_identity,
    get_profile_repository,
    get_workflow_definition_service,
)
from app.api.routers.admin_shared import fetch_all_profiles, group_profiles_by_department
from app.api.schemas.analytics import AuditLogEntryOut
from app.auth import rbac
from app.auth.authentication import AuthenticatedIdentity
from app.database.exceptions import RecordNotFoundError
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page
from app.database.repositories.user_repository import ProfileRepository
from app.models.enums import AuditAction, UserRole
from app.services.approval_service import ApprovalService
from app.services.workflow_definition_service import WorkflowDefinitionService
from app.utils.response import build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["admin-dashboard"])

#: The request types this frontend already knows about (mirrors
#: ``frontend/src/features/requests/constants.ts``'s ``REQUEST_TYPES``) —
#: used only to enumerate workflow-definition counts per type, since no
#: cross-type "list every definition" method exists anywhere in
#: ``WorkflowDefinitionService``.
_KNOWN_REQUEST_TYPES = ["expense_reimbursement"]

_RECENT_ACTIVITY_LIMIT = 10


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/admin/dashboard")
def get_admin_dashboard(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    approval_service: ApprovalService = Depends(get_approval_service),
    workflow_definition_service: WorkflowDefinitionService = Depends(
        get_workflow_definition_service
    ),
) -> dict[str, Any]:
    """Composed administration overview. Admin only."""
    rbac.require_role(identity.role, UserRole.ADMIN)

    profiles = fetch_all_profiles(profile_repo, company_id=identity.company_id)
    grouped = group_profiles_by_department(profiles)

    pending_page = approval_service.list_pending_approvals(identity, page=Page(number=1, size=1))

    workflow_definition_counts: dict[str, int] = {}
    for request_type in _KNOWN_REQUEST_TYPES:
        result = workflow_definition_service.list_versions(
            identity, request_type, page=Page(number=1, size=1)
        )
        workflow_definition_counts[request_type] = result.total_records

    activity_page = audit_repo.list_all(
        company_id=identity.company_id, page=Page(number=1, size=_RECENT_ACTIVITY_LIMIT)
    )
    names_by_actor: dict[UUID, str | None] = {}
    recent_activity: list[dict[str, Any]] = []
    for entry in activity_page.items:
        actor_name: str | None = None
        if entry.actor_id is not None:
            if entry.actor_id not in names_by_actor:
                try:
                    names_by_actor[entry.actor_id] = profile_repo.get_by_id(
                        entry.actor_id
                    ).full_name
                except RecordNotFoundError:
                    names_by_actor[entry.actor_id] = None
            actor_name = names_by_actor[entry.actor_id]
        recent_activity.append(
            serialize(
                AuditLogEntryOut(
                    id=entry.id,
                    actor_id=entry.actor_id,
                    actor_name=actor_name,
                    request_id=entry.request_id,
                    action=AuditAction(entry.action),
                    metadata=entry.metadata,
                    created_at=entry.created_at,
                )
            )
        )

    data = {
        "total_users": len(profiles),
        "department_count": len(grouped),
        "pending_approvals_count": pending_page.total_records,
        "workflow_definition_counts": workflow_definition_counts,
        "recent_activity": recent_activity,
    }
    return build_success_response(data, request_id=_request_id_of(request))
