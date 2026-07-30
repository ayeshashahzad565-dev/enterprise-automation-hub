"""Unit tests for the pure, I/O-free Workflow Engine (``app.workflow``).

Per WEDD Section 2.4-2.5 and this package's own docstrings, every
collaborator the engine composes is a pure function of its arguments —
these tests construct plain domain-model values directly and never touch
a repository, a service, or the fake in-memory database used elsewhere in
this suite.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.models import Profile, WorkflowDefinition, WorkflowDefinitionDocument
from app.models.enums import RequestStatus, StageStatus, UserRole
from app.utils.datetime_utils import utc_now
from app.workflow.engine import WorkflowEngine
from app.workflow.exceptions import (
    DefinitionAlreadyActiveError,
    DefinitionEditNotAllowedError,
    InvalidStateTransitionError,
    MultipleActiveDefinitionsError,
    NoActiveDefinitionError,
    NonSequentialStageOrderError,
)
from tests.fixtures.factories import (
    department_queue_stage,
    requester_manager_stage,
    specific_user_stage,
)

pytestmark = pytest.mark.unit


def _definition(
    *,
    request_type: str = "expense_reimbursement",
    stages: list[dict[str, object]],
    is_active: bool = True,
) -> WorkflowDefinition:
    now = utc_now()
    return WorkflowDefinition(
        id=uuid4(),
        request_type=request_type,
        version=1,
        definition=WorkflowDefinitionDocument.model_validate({"stages": stages}),
        is_active=is_active,
        created_by=uuid4(),
        row_version=1,
        created_at=now,
    )


def _profile(*, department: str | None = None, role: UserRole = UserRole.EMPLOYEE) -> Profile:
    now = utc_now()
    return Profile(
        id=uuid4(),
        full_name="Test User",
        role=role,
        department=department,
        company_id=uuid4(),
        version=1,
        created_at=now,
        updated_at=now,
    )


class TestDefinitionResolution:
    def test_resolves_the_single_active_candidate(self) -> None:
        engine = WorkflowEngine()
        active = _definition(stages=[specific_user_stage(1, "Manager Review", user_id=uuid4())])
        inactive = _definition(
            stages=[specific_user_stage(1, "Manager Review", user_id=uuid4())], is_active=False
        )

        resolved = engine.resolve_definition("expense_reimbursement", [inactive, active])

        assert resolved.id == active.id

    def test_raises_when_no_active_definition_exists(self) -> None:
        engine = WorkflowEngine()
        inactive = _definition(
            stages=[specific_user_stage(1, "Review", user_id=uuid4())], is_active=False
        )

        with pytest.raises(NoActiveDefinitionError):
            engine.resolve_definition("expense_reimbursement", [inactive])

    def test_raises_when_multiple_active_definitions_exist(self) -> None:
        engine = WorkflowEngine()
        first = _definition(stages=[specific_user_stage(1, "Review", user_id=uuid4())])
        second = _definition(stages=[specific_user_stage(1, "Review", user_id=uuid4())])

        with pytest.raises(MultipleActiveDefinitionsError):
            engine.resolve_definition("expense_reimbursement", [first, second])


class TestStagePlanning:
    def test_plan_first_stage_specific_user(self) -> None:
        engine = WorkflowEngine()
        approver_id = uuid4()
        definition = _definition(
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_id)]
        )
        requester = _profile()

        plan = engine.plan_first_stage(definition, requester=requester)

        assert plan.assigned_to == approver_id
        assert plan.assigned_role is None
        assert plan.is_final_stage is True
        assert plan.used_fallback is False

    def test_plan_first_stage_department_queue(self) -> None:
        engine = WorkflowEngine()
        definition = _definition(
            stages=[
                department_queue_stage(
                    1, "Finance Review", role=UserRole.APPROVER, department="finance"
                )
            ]
        )
        requester = _profile()

        plan = engine.plan_first_stage(definition, requester=requester)

        assert plan.assigned_to is None
        assert plan.assigned_role is UserRole.APPROVER

    def test_plan_first_stage_requester_manager_resolves_department_approver(self) -> None:
        engine = WorkflowEngine()
        definition = _definition(stages=[requester_manager_stage(1, "Manager Review")])
        requester = _profile(department="sales")
        approver_a = _profile(department="sales", role=UserRole.APPROVER)

        plan = engine.plan_first_stage(
            definition, requester=requester, department_approvers=[approver_a]
        )

        assert plan.assigned_to == approver_a.id
        assert plan.used_fallback is False

    def test_plan_first_stage_requester_manager_falls_back_when_no_department_approver(
        self,
    ) -> None:
        engine = WorkflowEngine()
        definition = _definition(stages=[requester_manager_stage(1, "Manager Review")])
        requester = _profile(department="sales")

        plan = engine.plan_first_stage(definition, requester=requester, department_approvers=[])

        assert plan.assigned_to is None
        assert plan.assigned_role is UserRole.ADMIN
        assert plan.used_fallback is True
        assert plan.fallback_reason is not None

    def test_plan_next_stage_advances_to_the_second_stage(self) -> None:
        engine = WorkflowEngine()
        second_approver = uuid4()
        definition = _definition(
            stages=[
                specific_user_stage(1, "Manager Review", user_id=uuid4()),
                specific_user_stage(2, "Finance Review", user_id=second_approver),
            ]
        )
        requester = _profile()

        plan = engine.plan_next_stage(
            definition, current_order=1, highest_existing_order=1, requester=requester
        )

        assert plan is not None
        assert plan.stage_order == 2
        assert plan.assigned_to == second_approver
        assert plan.is_final_stage is True

    def test_plan_next_stage_returns_none_at_the_final_stage(self) -> None:
        engine = WorkflowEngine()
        definition = _definition(stages=[specific_user_stage(1, "Manager Review", user_id=uuid4())])
        requester = _profile()

        plan = engine.plan_next_stage(
            definition, current_order=1, highest_existing_order=1, requester=requester
        )

        assert plan is None

    def test_plan_next_stage_rejects_a_non_sequential_order(self) -> None:
        engine = WorkflowEngine()
        definition = _definition(
            stages=[
                specific_user_stage(1, "Manager Review", user_id=uuid4()),
                specific_user_stage(2, "Finance Review", user_id=uuid4()),
            ]
        )
        requester = _profile()

        with pytest.raises(NonSequentialStageOrderError):
            engine.plan_next_stage(
                definition, current_order=1, highest_existing_order=2, requester=requester
            )


class TestEscalation:
    def test_stage_is_not_eligible_before_the_threshold(self) -> None:
        engine = WorkflowEngine()
        created_at = utc_now()

        eligible = engine.is_stage_escalation_eligible(
            created_at, escalation_hours=24, now=created_at + timedelta(hours=1)
        )

        assert eligible is False

    def test_stage_becomes_eligible_after_a_shortened_timeout(self) -> None:
        engine = WorkflowEngine()
        created_at = utc_now()

        # Simulate a "shortened timeout" deterministically via the `now`
        # argument rather than sleeping in real time.
        eligible = engine.is_stage_escalation_eligible(
            created_at, escalation_hours=0.01, now=created_at + timedelta(hours=1)
        )

        assert eligible is True

    def test_plan_stage_escalation_routes_to_the_fallback_role(self) -> None:
        engine = WorkflowEngine()
        previous_assignee = uuid4()

        plan = engine.plan_stage_escalation(
            current_assigned_to=previous_assignee, current_assigned_role=None
        )

        assert plan.previous_assigned_to == previous_assignee
        assert plan.new_assigned_to is None
        assert plan.new_assigned_role is UserRole.ADMIN


class TestStateTransitions:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (RequestStatus.PENDING, RequestStatus.IN_REVIEW),
            (RequestStatus.PENDING, RequestStatus.COMPLETED),
            (RequestStatus.PENDING, RequestStatus.REJECTED),
            (RequestStatus.IN_REVIEW, RequestStatus.COMPLETED),
        ],
    )
    def test_valid_request_transitions_are_accepted(
        self, current: RequestStatus, target: RequestStatus
    ) -> None:
        WorkflowEngine().validate_request_status_transition(current, target)

    def test_invalid_request_transition_is_rejected(self) -> None:
        with pytest.raises(InvalidStateTransitionError):
            WorkflowEngine().validate_request_status_transition(
                RequestStatus.COMPLETED, RequestStatus.PENDING
            )

    def test_invalid_stage_transition_is_rejected(self) -> None:
        with pytest.raises(InvalidStateTransitionError):
            WorkflowEngine().validate_stage_status_transition(
                StageStatus.APPROVED, StageStatus.PENDING
            )

    def test_terminal_statuses(self) -> None:
        engine = WorkflowEngine()
        assert engine.is_request_terminal(RequestStatus.COMPLETED) is True
        assert engine.is_request_terminal(RequestStatus.PENDING) is False
        assert engine.is_stage_terminal(StageStatus.APPROVED) is True
        assert engine.is_stage_terminal(StageStatus.PENDING) is False


class TestVersioning:
    def test_next_definition_version_increments_from_the_highest(self) -> None:
        engine = WorkflowEngine()
        assert engine.next_definition_version([]) == 1
        assert engine.next_definition_version([1, 2, 3]) == 4

    def test_validate_definition_edit_rejects_an_active_definition(self) -> None:
        engine = WorkflowEngine()
        active = _definition(
            stages=[specific_user_stage(1, "Review", user_id=uuid4())], is_active=True
        )

        with pytest.raises(DefinitionEditNotAllowedError):
            engine.validate_definition_edit(active)

    def test_validate_definition_activation_rejects_an_already_active_candidate(self) -> None:
        engine = WorkflowEngine()
        active = _definition(
            stages=[specific_user_stage(1, "Review", user_id=uuid4())], is_active=True
        )

        with pytest.raises(DefinitionAlreadyActiveError):
            engine.validate_definition_activation(active, currently_active=None)
