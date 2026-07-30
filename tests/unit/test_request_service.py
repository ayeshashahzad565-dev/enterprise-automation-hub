"""Unit tests for ``app.services.request_service.RequestService``."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.enums import RequestStatus, UserRole
from app.services.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from tests.fixtures.factories import department_queue_stage, specific_user_stage

pytestmark = pytest.mark.unit


class TestCreateRequest:
    def test_creates_the_request_its_first_stage_and_audit_entry(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )

        request = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )

        assert request.status is RequestStatus.PENDING
        assert request.current_stage_id is not None

        stages = env.workflow_stage_repo.list_for_request(request.id).items
        assert len(stages) == 1
        assert stages[0].assigned_to == approver_profile.id

        audit_entries = env.audit_repo.list_for_request(request.id).items
        assert [a.action for a in audit_entries] == ["REQUEST_CREATED"]

        notifications = env.notification_repo.list_for_recipient(approver_profile.id).items
        assert len(notifications) == 1
        assert notifications[0].notification_type.value == "assignment"

    def test_raises_validation_error_when_no_active_definition_exists(self, env, employee):
        _, employee_identity = employee

        with pytest.raises(ValidationError):
            env.request_service.create_request(
                employee_identity, request_type="nonexistent_type", title="Anything"
            )

    def test_department_queue_first_stage_sends_no_specific_assignment_notification(
        self, env, employee, make_definition
    ):
        _, employee_identity = employee
        make_definition(
            request_type="it_access",
            stages=[
                department_queue_stage(1, "IT Review", role=UserRole.APPROVER, department="it")
            ],
        )

        request = env.request_service.create_request(
            employee_identity, request_type="it_access", title="Need VPN access"
        )

        stages = env.workflow_stage_repo.list_for_request(request.id).items
        assert stages[0].assigned_to is None
        assert stages[0].assigned_role is UserRole.APPROVER
        # No specific recipient was resolved, so no assignment notification
        # should have been created for anyone.
        assert env.notification_repo._table.values() == []


class TestGetRequest:
    def test_requester_can_view_their_own_request(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )

        fetched = env.request_service.get_request(employee_identity, created.id)

        assert fetched.id == created.id

    def test_assigned_approver_can_view_the_request(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )

        fetched = env.request_service.get_request(approver_identity, created.id)

        assert fetched.id == created.id

    def test_unrelated_employee_cannot_view_the_request(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )
        _, other_employee_identity = make_user(role=UserRole.EMPLOYEE, full_name="Other Employee")

        with pytest.raises(NotFoundError):
            env.request_service.get_request(other_employee_identity, created.id)

    def test_invalid_request_id_raises_not_found(self, env, employee):
        _, employee_identity = employee

        with pytest.raises(NotFoundError):
            env.request_service.get_request(employee_identity, uuid4())


class TestListRequests:
    def test_employee_only_sees_their_own_requests(
        self, env, employee, make_user, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Mine"
        )
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Other Employee")
        env.request_service.create_request(
            other_identity, request_type="expense_reimbursement", title="Not mine"
        )

        result = env.request_service.list_requests(employee_identity)

        assert [r.title for r in result.items] == ["Mine"]

    def test_approver_only_sees_requests_with_a_pending_stage_assigned_to_them(
        self, env, employee, approver, second_approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        second_approver_profile, _ = second_approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        make_definition(
            request_type="equipment_request",
            stages=[specific_user_stage(1, "Manager Review", user_id=second_approver_profile.id)],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Assigned to Alan"
        )
        env.request_service.create_request(
            employee_identity, request_type="equipment_request", title="Assigned to Amy"
        )

        result = env.request_service.list_requests(approver_identity)

        assert [r.title for r in result.items] == ["Assigned to Alan"]

    def test_approver_with_no_pending_assignments_sees_an_empty_page(self, env, approver):
        _, approver_identity = approver

        result = env.request_service.list_requests(approver_identity)

        assert result.items == []
        assert result.total_records == 0

    def test_admin_sees_every_request_regardless_of_assignment(
        self, env, employee, approver, admin, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Visible to admin"
        )

        result = env.request_service.list_requests(admin_identity)

        assert [r.title for r in result.items] == ["Visible to admin"]


class TestSearchRequests:
    def test_approver_search_only_matches_requests_assigned_to_them(
        self, env, employee, approver, second_approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        second_approver_profile, _ = second_approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        make_definition(
            request_type="equipment_request",
            stages=[specific_user_stage(1, "Manager Review", user_id=second_approver_profile.id)],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Laptop for Alan"
        )
        env.request_service.create_request(
            employee_identity, request_type="equipment_request", title="Laptop for Amy"
        )

        result = env.request_service.search_requests(approver_identity, "Laptop")

        assert [r.title for r in result.items] == ["Laptop for Alan"]

    def test_approver_with_no_pending_assignments_gets_no_search_results(self, env, approver):
        _, approver_identity = approver

        result = env.request_service.search_requests(approver_identity, "anything")

        assert result.items == []
        assert result.total_records == 0


class TestUpdateAndWithdrawRequest:
    def test_requester_can_edit_while_pending(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Original title"
        )

        updated = env.request_service.update_request(
            employee_identity, created.id, title="Updated title", expected_version=created.version
        )

        assert updated.title == "Updated title"

    def test_non_requester_cannot_edit(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Original title"
        )

        with pytest.raises(PermissionDeniedError):
            env.request_service.update_request(
                approver_identity, created.id, title="Hijacked", expected_version=created.version
            )

    def test_requester_can_withdraw_while_pending(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )

        withdrawn = env.request_service.withdraw_request(
            employee_identity, created.id, expected_version=created.version
        )

        assert withdrawn.deleted_at is not None


class TestGetWorkflowProgress:
    def test_reflects_a_single_stage_workflow_awaiting_its_only_decision(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )

        progress = env.request_service.get_workflow_progress(employee_identity, request.id)

        assert progress.total_stages == 1
        assert progress.current_stage_order == 1
        assert progress.upcoming_stages == []
        assert len(progress.stages) == 1
        assert progress.stages[0].assigned_to_name == approver_profile.full_name
        assert progress.stages[0].decided_at is None
        assert progress.stages[0].is_escalated is False

    def test_a_multi_stage_workflow_shows_upcoming_stages_before_they_materialize(
        self, env, employee, approver, second_approver, make_definition
    ):
        _, employee_identity = employee
        approver_a_profile, _ = approver
        approver_b_profile, _ = second_approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[
                specific_user_stage(1, "Manager Review", user_id=approver_a_profile.id),
                specific_user_stage(2, "Finance Review", user_id=approver_b_profile.id),
            ],
        )
        request = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )

        progress = env.request_service.get_workflow_progress(employee_identity, request.id)

        assert progress.total_stages == 2
        assert progress.current_stage_order == 1
        assert len(progress.stages) == 1
        assert [u.stage_order for u in progress.upcoming_stages] == [2]
        assert progress.upcoming_stages[0].stage_name == "Finance Review"

    def test_advancing_the_workflow_materializes_the_next_stage_and_records_the_decider(
        self, env, employee, approver, second_approver, make_definition
    ):
        _, employee_identity = employee
        approver_a_profile, approver_a_identity = approver
        approver_b_profile, _ = second_approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[
                specific_user_stage(1, "Manager Review", user_id=approver_a_profile.id),
                specific_user_stage(2, "Finance Review", user_id=approver_b_profile.id),
            ],
        )
        request = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )
        first_stage = env.workflow_stage_repo.list_for_request(request.id).items[0]
        env.approval_service.approve_stage(
            approver_a_identity, first_stage.id, decision_note="Looks good."
        )

        progress = env.request_service.get_workflow_progress(employee_identity, request.id)

        assert progress.current_stage_order == 2
        assert progress.upcoming_stages == []
        assert len(progress.stages) == 2
        decided = next(s for s in progress.stages if s.stage_order == 1)
        assert decided.decided_by_name == approver_a_profile.full_name
        assert decided.decision_note == "Looks good."

    def test_an_escalated_stage_is_flagged_regardless_of_its_status(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]
        env.approval_service.escalate_stage(stage.id)

        progress = env.request_service.get_workflow_progress(employee_identity, request.id)

        assert progress.stages[0].is_escalated is True
        assert progress.stages[0].status.value == "pending"

    def test_an_unrelated_employee_cannot_view_workflow_progress(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Outsider")

        with pytest.raises(NotFoundError):
            env.request_service.get_workflow_progress(other_identity, request.id)

    def test_invalid_request_id_raises_not_found(self, env, employee):
        _, employee_identity = employee

        with pytest.raises(NotFoundError):
            env.request_service.get_workflow_progress(employee_identity, uuid4())


class TestGetAuditTrail:
    def test_returns_entries_chronologically_with_resolved_actor_names(
        self, env, employee, approver, make_definition
    ):
        employee_profile, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]
        env.approval_service.approve_stage(approver_identity, stage.id)

        entries = env.request_service.get_audit_trail(employee_identity, request.id)

        assert [e.action.value for e in entries] == ["REQUEST_CREATED", "STAGE_APPROVED"]
        assert entries[0].actor_name == employee_profile.full_name
        assert entries[1].actor_name == approver_profile.full_name

    def test_an_unrelated_employee_cannot_view_the_audit_trail(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Outsider")

        with pytest.raises(NotFoundError):
            env.request_service.get_audit_trail(other_identity, request.id)
