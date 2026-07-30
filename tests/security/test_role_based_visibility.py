"""Security tests: RBAC-enforced visibility and access control.

These tests focus specifically on *who may see or act on what*, distinct
from the functional lifecycle covered in ``tests/unit`` and
``tests/acceptance`` — an employee's request must be invisible to other
employees, only approvers/admins may act on stages, and only admins may
manage workflow definitions or moderate comments.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.enums import UserRole
from app.services.exceptions import NotFoundError, PermissionDeniedError
from tests.fixtures.factories import specific_user_stage

pytestmark = pytest.mark.security


def test_an_employee_cannot_view_another_employees_request(
    env, employee, approver, make_user, make_definition
):
    _, employee_identity = employee
    approver_profile, _ = approver
    make_definition(
        request_type="expense_reimbursement",
        stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
    )
    request = env.request_service.create_request(
        employee_identity, request_type="expense_reimbursement", title="Confidential request"
    )
    _, outsider_identity = make_user(role=UserRole.EMPLOYEE, full_name="Outsider")

    # Per API-ADD Section 11.2, an out-of-scope resource must be reported
    # as not-found, never as a permission failure, so that an
    # unauthorized caller cannot even confirm the resource exists.
    with pytest.raises(NotFoundError):
        env.request_service.get_request(outsider_identity, request.id)


def test_an_unassigned_approver_cannot_view_a_request_they_are_not_assigned_to(
    env, employee, approver, second_approver, make_definition
):
    _, employee_identity = employee
    approver_a_profile, _ = approver
    _, approver_b_identity = second_approver
    make_definition(
        request_type="expense_reimbursement",
        stages=[specific_user_stage(1, "Manager Review", user_id=approver_a_profile.id)],
    )
    request = env.request_service.create_request(
        employee_identity, request_type="expense_reimbursement", title="Team lunch"
    )

    with pytest.raises(NotFoundError):
        env.request_service.get_request(approver_b_identity, request.id)


def test_employees_cannot_view_the_pending_approvals_queue(env, employee):
    _, employee_identity = employee

    with pytest.raises(PermissionDeniedError):
        env.approval_service.list_pending_approvals(employee_identity)


def test_only_administrators_may_create_workflow_definitions(env, employee, approver):
    _, employee_identity = employee
    _, approver_identity = approver

    for identity in (employee_identity, approver_identity):
        with pytest.raises(PermissionDeniedError):
            env.workflow_definition_service.create_definition(
                identity,
                request_type="expense_reimbursement",
                definition={"stages": [specific_user_stage(1, "Review", user_id=uuid4())]},
            )


def test_only_administrators_may_moderate_comments(env, employee, approver, make_definition):
    _, employee_identity = employee
    approver_profile, approver_identity = approver
    make_definition(
        request_type="expense_reimbursement",
        stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
    )
    request = env.request_service.create_request(
        employee_identity, request_type="expense_reimbursement", title="Team lunch"
    )
    comment = env.comment_service.add_comment(employee_identity, request.id, body="A comment.")

    for identity in (employee_identity, approver_identity):
        with pytest.raises(PermissionDeniedError):
            env.comment_service.remove_comment(identity, comment.id)


def test_only_the_resolved_assignee_or_role_eligible_approver_may_decide_a_stage(
    env, employee, approver, second_approver, make_definition
):
    _, employee_identity = employee
    approver_a_profile, _ = approver
    _, approver_b_identity = second_approver
    make_definition(
        request_type="expense_reimbursement",
        stages=[specific_user_stage(1, "Manager Review", user_id=approver_a_profile.id)],
    )
    request = env.request_service.create_request(
        employee_identity, request_type="expense_reimbursement", title="Team lunch"
    )
    stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

    with pytest.raises(PermissionDeniedError):
        env.approval_service.approve_stage(approver_b_identity, stage.id)
