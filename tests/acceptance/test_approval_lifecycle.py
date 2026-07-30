"""End-to-end acceptance test for the complete approval workflow lifecycle.

Exercises, against the real (unmodified) service and Workflow Engine
classes wired to isolated in-memory fakes: user creation, workflow
definition creation, request submission, first-stage approval,
second-stage approval, and final completion — verifying the request
record, workflow stages, audit log, and notifications at every step.
"""

from __future__ import annotations

import pytest

from app.models.enums import RequestStatus, StageStatus
from tests.fixtures.factories import specific_user_stage

pytestmark = pytest.mark.acceptance


def test_full_two_stage_approval_lifecycle(
    env, employee, approver, second_approver, make_definition
):
    # 1. Users: an employee (requester), and two approvers.
    employee_profile, employee_identity = employee
    approver_a_profile, approver_a_identity = approver
    approver_b_profile, approver_b_identity = second_approver

    # 2. Workflow definition: a two-stage expense reimbursement process.
    make_definition(
        request_type="expense_reimbursement",
        stages=[
            specific_user_stage(1, "Manager Review", user_id=approver_a_profile.id),
            specific_user_stage(2, "Finance Review", user_id=approver_b_profile.id),
        ],
    )

    # 3. Submit the request.
    request = env.request_service.create_request(
        employee_identity,
        request_type="expense_reimbursement",
        title="Client dinner reimbursement",
        description="Dinner with prospective client, receipts attached.",
    )

    # 4. Verify: request record, first workflow stage, audit log, notification.
    assert request.status is RequestStatus.PENDING
    assert request.requester_id == employee_profile.id
    assert request.current_stage_id is not None

    stages_after_submission = env.workflow_stage_repo.list_for_request(request.id).items
    assert len(stages_after_submission) == 1
    first_stage = stages_after_submission[0]
    assert first_stage.stage_order == 1
    assert first_stage.status is StageStatus.PENDING
    assert first_stage.assigned_to == approver_a_profile.id

    audit_after_submission = env.audit_repo.list_for_request(request.id).items
    assert [a.action for a in audit_after_submission] == ["REQUEST_CREATED"]

    notifications_to_approver_a = env.notification_repo.list_for_recipient(
        approver_a_profile.id
    ).items
    assert len(notifications_to_approver_a) == 1
    assert notifications_to_approver_a[0].notification_type.value == "assignment"
    assert notifications_to_approver_a[0].request_id == request.id

    # 5. Approve the first stage.
    outcome_1 = env.approval_service.approve_stage(
        approver_a_identity, first_stage.id, decision_note="Looks correct, approving."
    )

    # 6. Verify: stage status, next stage creation, request status, audit, notifications.
    assert outcome_1.stage.status is StageStatus.APPROVED
    assert outcome_1.request_status is RequestStatus.IN_REVIEW
    assert outcome_1.current_stage_id is not None

    stages_after_first_decision = env.workflow_stage_repo.list_for_request(request.id).items
    assert len(stages_after_first_decision) == 2
    second_stage = next(s for s in stages_after_first_decision if s.stage_order == 2)
    assert second_stage.status is StageStatus.PENDING
    assert second_stage.assigned_to == approver_b_profile.id

    request_after_first_decision = env.request_service.get_request(employee_identity, request.id)
    assert request_after_first_decision.status is RequestStatus.IN_REVIEW
    assert request_after_first_decision.current_stage_id == second_stage.id

    audit_after_first_decision = env.audit_repo.list_for_request(request.id).items
    assert [a.action for a in audit_after_first_decision] == ["REQUEST_CREATED", "STAGE_APPROVED"]

    notifications_to_approver_b = env.notification_repo.list_for_recipient(
        approver_b_profile.id
    ).items
    assert len(notifications_to_approver_b) == 1
    assert notifications_to_approver_b[0].notification_type.value == "assignment"

    # 7. Complete the workflow: approve the second (final) stage.
    outcome_2 = env.approval_service.approve_stage(
        approver_b_identity, second_stage.id, decision_note="Finance sign-off granted."
    )

    # 8. Verify final request status, terminal stage, audit trail, and
    #    the completion notification sent back to the requester.
    assert outcome_2.request_status is RequestStatus.COMPLETED
    assert outcome_2.current_stage_id is None

    final_request = env.request_service.get_request(employee_identity, request.id)
    assert final_request.status is RequestStatus.COMPLETED
    assert final_request.current_stage_id is None
    assert final_request.completed_at is not None

    final_audit = env.audit_repo.list_for_request(request.id).items
    assert [a.action for a in final_audit] == [
        "REQUEST_CREATED",
        "STAGE_APPROVED",
        "STAGE_APPROVED",
    ]

    completion_notifications = env.notification_repo.list_for_recipient(employee_profile.id).items
    assert any(n.notification_type.value == "completion" for n in completion_notifications)
