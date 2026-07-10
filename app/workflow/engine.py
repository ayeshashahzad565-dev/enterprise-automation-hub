"""The Workflow Engine facade.

Per WEDD Section 2.1: "The Workflow Engine is not a single class; it is
a small internal module composed of four focused collaborators, each
with one responsibility." ``WorkflowEngine`` is that composition: a
single, cohesive entry point over ``DefinitionResolver``,
``StageGenerator``, ``AssignmentResolver``, and ``EscalationManager``
(plus ``VersionManager``, which WEDD Section 9 assigns to the same
"engine" concept even though it is not one of the four collaborators
named in Section 2.1), so that a future Application Service depends on
one injected object rather than five.

None of ``WorkflowEngine``'s methods perform I/O (WEDD Section 2.4-2.5):
every method accepts already-fetched data as plain arguments and returns
a plain result, making this entire class — and every collaborator it
composes — trivially unit-testable without a database, a Supabase
client, or any mock beyond plain Python values (TSD Section 3.2).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from app.models import Profile, StageDefinition, WorkflowDefinition, WorkflowDefinitionDocument
from app.models.enums import RequestStatus, StageStatus, UserRole
from app.workflow.assignment_resolver import AssignmentResolver, AssignmentResult
from app.workflow.definition_resolver import DefinitionResolver
from app.workflow.escalation_manager import EscalationManager, EscalationPlan
from app.workflow.stage_generator import StageGenerator
from app.workflow.state_machine import (
    is_terminal_request_status,
    is_terminal_stage_status,
    validate_request_transition,
    validate_stage_transition,
)
from app.workflow.validators import validate_definition_assignees
from app.workflow.version_manager import VersionManager

__all__ = ["StagePlan", "WorkflowEngine"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StagePlan:
    """A fully resolved plan for materializing one workflow stage.

    Combines ``StageGenerator``'s structural output (order, name) with
    ``AssignmentResolver``'s assignment output into the single shape a
    future ``WorkflowStageRepository.create_stage`` call needs, per WEDD
    Sections 5.4 and 6.4.

    Attributes:
        stage_order: The 1-indexed position of this stage.
        stage_name: The human-readable stage label.
        assigned_to: The specific assignee, if resolved.
        assigned_role: The eligible role, if not assigned to a specific
            user.
        used_fallback: Whether assignment resolution fell back to
            administrator attention (WEDD Section 7.5).
        fallback_reason: The reason for the fallback, if ``used_fallback``
            is ``True``.
        is_final_stage: Whether this stage is the definition's last
            stage — useful for the calling Application Service to decide,
            in advance, whether deciding this stage will complete the
            request.
    """

    stage_order: int
    stage_name: str
    assigned_to: UUID | None
    assigned_role: UserRole | None
    used_fallback: bool
    fallback_reason: str | None
    is_final_stage: bool


class WorkflowEngine:
    """The composed Workflow Engine, per WEDD Section 2.1.

    Every constructor argument is optional and defaults to a concrete
    instance of the corresponding collaborator, so that production code
    can simply write ``WorkflowEngine()``, while unit tests can inject a
    fake or a ``unittest.mock`` double for any single collaborator to
    isolate a specific interaction (TSD Section 3.2).
    """

    def __init__(
        self,
        *,
        definition_resolver: DefinitionResolver | None = None,
        stage_generator: StageGenerator | None = None,
        assignment_resolver: AssignmentResolver | None = None,
        escalation_manager: EscalationManager | None = None,
        version_manager: VersionManager | None = None,
    ) -> None:
        """Initialize the engine, composing its four (plus one) collaborators.

        Args:
            definition_resolver: The ``DefinitionResolver`` to use.
                Defaults to a new ``DefinitionResolver()``.
            stage_generator: The ``StageGenerator`` to use. Defaults to a
                new ``StageGenerator()``.
            assignment_resolver: The ``AssignmentResolver`` to use.
                Defaults to a new ``AssignmentResolver()``.
            escalation_manager: The ``EscalationManager`` to use.
                Defaults to a new ``EscalationManager()``.
            version_manager: The ``VersionManager`` to use. Defaults to a
                new ``VersionManager()``.
        """
        self._definition_resolver = definition_resolver or DefinitionResolver()
        self._stage_generator = stage_generator or StageGenerator()
        self._assignment_resolver = assignment_resolver or AssignmentResolver()
        self._escalation_manager = escalation_manager or EscalationManager()
        self._version_manager = version_manager or VersionManager()

    # ------------------------------------------------------------------
    # Definition resolution (WEDD Sections 5.2-5.3)
    # ------------------------------------------------------------------

    def resolve_definition(
        self, request_type: str, candidates: Sequence[WorkflowDefinition]
    ) -> WorkflowDefinition:
        """Resolve the active workflow definition for a request type.

        Args:
            request_type: The request type to resolve.
            candidates: The candidate definitions already fetched by the
                caller.

        Returns:
            The active ``WorkflowDefinition`` for ``request_type``.

        Raises:
            NoActiveDefinitionError: If no candidate is active for
                ``request_type``.
            MultipleActiveDefinitionsError: If more than one candidate is
                simultaneously active.
        """
        return self._definition_resolver.resolve(request_type, candidates)

    # ------------------------------------------------------------------
    # Stage planning (WEDD Sections 4.3-4.6, 5.4-5.5, 6.4-6.5, 7)
    # ------------------------------------------------------------------

    def plan_first_stage(
        self,
        definition: WorkflowDefinition,
        *,
        requester: Profile,
        department_approvers: Sequence[Profile] = (),
    ) -> StagePlan:
        """Plan the first stage for a newly created request.

        Combines ``StageGenerator.first_stage`` and
        ``AssignmentResolver.resolve`` into a single, ready-to-persist
        plan (WEDD Section 5.4).

        Args:
            definition: The resolved, active workflow definition.
            requester: The requester's profile, consulted only if the
                first stage uses the ``requester_manager`` strategy.
            department_approvers: The candidate approver pool for the
                ``requester_manager`` strategy, if applicable.

        Returns:
            A fully resolved ``StagePlan`` for the first stage.
        """
        stage_def = self._stage_generator.first_stage(definition)
        assignment = self._assignment_resolver.resolve(
            stage_def, requester=requester, department_approvers=department_approvers
        )
        return self._to_stage_plan(definition, stage_def, assignment)

    def plan_next_stage(
        self,
        definition: WorkflowDefinition,
        *,
        current_order: int,
        highest_existing_order: int,
        requester: Profile,
        department_approvers: Sequence[Profile] = (),
    ) -> StagePlan | None:
        """Plan the next stage after a stage has been approved.

        Combines ``StageGenerator.next_stage`` and
        ``AssignmentResolver.resolve`` (WEDD Section 6.4). A ``None``
        result signals that the request should transition to
        ``RequestStatus.COMPLETED`` rather than advancing to a further
        stage (WEDD Section 6.5).

        Important: ``definition`` must be the specific version already
        pinned to the request being advanced (via its
        ``workflow_definition_id``), never a freshly re-resolved active
        definition — this is WEDD Section 9.6's running-workflow
        isolation guarantee, which this method trusts its caller to
        uphold, since a pure function operating only on the arguments it
        is given has no way to independently verify which definition
        "should" have been passed.

        Args:
            definition: The workflow definition pinned to the request.
            current_order: The ``stage_order`` of the stage that was just
                approved.
            highest_existing_order: The highest ``stage_order`` already
                materialized for this request.
            requester: The requester's profile.
            department_approvers: The candidate approver pool for the
                ``requester_manager`` strategy, if applicable.

        Returns:
            A ``StagePlan`` for the next stage, or ``None`` if
            ``current_order`` was the definition's final stage.

        Raises:
            NonSequentialStageOrderError: If ``highest_existing_order``
                does not equal ``current_order``.
        """
        next_stage_def = self._stage_generator.next_stage(
            definition,
            current_order=current_order,
            highest_existing_order=highest_existing_order,
        )
        if next_stage_def is None:
            return None
        assignment = self._assignment_resolver.resolve(
            next_stage_def, requester=requester, department_approvers=department_approvers
        )
        return self._to_stage_plan(definition, next_stage_def, assignment)

    def is_final_stage(self, definition: WorkflowDefinition, stage_order: int) -> bool:
        """Return whether a given stage order is the definition's final stage.

        Args:
            definition: The workflow definition.
            stage_order: The stage order to check.

        Returns:
            ``True`` if ``stage_order`` is the definition's last stage.
        """
        return self._stage_generator.is_final_stage(definition, stage_order)

    def _to_stage_plan(
        self,
        definition: WorkflowDefinition,
        stage_def: StageDefinition,
        assignment: AssignmentResult,
    ) -> StagePlan:
        """Combine a stage's structural definition and resolved assignment
        into a ``StagePlan``.

        Args:
            definition: The workflow definition the stage belongs to.
            stage_def: The stage's structural configuration.
            assignment: The resolved assignment for the stage.

        Returns:
            The combined ``StagePlan``.
        """
        return StagePlan(
            stage_order=stage_def.order,
            stage_name=stage_def.name,
            assigned_to=assignment.assigned_to,
            assigned_role=assignment.assigned_role,
            used_fallback=assignment.used_fallback,
            fallback_reason=assignment.fallback_reason,
            is_final_stage=self._stage_generator.is_final_stage(definition, stage_def.order),
        )

    # ------------------------------------------------------------------
    # Escalation (WEDD Section 8)
    # ------------------------------------------------------------------

    def is_stage_escalation_eligible(
        self, stage_created_at, escalation_hours: float, *, now=None
    ) -> bool:
        """Return whether a pending stage is currently eligible for escalation.

        Args:
            stage_created_at: The stage's ``created_at`` timestamp.
            escalation_hours: The definition's configured escalation
                duration for this stage, in hours.
            now: The point in time to evaluate against. Defaults to the
                current instant.

        Returns:
            ``True`` if the stage's escalation threshold has passed.
        """
        return self._escalation_manager.is_eligible(stage_created_at, escalation_hours, now=now)

    def plan_stage_escalation(
        self,
        *,
        current_assigned_to: UUID | None,
        current_assigned_role: UserRole | None,
    ) -> EscalationPlan:
        """Plan an escalation reassignment for an eligible stage.

        Args:
            current_assigned_to: The stage's current specific assignee,
                if any.
            current_assigned_role: The stage's current eligible role, if
                any.

        Returns:
            An ``EscalationPlan`` describing the reassignment.
        """
        return self._escalation_manager.plan_escalation(
            current_assigned_to=current_assigned_to,
            current_assigned_role=current_assigned_role,
        )

    # ------------------------------------------------------------------
    # Versioning (WEDD Section 9)
    # ------------------------------------------------------------------

    def next_definition_version(self, existing_versions: Sequence[int]) -> int:
        """Compute the next version number for a request type.

        Args:
            existing_versions: Every version number already used for
                this request type.

        Returns:
            The next version number to use.
        """
        return self._version_manager.next_version_number(existing_versions)

    def validate_definition_edit(self, definition: WorkflowDefinition) -> None:
        """Enforce that a definition may be edited in place.

        Args:
            definition: The definition an edit is being attempted
                against.

        Raises:
            DefinitionEditNotAllowedError: If ``definition`` is already
                active.
        """
        self._version_manager.validate_edit_allowed(definition)

    def validate_definition_activation(
        self,
        candidate: WorkflowDefinition,
        *,
        currently_active: WorkflowDefinition | None,
    ) -> None:
        """Enforce that an activation attempt is legal before it proceeds.

        Args:
            candidate: The definition being activated.
            currently_active: The definition currently active for this
                request type, if any.

        Raises:
            DefinitionAlreadyActiveError: If ``candidate`` is already
                active.
            MismatchedRequestTypeError: If ``currently_active``'s request
                type does not match ``candidate``'s.
        """
        self._version_manager.validate_activation(candidate, currently_active=currently_active)

    def validate_definition_assignees(
        self, document: WorkflowDefinitionDocument, known_profile_ids
    ) -> None:
        """Validate every ``specific_user`` stage's assignee across a definition.

        Args:
            document: The workflow definition document to validate.
            known_profile_ids: The set of profile ids known to exist.

        Raises:
            UnknownAssigneeError: If any ``specific_user`` stage's
                assignee is unknown.
        """
        validate_definition_assignees(document, known_profile_ids)

    # ------------------------------------------------------------------
    # State transitions (WEDD Section 10)
    # ------------------------------------------------------------------

    def validate_request_status_transition(
        self, current: RequestStatus, target: RequestStatus
    ) -> None:
        """Enforce that a request status transition is documented as legal.

        Args:
            current: The request's current status.
            target: The status being transitioned to.

        Raises:
            InvalidStateTransitionError: If the transition is not legal.
        """
        validate_request_transition(current, target)

    def validate_stage_status_transition(self, current: StageStatus, target: StageStatus) -> None:
        """Enforce that a workflow-stage status transition is documented as legal.

        Args:
            current: The stage's current status.
            target: The status being transitioned to.

        Raises:
            InvalidStateTransitionError: If the transition is not legal.
        """
        validate_stage_transition(current, target)

    def is_request_terminal(self, status: RequestStatus) -> bool:
        """Return whether a request status is terminal.

        Args:
            status: The status to check.

        Returns:
            ``True`` if ``status`` has no further legal transitions.
        """
        return is_terminal_request_status(status)

    def is_stage_terminal(self, status: StageStatus) -> bool:
        """Return whether a workflow-stage status is terminal.

        Args:
            status: The status to check.

        Returns:
            ``True`` if ``status`` has no further legal transitions.
        """
        return is_terminal_stage_status(status)