"""Custom exception hierarchy for the app.workflow package.

Mirroring the pattern already established in ``app.database.exceptions``,
``app.models.exceptions``, ``app.config.exceptions``, ``app.utils.exceptions``,
and ``app.auth.exceptions``, every exception the Workflow Engine can raise
is defined here, exactly once. Each branch corresponds to one of the four
internal collaborators described in WEDD Section 2.1
(``DefinitionResolver``, ``StageGenerator``, ``AssignmentResolver``,
``EscalationManager``) plus the version-management and state-machine
concerns that sit alongside them.

Every exception here is a pure domain-logic failure — a definition that
cannot be resolved, a stage sequence that is internally inconsistent, an
illegal state transition. None of them wrap a database or network
failure (those belong to ``app.database.exceptions``, raised by a future
Repository Layer caller, never by this package, which performs no I/O of
its own).
"""

from __future__ import annotations


class WorkflowError(Exception):
    """Base class for every exception raised by the app.workflow package.

    Attributes:
        message: A human-readable description of the failure.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{self.__class__.__name__}(message={self.message!r})"


# ---------------------------------------------------------------------------
# DefinitionResolver failures (WEDD Section 5.3, Section 9)
# ---------------------------------------------------------------------------


class DefinitionResolutionError(WorkflowError):
    """Base class for failures resolving a workflow definition."""


class NoActiveDefinitionError(DefinitionResolutionError):
    """Raised when no active ``WorkflowDefinition`` exists for a request type.

    Corresponds to the trigger for API-ADD's ``422 INVALID_REQUEST_TYPE``
    (WEDD Section 5.3) — this package raises the underlying domain
    condition; translating it into that specific HTTP-shaped error is a
    future Application/API-binding layer's responsibility.

    Attributes:
        request_type: The request type for which no active definition
            was found.
    """

    def __init__(self, request_type: str) -> None:
        super().__init__(f"No active workflow definition exists for request type '{request_type}'.")
        self.request_type = request_type


class MultipleActiveDefinitionsError(DefinitionResolutionError):
    """Raised when more than one candidate definition for the same
    request type is marked active.

    This should never occur if the atomic activation transaction
    described in DSD Section 11 and WEDD Section 9.2 has been correctly
    applied — this exception exists as a defensive, fail-fast check
    against that invariant being violated (for example, by a defect
    upstream, or by test fixtures constructed incorrectly), rather than
    something this package expects to occur in correct operation.

    Attributes:
        request_type: The request type with more than one active
            definition.
        active_definition_ids: The ids of the conflicting active
            definitions, for diagnostic purposes.
    """

    def __init__(self, request_type: str, active_definition_ids: tuple[str, ...]) -> None:
        super().__init__(
            f"Found {len(active_definition_ids)} active workflow definitions for "
            f"request type '{request_type}'; expected at most one."
        )
        self.request_type = request_type
        self.active_definition_ids = active_definition_ids


# ---------------------------------------------------------------------------
# StageGenerator failures (WEDD Sections 4.6, 6.4-6.5, 13.2)
# ---------------------------------------------------------------------------


class StageGenerationError(WorkflowError):
    """Base class for failures generating a workflow stage's shape."""


class NonSequentialStageOrderError(StageGenerationError):
    """Raised when the next stage's computed order is not exactly one
    greater than the highest already-materialized stage order.

    Corresponds to WEDD Section 13.2's defensive check: "the next order
    is exactly one greater than the current highest."

    Attributes:
        highest_existing_order: The highest ``stage_order`` already
            materialized for the request.
        attempted_next_order: The order value that was attempted, which
            did not satisfy the expected sequence.
    """

    def __init__(self, highest_existing_order: int, attempted_next_order: int) -> None:
        super().__init__(
            f"Next stage order must be exactly {highest_existing_order + 1}, "
            f"got {attempted_next_order}."
        )
        self.highest_existing_order = highest_existing_order
        self.attempted_next_order = attempted_next_order


class StageNotFoundInDefinitionError(StageGenerationError):
    """Raised when a requested stage order does not exist within a
    workflow definition's ``stages`` array.

    Attributes:
        stage_order: The order value that was not found.
    """

    def __init__(self, stage_order: int) -> None:
        super().__init__(f"No stage with order {stage_order} exists in this workflow definition.")
        self.stage_order = stage_order


