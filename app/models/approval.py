"""Domain models for approval and rejection decisions.

Unlike the other modules in this package, these models do not correspond
one-to-one with a database table — they represent the input and output
shapes of the decision-specific operations ``ApprovalService`` performs
against a ``workflow_stages`` row (WEDD Section 6), matching
``POST /api/v1/workflow-stages/{id}/approve`` and ``.../reject``
(API-ADD Sections 19.5.1-19.5.2).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.models.base import DecisionNote, EAHBaseModel
from app.models.enums import RequestStatus, UserRole
from app.models.workflow import WorkflowStage

__all__ = [
    "ApprovalDecisionRequest",
    "RejectionDecisionRequest",
    "ApprovalOutcome",
    "EscalationOutcome",
]


class ApprovalDecisionRequest(EAHBaseModel):
    """Input model for ``POST /api/v1/workflow-stages/{id}/approve``
    (API-ADD Section 19.5.1).

    Attributes:
        decision_note: An optional note (up to 1,000 characters), if
            provided must be non-empty after whitespace stripping.
        expected_version: The stage's ``version`` last observed by the
            caller, used for an explicit optimistic-locking check (WEDD
            Section 14.4) in addition to the implicit one always
            performed server-side.
    """

    decision_note: DecisionNote | None = None
    expected_version: int | None = Field(default=None, ge=1)


class RejectionDecisionRequest(EAHBaseModel):
    """Input model for ``POST /api/v1/workflow-stages/{id}/reject``
    (API-ADD Section 19.5.2).

    Attributes:
        decision_note: The required reason for rejection (WEDD Section
            6.6), 1-1,000 characters after whitespace stripping.
        expected_version: The stage's ``version`` last observed by the
            caller.
    """

    decision_note: DecisionNote
    expected_version: int | None = Field(default=None, ge=1)


class ApprovalOutcome(EAHBaseModel):
    """The result of a successful approve or reject operation.

    Corresponds to the response body documented in API-ADD Section
    19.5.1: the decided stage together with the resulting request-level
    state, without requiring the caller to fetch the full ``Request``
    separately just to observe its post-decision status.

    Attributes:
        stage: The stage as it now stands, post-decision.
        request_status: The request's lifecycle status immediately after
            this decision (WEDD Section 10.1's state transition table).
        current_stage_id: The request's new current stage, if any
            further stage was generated; ``None`` if the request reached
            a terminal status.
    """

    stage: WorkflowStage
    request_status: RequestStatus
    current_stage_id: UUID | None = None


class EscalationOutcome(EAHBaseModel):
    """The result of a Scheduler-driven escalation reassignment (WEDD
    Section 8.4).

    Attributes:
        stage: The stage as it now stands, post-reassignment (``status``
            remains unchanged; only assignment fields differ).
        previous_assigned_to: The specific user previously assigned, if
            any, prior to escalation.
        previous_assigned_role: The role previously eligible, if any,
            prior to escalation.
    """

    stage: WorkflowStage
    previous_assigned_to: UUID | None = None
    previous_assigned_role: UserRole | None = None
