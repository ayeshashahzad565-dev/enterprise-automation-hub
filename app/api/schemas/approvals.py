"""HTTP-only schemas for the ``approvals`` resource.

``ApprovalService`` already returns fully-formed, directly serializable
Pydantic models for a single decision (``app.models.approval
.ApprovalDecisionRequest``/``RejectionDecisionRequest`` as input,
``ApprovalOutcome`` as output) — those are reused as-is by
``app.api.routers.approvals`` and need no wrapper here, unlike Phase 2's
``WorkflowProgressOut``/``AuditEntryOut`` (which wrapped plain
dataclasses).

What genuinely doesn't exist yet in ``app.models``:

- ``ApprovalInboxItemOut``: ``ApprovalService.list_pending_approvals``
  returns a bare ``WorkflowStage`` (no request title/type/department/
  requester) — this composes one ``WorkflowStage`` with its owning
  ``Request`` (fetched via the existing ``RequestService.get_request``,
  see the router) into one inbox row. Pure data-shaping of two already-
  authorized reads, not a new persisted entity.
- The bulk approve/reject request/response shapes: ``ApprovalService``
  has no bulk operation of its own; the router loops over the existing
  single-stage ``approve_stage``/``reject_stage`` methods and these
  schemas describe that loop's input/output.
- ``ApprovalEligibilityOut``: backs ``GET /requests/{id}/approval-
  eligibility``, a presentation-only slice of ``list_pending_approvals``
  filtered to one request (same category as Phase 2's ``/workflow/
  current`` slice).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.models.base import DecisionNote, EAHBaseModel, RequestTitle, UTCDatetime
from app.models.enums import RequestStatus, StageStatus, UserRole

__all__ = [
    "ApprovalInboxItemOut",
    "BulkDecisionItem",
    "BulkApproveBody",
    "BulkRejectBody",
    "BulkDecisionResultItem",
    "BulkDecisionResponse",
    "ApprovalEligibilityOut",
]


class ApprovalInboxItemOut(EAHBaseModel):
    """One row of the approval inbox: a pending ``WorkflowStage`` merged
    with its owning ``Request``'s summary fields.

    Attributes:
        stage_id: The stage's id — the identifier every decision action
            (approve/reject/bulk) targets.
        stage_version: The stage's own optimistic-locking ``version``,
            distinct from the request's ``version`` (Phase 2's concurrency
            token for edits/withdrawal) — this is the token
            ``approve_stage``/``reject_stage`` expect as
            ``expected_version``.
        stage_order: The stage's 1-indexed position in its request's
            approval chain.
        stage_name: The stage's human-readable label.
        stage_status: Always ``pending`` for an inbox row.
        assigned_role: The role-eligible queue this stage belongs to, if
            not assigned to a specific user.
        stage_created_at: When this stage began waiting for a decision.
        request_id: The owning request's id.
        request_title: The owning request's title.
        request_type: The owning request's type.
        department: The owning request's department, if any.
        requester_id: The owning request's submitter.
        request_status: The owning request's current lifecycle status.
    """

    stage_id: UUID
    stage_version: int = Field(ge=1)
    stage_order: int = Field(gt=0)
    stage_name: str
    stage_status: StageStatus
    assigned_role: UserRole | None
    stage_created_at: UTCDatetime
    request_id: UUID
    request_title: RequestTitle
    request_type: str
    department: str | None
    requester_id: UUID
    request_status: RequestStatus


class BulkDecisionItem(EAHBaseModel):
    """One item of a bulk approve/reject request.

    Attributes:
        stage_id: The stage to decide.
        expected_version: The stage's last-observed ``version``.
        decision_note: A note — optional for approve, required for
            reject (enforced by ``ApprovalService.reject_stage`` itself,
            surfaced per-item in the response rather than failing the
            whole batch).
    """

    stage_id: UUID
    expected_version: int = Field(ge=1)
    decision_note: DecisionNote | None = None


class BulkApproveBody(EAHBaseModel):
    """Request body for ``POST /api/v1/approvals/bulk-approve``."""

    items: list[BulkDecisionItem] = Field(min_length=1, max_length=100)


class BulkRejectBody(EAHBaseModel):
    """Request body for ``POST /api/v1/approvals/bulk-reject``."""

    items: list[BulkDecisionItem] = Field(min_length=1, max_length=100)


class BulkDecisionResultItem(EAHBaseModel):
    """The outcome of one item within a bulk approve/reject request.

    Attributes:
        stage_id: The stage this result corresponds to.
        success: Whether the decision succeeded.
        error_code: The ``ErrorCode`` value (as a string) if it failed,
            matching the same catalog a single-item request would have
            responded with.
        error_message: A human-readable failure reason, if it failed.
    """

    stage_id: UUID
    success: bool
    error_code: str | None = None
    error_message: str | None = None


class BulkDecisionResponse(EAHBaseModel):
    """Response body for both bulk approve and bulk reject endpoints."""

    results: list[BulkDecisionResultItem]


class ApprovalEligibilityOut(EAHBaseModel):
    """Response body for ``GET /requests/{id}/approval-eligibility``.

    Attributes:
        eligible: Whether the caller currently has a pending stage on
            this request awaiting their decision.
        stage_id: That stage's id, if eligible.
        expected_version: That stage's current ``version``, if eligible
            — ready to send straight back as ``expected_version`` on an
            approve/reject call.
    """

    eligible: bool
    stage_id: UUID | None = None
    expected_version: int | None = None