# ---------------------------------------------------------------------------
# AssignmentResolver failures (WEDD Section 7)
# ---------------------------------------------------------------------------


class AssignmentResolutionError(WorkflowError):
    """Base class for failures resolving a stage's assignment."""


class UnknownAssigneeError(AssignmentResolutionError):
    """Raised when a ``specific_user`` stage's ``assigned_user_id`` does
    not resolve to a known profile.

    Corresponds to API-ADD's ``422 UNKNOWN_ASSIGNEE`` (WEDD Sections 7.2
    and 13.3) — validated at definition-authoring time, since a
    ``specific_user`` reference is never re-validated once the
    definition has been activated (WEDD Section 3.2's immutability
    guarantee).

    Attributes:
        assigned_user_id: The unresolved user id, as a string (kept
            loosely typed here to avoid a hard dependency on ``uuid.UUID``
            formatting at the exception level).
    """

    def __init__(self, assigned_user_id: str) -> None:
        super().__init__(
            f"assigned_user_id '{assigned_user_id}' does not resolve to a known profile."
        )
        self.assigned_user_id = assigned_user_id


# ---------------------------------------------------------------------------
# EscalationManager failures (WEDD Section 8)
# ---------------------------------------------------------------------------


class EscalationError(WorkflowError):
    """Base class for failures in escalation planning."""


class InvalidEscalationConfigurationError(EscalationError):
    """Raised when a stage's escalation configuration cannot be used to
    compute a valid threshold (for example, a non-positive
    ``escalation_hours`` value reaching this package despite the Domain
    Layer's own field constraint — a defensive check, not an expected
    occurrence).
    """


# ---------------------------------------------------------------------------
# VersionManager failures (WEDD Section 9)
# ---------------------------------------------------------------------------


class VersionManagementError(WorkflowError):
    """Base class for failures in workflow definition versioning."""


class DefinitionAlreadyActiveError(VersionManagementError):
    """Raised when an activation is attempted against a definition that
    is already the active version for its request type.

    Corresponds to API-ADD's ``409 DUPLICATE_ACTIVATION`` (WEDD Section
    9.2).

    Attributes:
        definition_id: The id of the definition, as a string.
    """

    def __init__(self, definition_id: str) -> None:
        super().__init__(f"Workflow definition '{definition_id}' is already active.")
        self.definition_id = definition_id


class MismatchedRequestTypeError(VersionManagementError):
    """Raised when an activation candidate's ``request_type`` does not
    match the request type of the definition it is meant to replace —
    a defensive check against a programming error, since these two
    values should always agree by construction.

    Attributes:
        candidate_request_type: The candidate definition's request type.
        currently_active_request_type: The currently active definition's
            request type.
    """

    def __init__(self, candidate_request_type: str, currently_active_request_type: str) -> None:
        super().__init__(
            f"Cannot activate a '{candidate_request_type}' definition to replace "
            f"the active '{currently_active_request_type}' definition; "
            "request types must match."
        )
        self.candidate_request_type = candidate_request_type
        self.currently_active_request_type = currently_active_request_type


class DefinitionEditNotAllowedError(VersionManagementError):
    """Raised when an edit is attempted against a definition that is
    already active.

    Corresponds to API-ADD Section 19.9.2: an active definition is never
    mutated in place; a new version must be created instead.

    Attributes:
        definition_id: The id of the definition, as a string.
    """

    def __init__(self, definition_id: str) -> None:
        super().__init__(
            f"Workflow definition '{definition_id}' is active and cannot be edited "
            "in place; create a new version instead."
        )
        self.definition_id = definition_id


# ---------------------------------------------------------------------------
# State machine failures (WEDD Section 10)
# ---------------------------------------------------------------------------


class InvalidStateTransitionError(WorkflowError):
    """Raised when a state transition does not appear in the documented
    state transition table (WEDD Sections 10.1 and 10.3).

    Attributes:
        entity: A short label for the entity whose transition was
            rejected (``"request"`` or ``"workflow_stage"``).
        current_state: The state being transitioned from.
        attempted_state: The state that was attempted.
    """

    def __init__(self, entity: str, current_state: str, attempted_state: str) -> None:
        super().__init__(
            f"Invalid {entity} state transition: '{current_state}' -> '{attempted_state}' "
            "is not a documented transition."
        )
        self.entity = entity
        self.current_state = current_state
        self.attempted_state = attempted_state