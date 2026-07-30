"""Routes for the ``requests`` resource: CRUD, workflow-progress reads,
and the audit trail.

Every handler below is a thin wrapper: it resolves the caller's identity,
calls exactly one existing ``RequestService`` method, and shapes the
result into this app's standard response envelope
(``app.utils.response``). No handler contains business logic of its own —
see ``app.api.schemas`` for the two small HTTP-shape adapters this router
needs (``RequestPatchBody`` for the one field ``app.models.request``
doesn't declare; ``WorkflowProgressOut``/``AuditEntryOut`` to make
``RequestService``'s read-only dataclasses JSON-serializable).

The workflow ``/current`` and ``/history`` sub-routes are pure,
presentation-only slices of the single ``get_workflow_progress`` result —
``RequestService`` exposes no narrower read method for either, and slicing
an already-fetched list by ``stage_order``/``status`` is not business
logic (see the Phase 2 migration plan's "Known backend gaps" section).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import (
    get_approval_service,
    get_current_identity,
    get_request_service,
)
from app.api.schemas.approvals import ApprovalEligibilityOut
from app.api.schemas.audit import AuditEntryOut
from app.api.schemas.requests import RequestPatchBody
from app.api.schemas.workflow import WorkflowProgressOut, WorkflowStageDetailOut
from app.auth.authentication import AuthenticatedIdentity
from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database.repositories.base_repository import Page
from app.models.enums import RequestStatus, StageStatus, UserRole
from app.models.request import RequestCreate
from app.services.approval_service import ApprovalService
from app.services.request_service import RequestService
from app.utils.pagination import build_pagination_metadata
from app.utils.response import build_list_response, build_success_response
from app.utils.serialization import serialize, serialize_many

__all__ = ["router"]

router = APIRouter(tags=["requests"])


def _request_id_of(request: Request) -> str | None:
    """Read the correlation id ``RequestIDMiddleware`` attached to this request."""
    return getattr(request.state, "request_id", None)


@router.post("", status_code=201)
def create_request(
    request: Request,
    body: RequestCreate,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: RequestService = Depends(get_request_service),
) -> dict[str, Any]:
    """Submit a new request. See ``RequestService.create_request``."""
    created = service.create_request(
        identity,
        request_type=body.request_type,
        title=body.title,
        description=body.description,
        department=body.department,
    )
    return build_success_response(serialize(created), request_id=_request_id_of(request))


@router.get("")
def list_or_search_requests(
    request: Request,
    status: RequestStatus | None = Query(None),
    request_type: str | None = Query(None, max_length=200),
    department: str | None = Query(None, max_length=200),
    search: str | None = Query(None, min_length=1, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: RequestService = Depends(get_request_service),
) -> dict[str, Any]:
    """List requests visible to the caller, or free-text search them.

    Dispatches to ``RequestService.search_requests`` when ``search`` is
    provided (in which case ``status``/``request_type``/``department`` are
    ignored — the two service methods' filters are not combinable, see
    the Phase 2 migration plan's "Known backend gaps" section), otherwise
    to ``RequestService.list_requests``.
    """
    page_request = Page(number=page, size=page_size)
    if search:
        result = service.search_requests(identity, search, page=page_request)
    else:
        result = service.list_requests(
            identity,
            status=status,
            request_type=request_type,
            department=department,
            page=page_request,
        )
    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    return build_list_response(
        serialize_many(result.items), pagination=pagination, request_id=_request_id_of(request)
    )


@router.get("/{request_id}")
def get_request(
    request: Request,
    request_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: RequestService = Depends(get_request_service),
) -> dict[str, Any]:
    """Retrieve a single request. See ``RequestService.get_request``."""
    record = service.get_request(identity, request_id)
    return build_success_response(serialize(record), request_id=_request_id_of(request))


@router.patch("/{request_id}")
def update_request(
    request: Request,
    request_id: UUID,
    body: RequestPatchBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: RequestService = Depends(get_request_service),
) -> dict[str, Any]:
    """Update editable fields while the request is pending. See
    ``RequestService.update_request``."""
    updated = service.update_request(
        identity,
        request_id,
        title=body.title,
        description=body.description,
        department=body.department,
        expected_version=body.expected_version,
    )
    return build_success_response(serialize(updated), request_id=_request_id_of(request))


@router.delete("/{request_id}", status_code=204)
def withdraw_request(
    request_id: UUID,
    expected_version: int = Query(..., ge=1),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: RequestService = Depends(get_request_service),
) -> Response:
    """Withdraw (soft-delete) a request. See ``RequestService.withdraw_request``."""
    service.withdraw_request(identity, request_id, expected_version=expected_version)
    return Response(status_code=204)


@router.get("/{request_id}/workflow")
def get_workflow_progress(
    request: Request,
    request_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: RequestService = Depends(get_request_service),
) -> dict[str, Any]:
    """Full, ordered workflow progress. See
    ``RequestService.get_workflow_progress``."""
    progress = service.get_workflow_progress(identity, request_id)
    out = WorkflowProgressOut.model_validate(progress)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/{request_id}/workflow/current")
def get_current_stage(
    request: Request,
    request_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: RequestService = Depends(get_request_service),
) -> Response:
    """The stage currently awaiting a decision, or ``204`` if none.

    A presentation-only slice of ``get_workflow_progress``'s own result —
    see this module's docstring.
    """
    progress = service.get_workflow_progress(identity, request_id)
    current = next(
        (s for s in progress.stages if s.stage_order == progress.current_stage_order), None
    )
    if current is None or current.status is not StageStatus.PENDING:
        return Response(status_code=204)
    out = WorkflowStageDetailOut.model_validate(current)
    body = build_success_response(serialize(out), request_id=_request_id_of(request))
    return JSONResponse(content=body)


@router.get("/{request_id}/workflow/history")
def get_workflow_history(
    request: Request,
    request_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: RequestService = Depends(get_request_service),
) -> dict[str, Any]:
    """Decided stages only, ordered by ``stage_order``.

    A presentation-only slice of ``get_workflow_progress``'s own result —
    see this module's docstring.
    """
    progress = service.get_workflow_progress(identity, request_id)
    decided = [s for s in progress.stages if s.status is not StageStatus.PENDING]
    out = [serialize(WorkflowStageDetailOut.model_validate(s)) for s in decided]
    return build_success_response(out, request_id=_request_id_of(request))


@router.get("/{request_id}/approval-eligibility")
def get_approval_eligibility(
    request: Request,
    request_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> dict[str, Any]:
    """Whether the caller currently has a pending stage on this request
    awaiting their decision.

    A presentation-only slice of ``ApprovalService.list_pending_approvals``
    filtered to one request — that service exposes no request-scoped
    query of its own (see the Phase 3 migration plan's audit). Answers
    ``eligible: false`` rather than 403 for a non-approver/non-admin
    caller, since a page merely asking "can I act on this?" shouldn't
    itself fail for a caller who simply isn't an approver.
    """
    if identity.role not in (UserRole.APPROVER, UserRole.ADMIN):
        out = ApprovalEligibilityOut(eligible=False)
        return build_success_response(serialize(out), request_id=_request_id_of(request))

    result = approval_service.list_pending_approvals(identity, page=Page(size=MAX_PAGE_SIZE))
    match = next((stage for stage in result.items if stage.request_id == request_id), None)
    if match is None:
        out = ApprovalEligibilityOut(eligible=False)
    else:
        out = ApprovalEligibilityOut(
            eligible=True, stage_id=match.id, expected_version=match.version
        )
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/{request_id}/audit-log")
def get_audit_trail(
    request: Request,
    request_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: RequestService = Depends(get_request_service),
) -> dict[str, Any]:
    """Full, chronological audit trail. See ``RequestService.get_audit_trail``."""
    entries = service.get_audit_trail(identity, request_id)
    out = [serialize(AuditEntryOut.model_validate(e)) for e in entries]
    return build_success_response(out, request_id=_request_id_of(request))
