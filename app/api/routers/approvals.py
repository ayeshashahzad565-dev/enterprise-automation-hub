"""Routes for the ``approvals`` resource: the pending-approvals inbox,
single-stage decisions, and bulk decisions.

Every handler is a thin wrapper over ``ApprovalService``'s four public
methods (``approve_stage``, ``reject_stage``, ``list_pending_approvals`` —
``escalate_stage`` is scheduler-only and never exposed here, per its own
docstring). ``list_inbox`` additionally enriches each pending
``WorkflowStage`` with its owning request's summary fields via the
already-existing ``RequestService.get_request`` (deduplicated per request
id within a page) — see ``app.api.schemas.approvals.ApprovalInboxItemOut``
for why this composition is pure data-shaping, not new business logic.

``bulk_approve``/``bulk_reject`` loop over the existing single-stage
methods, catching each item's failure independently so one bad item
(stale version, already-decided stage, missing note) doesn't fail the
whole batch — no bulk operation exists in ``ApprovalService`` itself.

The frontend's "Request changes" action is not a distinct capability
here — it calls ``reject_stage`` (the endpoint below), the same as a
plain rejection; see the Phase 3 migration plan's scoping decision.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_approval_service, get_current_identity, get_request_service
from app.api.schemas.approvals import (
    ApprovalInboxItemOut,
    BulkApproveBody,
    BulkDecisionResponse,
    BulkDecisionResultItem,
    BulkRejectBody,
)
from app.auth.authentication import AuthenticatedIdentity
from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database.repositories.base_repository import Page
from app.models.approval import ApprovalDecisionRequest, RejectionDecisionRequest
from app.services.approval_service import ApprovalService
from app.services.exceptions import (
    ConcurrencyError as ServiceConcurrencyError,
)
from app.services.exceptions import EAHError
from app.services.exceptions import (
    NotFoundError as ServiceNotFoundError,
)
from app.services.exceptions import (
    PermissionDeniedError as ServicePermissionDeniedError,
)
from app.services.exceptions import (
    ValidationError as ServiceValidationError,
)
from app.services.request_service import RequestService
from app.utils.pagination import build_pagination_metadata
from app.utils.response import ErrorCode, build_list_response, build_success_response
from app.utils.serialization import serialize, serialize_many

__all__ = ["router"]

router = APIRouter(tags=["approvals"])


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _bulk_item_error(exc: EAHError) -> tuple[str, str]:
    """Map a caught service exception to the ``(error_code, message)``
    pair a single-item request would have answered with.

    Mirrors ``app.api.exception_handlers``'s own ``EAHError`` mapping,
    narrowed to the codes a bulk decision item can actually raise.
    """
    if isinstance(exc, ServiceNotFoundError):
        return ErrorCode.RESOURCE_NOT_FOUND.value, exc.message
    if isinstance(exc, ServiceValidationError):
        return ErrorCode.VALIDATION_ERROR.value, exc.message
    if isinstance(exc, ServicePermissionDeniedError):
        return ErrorCode.PERMISSION_DENIED.value, exc.message
    if isinstance(exc, ServiceConcurrencyError):
        return ErrorCode.CONCURRENT_UPDATE.value, exc.message
    return ErrorCode.INTERNAL_ERROR.value, exc.message


@router.get("/inbox")
def list_inbox(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    approval_service: ApprovalService = Depends(get_approval_service),
    request_service: RequestService = Depends(get_request_service),
) -> dict[str, Any]:
    """The caller's pending-approvals queue, enriched with request summary
    fields. See ``ApprovalService.list_pending_approvals``."""
    result = approval_service.list_pending_approvals(
        identity, page=Page(number=page, size=page_size)
    )

    requests_by_id: dict[UUID, Any] = {}
    items: list[ApprovalInboxItemOut] = []
    for stage in result.items:
        owning_request = requests_by_id.get(stage.request_id)
        if owning_request is None:
            owning_request = request_service.get_request(identity, stage.request_id)
            requests_by_id[stage.request_id] = owning_request
        items.append(
            ApprovalInboxItemOut(
                stage_id=stage.id,
                stage_version=stage.version,
                stage_order=stage.stage_order,
                stage_name=stage.stage_name,
                stage_status=stage.status,
                assigned_role=stage.assigned_role,
                stage_created_at=stage.created_at,
                request_id=owning_request.id,
                request_title=owning_request.title,
                request_type=owning_request.request_type,
                department=owning_request.department,
                requester_id=owning_request.requester_id,
                request_status=owning_request.status,
            )
        )

    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    return build_list_response(
        serialize_many(items), pagination=pagination, request_id=_request_id_of(request)
    )


@router.post("/{stage_id}/approve")
def approve_stage(
    request: Request,
    stage_id: UUID,
    body: ApprovalDecisionRequest,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: ApprovalService = Depends(get_approval_service),
) -> dict[str, Any]:
    """Approve a workflow stage. See ``ApprovalService.approve_stage``."""
    outcome = service.approve_stage(
        identity,
        stage_id,
        expected_version=body.expected_version,
        decision_note=body.decision_note,
    )
    return build_success_response(serialize(outcome), request_id=_request_id_of(request))


@router.post("/{stage_id}/reject")
def reject_stage(
    request: Request,
    stage_id: UUID,
    body: RejectionDecisionRequest,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: ApprovalService = Depends(get_approval_service),
) -> dict[str, Any]:
    """Reject a workflow stage. See ``ApprovalService.reject_stage``.

    Also backs the frontend's "Request changes" action — a labeled UI
    variant of the same call, ``decision_note`` required either way.
    """
    outcome = service.reject_stage(
        identity,
        stage_id,
        expected_version=body.expected_version,
        decision_note=body.decision_note,
    )
    return build_success_response(serialize(outcome), request_id=_request_id_of(request))


@router.post("/bulk-approve")
def bulk_approve(
    request: Request,
    body: BulkApproveBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: ApprovalService = Depends(get_approval_service),
) -> dict[str, Any]:
    """Approve several stages, one ``approve_stage`` call per item.

    Each item's failure is caught independently so one stale/invalid item
    doesn't fail the whole batch — no bulk method exists in
    ``ApprovalService`` itself.
    """
    results: list[BulkDecisionResultItem] = []
    for item in body.items:
        try:
            service.approve_stage(
                identity,
                item.stage_id,
                expected_version=item.expected_version,
                decision_note=item.decision_note,
            )
        except EAHError as exc:
            code, message = _bulk_item_error(exc)
            results.append(
                BulkDecisionResultItem(
                    stage_id=item.stage_id, success=False, error_code=code, error_message=message
                )
            )
        else:
            results.append(BulkDecisionResultItem(stage_id=item.stage_id, success=True))
    return build_success_response(
        serialize(BulkDecisionResponse(results=results)), request_id=_request_id_of(request)
    )


@router.post("/bulk-reject")
def bulk_reject(
    request: Request,
    body: BulkRejectBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: ApprovalService = Depends(get_approval_service),
) -> dict[str, Any]:
    """Reject several stages, one ``reject_stage`` call per item.

    A missing/empty ``decision_note`` on an item surfaces as that item's
    own failure (``VALIDATION_ERROR``), exactly as a single-item request
    would respond — not a whole-batch failure.
    """
    results: list[BulkDecisionResultItem] = []
    for item in body.items:
        try:
            service.reject_stage(
                identity,
                item.stage_id,
                expected_version=item.expected_version,
                decision_note=item.decision_note or "",
            )
        except EAHError as exc:
            code, message = _bulk_item_error(exc)
            results.append(
                BulkDecisionResultItem(
                    stage_id=item.stage_id, success=False, error_code=code, error_message=message
                )
            )
        else:
            results.append(BulkDecisionResultItem(stage_id=item.stage_id, success=True))
    return build_success_response(
        serialize(BulkDecisionResponse(results=results)), request_id=_request_id_of(request)
    )
