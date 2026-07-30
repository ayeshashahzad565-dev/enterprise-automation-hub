"""Unit tests for ``app.services.comment_service.CommentService``."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.enums import UserRole
from app.services.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from tests.fixtures.factories import specific_user_stage

pytestmark = pytest.mark.unit


def _submit(env, employee_identity):
    return env.request_service.create_request(
        employee_identity, request_type="expense_reimbursement", title="Team lunch"
    )


class TestAddAndListComments:
    def test_requester_can_add_and_list_a_comment(self, env, employee, approver, make_definition):
        employee_profile, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)

        created = env.comment_service.add_comment(
            employee_identity, request.id, body="Please expedite."
        )

        assert created.author_id == employee_profile.id
        assert created.body == "Please expedite."

        thread = env.comment_service.list_comments(employee_identity, request.id).items
        assert [c.id for c in thread] == [created.id]

        audit_actions = [a.action for a in env.audit_repo.list_for_request(request.id).items]
        assert "COMMENT_CREATED" in audit_actions

    def test_assigned_approver_can_comment_and_reply(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        original = env.comment_service.add_comment(
            employee_identity, request.id, body="Please expedite."
        )

        reply = env.comment_service.add_comment(
            approver_identity, request.id, body="Approving now.", parent_comment_id=original.id
        )

        assert reply.parent_comment_id == original.id

    def test_reply_to_a_nonexistent_parent_is_rejected(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)

        with pytest.raises(ValidationError):
            env.comment_service.add_comment(
                employee_identity, request.id, body="Reply to nothing.", parent_comment_id=uuid4()
            )

    def test_unrelated_employee_cannot_comment(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Outsider")

        with pytest.raises(NotFoundError):
            env.comment_service.add_comment(other_identity, request.id, body="Snooping.")

    def test_invalid_request_id_raises_not_found(self, env, employee):
        _, employee_identity = employee

        with pytest.raises(NotFoundError):
            env.comment_service.add_comment(employee_identity, uuid4(), body="Anything")


class TestRemoveComment:
    def test_admin_can_moderate_a_comment(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        comment = env.comment_service.add_comment(
            employee_identity, request.id, body="Inappropriate content."
        )
        _, admin_identity = make_user(role=UserRole.ADMIN)

        removed = env.comment_service.remove_comment(admin_identity, comment.id)

        assert removed.deleted_at is not None
        audit_actions = [a.action for a in env.audit_repo.list_for_request(request.id).items]
        assert "COMMENT_REMOVED" in audit_actions

    def test_non_admin_cannot_moderate_a_comment(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        comment = env.comment_service.add_comment(
            employee_identity, request.id, body="A normal comment."
        )

        with pytest.raises(PermissionDeniedError):
            env.comment_service.remove_comment(approver_identity, comment.id)


class TestCrossTenantIsolation:
    """Regression coverage for the cross-tenant IDOR fixed in
    ``CommentService._authorize_view``/``remove_comment``: an admin in
    Company B must never be able to read, post to, or moderate a comment
    thread belonging to a Company A request, even with a fully valid
    request/comment id. Every case uses an *admin* identity deliberately —
    ``can_view_request``/``authorize_comment_moderation`` grant admins
    unconditional access within their own company, which is exactly the
    class of check that silently had no company comparison before this fix.
    """

    def _other_company_admin(self, make_user):
        return make_user(role=UserRole.ADMIN, full_name="Other Co Admin", company_id=uuid4())

    def test_admin_of_another_company_cannot_add_a_comment(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        _, other_company_admin = self._other_company_admin(make_user)

        with pytest.raises(NotFoundError):
            env.comment_service.add_comment(other_company_admin, request.id, body="Snooping.")

    def test_admin_of_another_company_cannot_list_comments(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        env.comment_service.add_comment(employee_identity, request.id, body="Internal note.")
        _, other_company_admin = self._other_company_admin(make_user)

        with pytest.raises(NotFoundError):
            env.comment_service.list_comments(other_company_admin, request.id)

    def test_admin_of_another_company_cannot_moderate_a_comment(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        comment = env.comment_service.add_comment(
            employee_identity, request.id, body="A normal comment."
        )
        _, other_company_admin = self._other_company_admin(make_user)

        with pytest.raises(NotFoundError):
            env.comment_service.remove_comment(other_company_admin, comment.id)
        # Not just denied — untouched: the comment is still there, unremoved.
        assert env.comment_repo.get_by_id(comment.id).deleted_at is None
