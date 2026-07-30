"""The request and workflow-stage state machines.

Per WEDD Section 10, this module encodes, as pure data plus pure
functions, the exact state transition tables already fixed by the API
Design Document (Section 20) and elaborated by the Workflow Engine Design
Document (Sections 10.1 and 10.3). No transition not present in these
tables is ever considered valid, and this module is the single
authoritative source every other collaborator in this package consults
before allowing a status change to proceed conceptually (the actual
database write is, per this package's design, always performed by a
future Repository Layer caller — this module only validates that the
*transition being requested* is a legal one).
"""

from __future__ import annotations

from app.models.enums import RequestStatus, StageStatus
from app.workflow.exceptions import InvalidStateTransitionError

__all__ = [
    "REQUEST_STATUS_TRANSITIONS",
    "STAGE_STATUS_TRANSITIONS",
    "is_valid_request_transition",
    "validate_request_transition",
    "is_terminal_request_status",
    "is_valid_stage_transition",
    "validate_stage_transition",
    "is_terminal_stage_status",
]

#: The complete request state transition table, matching WEDD Section
#: 10.1 exactly. ``RequestStatus.APPROVED`` is reserved for forward
#: compatibility (WEDD Section 20.1) and has no outgoing or incoming
#: transitions in the current baseline, since no code path produces or
#: consumes it.
REQUEST_STATUS_TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    RequestStatus.PENDING: frozenset(
        {RequestStatus.IN_REVIEW, RequestStatus.REJECTED, RequestStatus.COMPLETED}
    ),
    RequestStatus.IN_REVIEW: frozenset(
        {RequestStatus.IN_REVIEW, RequestStatus.COMPLETED, RequestStatus.REJECTED}
    ),
    RequestStatus.APPROVED: frozenset(),
    RequestStatus.COMPLETED: frozenset(),
    RequestStatus.REJECTED: frozenset(),
}

#: The complete workflow-stage state transition table, matching WEDD
#: Section 10.3 exactly. ``PENDING -> PENDING`` is included explicitly to
#: represent the Scheduler's Escalation Check reassignment (WEDD Section
#: 8.4), which changes a stage's assignment fields but never its
#: ``status`` — a legal, documented self-transition, not an omission.
STAGE_STATUS_TRANSITIONS: dict[StageStatus, frozenset[StageStatus]] = {
    StageStatus.PENDING: frozenset(
        {StageStatus.PENDING, StageStatus.APPROVED, StageStatus.REJECTED, StageStatus.SKIPPED}
    ),
    StageStatus.APPROVED: frozenset(),
    StageStatus.REJECTED: frozenset(),
    StageStatus.SKIPPED: frozenset(),
}


def is_valid_request_transition(current: RequestStatus, target: RequestStatus) -> bool:
    """Return whether a request status transition is documented as legal.

    Args:
        current: The request's current status.
        target: The status being transitioned to.

    Returns:
        ``True`` if ``target`` is in the set of legal transitions from
        ``current``, per ``REQUEST_STATUS_TRANSITIONS``.
    """
    return target in REQUEST_STATUS_TRANSITIONS.get(current, frozenset())


def validate_request_transition(current: RequestStatus, target: RequestStatus) -> None:
    """Enforce that a request status transition is documented as legal.

    Args:
        current: The request's current status.
        target: The status being transitioned to.

    Raises:
        InvalidStateTransitionError: If ``target`` is not a legal
            transition from ``current``.
    """
    if not is_valid_request_transition(current, target):
        raise InvalidStateTransitionError("request", current.value, target.value)


def is_terminal_request_status(status: RequestStatus) -> bool:
    """Return whether a request status has no further legal transitions.

    Args:
        status: The status to check.

    Returns:
        ``True`` if ``status`` is a terminal state (``COMPLETED`` or
        ``REJECTED`` in the current baseline).
    """
    return len(REQUEST_STATUS_TRANSITIONS.get(status, frozenset())) == 0


def is_valid_stage_transition(current: StageStatus, target: StageStatus) -> bool:
    """Return whether a workflow-stage status transition is documented as legal.

    Args:
        current: The stage's current status.
        target: The status being transitioned to.

    Returns:
        ``True`` if ``target`` is in the set of legal transitions from
        ``current``, per ``STAGE_STATUS_TRANSITIONS``.
    """
    return target in STAGE_STATUS_TRANSITIONS.get(current, frozenset())


def validate_stage_transition(current: StageStatus, target: StageStatus) -> None:
    """Enforce that a workflow-stage status transition is documented as legal.

    Args:
        current: The stage's current status.
        target: The status being transitioned to.

    Raises:
        InvalidStateTransitionError: If ``target`` is not a legal
            transition from ``current``.
    """
    if not is_valid_stage_transition(current, target):
        raise InvalidStateTransitionError("workflow_stage", current.value, target.value)


def is_terminal_stage_status(status: StageStatus) -> bool:
    """Return whether a workflow-stage status has no further legal transitions.

    Note that ``StageStatus.PENDING`` is *not* terminal despite having a
    self-transition (``PENDING -> PENDING`` for escalation reassignment,
    per WEDD Section 8.4) — a stage remains awaiting a decision until it
    reaches ``APPROVED``, ``REJECTED``, or ``SKIPPED``.

    Args:
        status: The status to check.

    Returns:
        ``True`` if ``status`` is a terminal state (``APPROVED``,
        ``REJECTED``, or ``SKIPPED``).
    """
    if status is StageStatus.PENDING:
        return False
    return len(STAGE_STATUS_TRANSITIONS.get(status, frozenset())) == 0
