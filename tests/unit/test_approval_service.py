"""Unit tests for ``app.services.approval_service.ApprovalService``.

Covers the full approve/reject/escalate lifecycle plus the edge cases
explicitly required for this suite: unauthorized approval, duplicate
approval prevention, invalid stage ids, approval after completion,
multi-stage workflows, escalation, and concurrent decision attempts.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.database.exceptions import ConcurrentUpdateError, RepositoryError
from app.models.enums import RequestStatus, StageStatus, UserRole
from app.services.exceptions import (
    EAHError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from tests.fixtures.factories import department_queue_stage, specific_user_stage


def _raise_repository_error(*_args: object, **_kwargs: object) -> None:
    """A drop-in failure for monkeypatching a fake repository method,
    simulating a transient storage failure at exactly one call site."""
    raise RepositoryError("Simulated failure for compensation testing.")

pytestmark = pytest.mark.unit


def _submit(
    env,
    employee_identity,
    *,
    request_type: str = "expense_reimbursement",
    title: str = "Team lunch",
):
    return env.request_service.create_request(
        employee_identity, request_type=request_type, title=title
    )


class TestSingleStageApproval:
    def test_approving_the_only_stage_completes_the_request(
        self, env, employee, approver, make_definition
    ):
        employee_profile, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        outcome = env.approval_service.approve_stage(approver_identity, stage.id)

        assert outcome.request_status is RequestStatus.COMPLETED
        assert outcome.current_stage_id is None
        assert outcome.stage.status is StageStatus.APPROVED

        updated_request = env.request_service.get_request(employee_identity, request.id)
        assert updated_request.status is RequestStatus.COMPLETED
        assert updated_request.completed_at is not None

        audit_actions = [a.action for a in env.audit_repo.list_for_request(request.id).items]
        assert audit_actions == ["REQUEST_CREATED", "STAGE_APPROVED"]

        requester_notifications = env.notification_repo.list_for_recipient(
            employee_profile.id
        ).items
        assert any(n.notification_type.value == "completion" for n in requester_notifications)

    def test_rejecting_the_only_stage_rejects_the_request(
        self, env, employee, approver, make_definition
    ):
        employee_profile, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        outcome = env.approval_service.reject_stage(
            approver_identity, stage.id, decision_note="Not within policy."
        )

        assert outcome.request_status is RequestStatus.REJECTED
        assert outcome.stage.status is StageStatus.REJECTED

        updated_request = env.request_service.get_request(employee_identity, request.id)
        assert updated_request.status is RequestStatus.REJECTED

        requester_notifications = env.notification_repo.list_for_recipient(
            employee_profile.id
        ).items
        assert any(n.notification_type.value == "decision" for n in requester_notifications)

    def test_rejection_requires_a_non_empty_decision_note(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        with pytest.raises(ValidationError):
            env.approval_service.reject_stage(approver_identity, stage.id, decision_note="   ")


class TestMultiStageWorkflow:
    def test_a_three_stage_workflow_advances_through_every_stage_to_completion(
        self, env, employee, approver, second_approver, make_definition, make_user
    ):
        employee_profile, employee_identity = employee
        approver_a_profile, approver_a_identity = approver
        approver_b_profile, approver_b_identity = second_approver
        admin_profile, admin_identity = make_user(role=UserRole.ADMIN, full_name="Third Approver")

        make_definition(
            request_type="expense_reimbursement",
            stages=[
                specific_user_stage(1, "Manager Review", user_id=approver_a_profile.id),
                specific_user_stage(2, "Finance Review", user_id=approver_b_profile.id),
                specific_user_stage(3, "Final Sign-off", user_id=admin_profile.id),
            ],
        )
        request = _submit(env, employee_identity)

        stage_1 = env.workflow_stage_repo.list_for_request(request.id).items[0]
        outcome_1 = env.approval_service.approve_stage(approver_a_identity, stage_1.id)
        assert outcome_1.request_status is RequestStatus.IN_REVIEW
        assert outcome_1.current_stage_id is not None

        all_stages = env.workflow_stage_repo.list_for_request(request.id).items
        assert len(all_stages) == 2
        stage_2 = [s for s in all_stages if s.stage_order == 2][0]
        assert stage_2.assigned_to == approver_b_profile.id

        outcome_2 = env.approval_service.approve_stage(approver_b_identity, stage_2.id)
        assert outcome_2.request_status is RequestStatus.IN_REVIEW

        all_stages = env.workflow_stage_repo.list_for_request(request.id).items
        assert len(all_stages) == 3
        stage_3 = [s for s in all_stages if s.stage_order == 3][0]

        outcome_3 = env.approval_service.approve_stage(admin_identity, stage_3.id)
        assert outcome_3.request_status is RequestStatus.COMPLETED

        final_request = env.request_service.get_request(employee_identity, request.id)
        assert final_request.status is RequestStatus.COMPLETED

        audit_actions = [a.action for a in env.audit_repo.list_for_request(request.id).items]
        assert audit_actions == [
            "REQUEST_CREATED",
            "STAGE_APPROVED",
            "STAGE_APPROVED",
            "STAGE_APPROVED",
        ]

    def test_a_rejection_partway_through_a_multi_stage_workflow_terminates_it(
        self, env, employee, approver, second_approver, make_definition
    ):
        employee_profile, employee_identity = employee
        approver_a_profile, approver_a_identity = approver
        approver_b_profile, _ = second_approver

        make_definition(
            request_type="expense_reimbursement",
            stages=[
                specific_user_stage(1, "Manager Review", user_id=approver_a_profile.id),
                specific_user_stage(2, "Finance Review", user_id=approver_b_profile.id),
            ],
        )
        request = _submit(env, employee_identity)
        stage_1 = env.workflow_stage_repo.list_for_request(request.id).items[0]

        outcome = env.approval_service.reject_stage(
            approver_a_identity, stage_1.id, decision_note="Missing receipts."
        )

        assert outcome.request_status is RequestStatus.REJECTED
        # No second stage should ever be materialized for a rejected workflow.
        assert len(env.workflow_stage_repo.list_for_request(request.id).items) == 1


class TestAuthorizationAndValidation:
    def test_employee_cannot_approve_a_stage(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        with pytest.raises(PermissionDeniedError):
            env.approval_service.approve_stage(employee_identity, stage.id)

    def test_an_approver_not_assigned_or_role_eligible_cannot_approve(
        self, env, employee, approver, second_approver, make_definition
    ):
        _, employee_identity = employee
        approver_a_profile, _ = approver
        _, approver_b_identity = second_approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_a_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        with pytest.raises(PermissionDeniedError):
            env.approval_service.approve_stage(approver_b_identity, stage.id)

    def test_invalid_stage_id_raises_not_found(self, env, approver):
        _, approver_identity = approver

        with pytest.raises(NotFoundError):
            env.approval_service.approve_stage(approver_identity, uuid4())

    def test_a_repeated_approval_by_the_same_actor_replays_the_original_outcome(
        self, env, employee, approver, make_definition
    ):
        """A retry by the *same* actor of their own already-committed
        decision (e.g. their original response was lost to a dropped
        connection) must come back as the same success, not an error —
        otherwise a client cannot safely retry at all. This is the
        idempotent-replay path (``ApprovalService._replay_idempotent_decision``),
        not a second application of the decision: exactly one
        ``STAGE_APPROVED`` audit entry exists, proving no double-write
        occurred."""
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        first = env.approval_service.approve_stage(approver_identity, stage.id)
        second = env.approval_service.approve_stage(approver_identity, stage.id)

        assert second.request_status == first.request_status == RequestStatus.COMPLETED
        assert second.current_stage_id == first.current_stage_id is None
        assert second.stage.status is StageStatus.APPROVED

        audit_actions = [a.action for a in env.audit_repo.list_for_request(request.id).items]
        assert audit_actions.count("STAGE_APPROVED") == 1

    def test_a_different_actor_deciding_an_already_decided_stage_is_still_rejected(
        self, env, employee, approver, second_approver, make_definition
    ):
        """The idempotent-replay path only ever applies to the exact actor
        who made the original decision — a different (even otherwise
        role-eligible) approver retrying it is a genuine conflict, not a
        retry, and must still be rejected exactly as before."""
        _, employee_identity = employee
        _, approver_identity = approver
        _, other_approver_identity = second_approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[
                department_queue_stage(
                    1, "Manager Review", role=UserRole.APPROVER, department="general"
                )
            ],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        env.approval_service.approve_stage(approver_identity, stage.id)

        with pytest.raises(PermissionDeniedError):
            env.approval_service.approve_stage(other_approver_identity, stage.id)

    def test_the_same_actor_rejecting_a_stage_they_already_approved_is_still_rejected(
        self, env, employee, approver, make_definition
    ):
        """Idempotent replay requires the *same target status*, not just
        the same actor — flipping the requested outcome after the fact is
        a genuine conflict (the decision is already terminal), not a
        retry of the same request."""
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        env.approval_service.approve_stage(approver_identity, stage.id)

        with pytest.raises(PermissionDeniedError):
            env.approval_service.reject_stage(
                approver_identity, stage.id, decision_note="Changed my mind."
            )

    def test_approval_after_the_request_has_already_completed_replays_idempotently(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]
        env.approval_service.approve_stage(approver_identity, stage.id)

        final_request = env.request_service.get_request(employee_identity, request.id)
        assert final_request.status is RequestStatus.COMPLETED

        replayed = env.approval_service.approve_stage(
            approver_identity, stage.id, decision_note="Trying again after completion."
        )
        assert replayed.request_status is RequestStatus.COMPLETED

    def test_concurrent_decision_attempts_are_rejected_by_optimistic_locking(
        self, env, employee, approver, make_definition
    ):
        """A raw storage-layer race: two callers both read version 1 of a
        still-pending stage; the first decision succeeds and bumps the
        version, and the second — submitted with the stale version it
        originally observed — is rejected outright, rather than silently
        overwriting the first decision.
        """
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]
        assert stage.version == 1

        env.approval_repo.approve_stage(
            stage.id, expected_version=1, decided_by=approver_profile.id
        )

        with pytest.raises(ConcurrentUpdateError):
            env.approval_repo.approve_stage(
                stage.id, expected_version=1, decided_by=approver_profile.id
            )


class TestEscalation:
    def test_an_overdue_stage_is_reassigned_to_the_admin_fallback_role(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[
                specific_user_stage(
                    1, "Manager Review", user_id=approver_profile.id, escalation_hours=1
                )
            ],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        # Simulate a shortened timeout deterministically via an explicit
        # `now` far past the stage's 1-hour threshold, rather than
        # sleeping in real time.
        eligible = env.workflow_engine.is_stage_escalation_eligible(
            stage.created_at, escalation_hours=1, now=stage.created_at + timedelta(hours=2)
        )
        assert eligible is True

        escalated = env.approval_service.escalate_stage(stage.id)

        assert escalated.assigned_to is None
        assert escalated.assigned_role is UserRole.ADMIN
        assert escalated.status is StageStatus.PENDING

        audit_entries = env.audit_repo.list_for_request(request.id).items
        escalation_entries = [a for a in audit_entries if a.action == "STAGE_ESCALATED"]
        assert len(escalation_entries) == 1
        assert escalation_entries[0].metadata["previous_assigned_to"] == str(approver_profile.id)

    def test_escalated_stage_can_then_be_decided_by_an_administrator(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = make_user(role=UserRole.ADMIN)
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]
        env.approval_service.escalate_stage(stage.id)

        outcome = env.approval_service.approve_stage(admin_identity, stage.id)

        assert outcome.request_status is RequestStatus.COMPLETED


class TestRoleBasedVisibility:
    def test_employee_cannot_view_the_pending_approvals_queue(self, env, employee):
        _, employee_identity = employee

        with pytest.raises(PermissionDeniedError):
            env.approval_service.list_pending_approvals(employee_identity)

    def test_an_approver_only_sees_stages_assigned_to_them_or_their_eligible_role(
        self, env, employee, approver, second_approver, make_definition
    ):
        _, employee_identity = employee
        approver_a_profile, approver_a_identity = approver
        approver_b_profile, approver_b_identity = second_approver

        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_a_profile.id)],
        )
        make_definition(
            request_type="it_access",
            stages=[
                department_queue_stage(1, "IT Review", role=UserRole.APPROVER, department="it")
            ],
        )
        _submit(
            env,
            employee_identity,
            request_type="expense_reimbursement",
            title="Specific-user request",
        )
        _submit(env, employee_identity, request_type="it_access", title="Department-queue request")

        approver_a_queue = env.approval_service.list_pending_approvals(approver_a_identity).items
        approver_b_queue = env.approval_service.list_pending_approvals(approver_b_identity).items

        # A specific_user stage is private to its named assignee: only
        # approver_a (the resolved assignee) sees "Manager Review". A
        # department_queue stage is visible to every approver sharing its
        # eligible role (workflow_stages carries no department column, so
        # role — not department — is the only visibility scope this
        # baseline enforces), so both approvers see "IT Review".
        assert {s.stage_name for s in approver_a_queue} == {"Manager Review", "IT Review"}
        assert {s.stage_name for s in approver_b_queue} == {"IT Review"}


class TestCompensationOnPartialFailure:
    """Every scenario here injects a failure at exactly one write step
    (via monkeypatching a fake repository method) partway through an
    otherwise-valid decision, then asserts three things together: the
    exception the caller sees, that the stage is back to genuine
    ``pending`` with every decision field cleared, and that the request
    (and any newly created stage) is back to its exact pre-decision state
    — not just that "an exception was raised."
    """

    def test_audit_failure_after_a_completing_approval_rolls_back_the_stage_and_request(
        self, env, employee, approver, make_definition, monkeypatch
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage_before = env.workflow_stage_repo.list_for_request(request.id).items[0]
        request_before = env.request_repo.get_by_id(request.id)

        monkeypatch.setattr(env.audit_repo, "record_event", _raise_repository_error)

        with pytest.raises(EAHError):
            env.approval_service.approve_stage(approver_identity, stage_before.id)

        reverted_stage = env.workflow_stage_repo.get_by_id(stage_before.id)
        assert reverted_stage.status is StageStatus.PENDING
        assert reverted_stage.decided_by is None
        assert reverted_stage.decided_at is None
        assert reverted_stage.decision_note is None

        reverted_request = env.request_repo.get_by_id(request.id)
        assert reverted_request.status == request_before.status == RequestStatus.PENDING
        assert reverted_request.current_stage_id == request_before.current_stage_id
        assert reverted_request.completed_at is None

        # The failed audit insert itself never landed, but nothing before
        # it should have either — no REQUEST_CREATED-only trail plus a
        # ghost STAGE_APPROVED.
        audit_actions = [a.action for a in env.audit_repo.list_for_request(request.id).items]
        assert "STAGE_APPROVED" not in audit_actions

    def test_audit_failure_after_a_multi_stage_approval_rolls_back_the_new_stage_too(
        self, env, employee, approver, second_approver, make_definition, monkeypatch
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
        request = _submit(env, employee_identity)
        stage_1 = env.workflow_stage_repo.list_for_request(request.id).items[0]
        request_before = env.request_repo.get_by_id(request.id)

        monkeypatch.setattr(env.audit_repo, "record_event", _raise_repository_error)

        with pytest.raises(EAHError):
            env.approval_service.approve_stage(approver_a_identity, stage_1.id)

        reverted_stage_1 = env.workflow_stage_repo.get_by_id(stage_1.id)
        assert reverted_stage_1.status is StageStatus.PENDING

        # The second stage create_stage() materialized must be gone —
        # otherwise it would be a permanently orphaned row the request
        # never points to and no approver's queue would ever surface.
        remaining_stages = env.workflow_stage_repo.list_for_request(request.id).items
        assert len(remaining_stages) == 1
        assert remaining_stages[0].id == stage_1.id

        reverted_request = env.request_repo.get_by_id(request.id)
        assert reverted_request.status == request_before.status == RequestStatus.PENDING
        assert reverted_request.current_stage_id == request_before.current_stage_id == stage_1.id

    def test_audit_failure_after_a_rejection_rolls_back_the_stage_and_request(
        self, env, employee, approver, make_definition, monkeypatch
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage_before = env.workflow_stage_repo.list_for_request(request.id).items[0]
        request_before = env.request_repo.get_by_id(request.id)

        monkeypatch.setattr(env.audit_repo, "record_event", _raise_repository_error)

        with pytest.raises(EAHError):
            env.approval_service.reject_stage(
                approver_identity, stage_before.id, decision_note="Missing receipts."
            )

        reverted_stage = env.workflow_stage_repo.get_by_id(stage_before.id)
        assert reverted_stage.status is StageStatus.PENDING
        assert reverted_stage.decided_by is None

        reverted_request = env.request_repo.get_by_id(request.id)
        assert reverted_request.status == request_before.status == RequestStatus.PENDING
        assert reverted_request.completed_at is None

    def test_stage_creation_failure_leaves_the_decision_rolled_back_and_the_request_untouched(
        self, env, employee, approver, second_approver, make_definition, monkeypatch
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
        request = _submit(env, employee_identity)
        stage_1 = env.workflow_stage_repo.list_for_request(request.id).items[0]
        request_before = env.request_repo.get_by_id(request.id)

        monkeypatch.setattr(env.workflow_stage_repo, "create_stage", _raise_repository_error)

        with pytest.raises(EAHError):
            env.approval_service.approve_stage(approver_a_identity, stage_1.id)

        reverted_stage_1 = env.workflow_stage_repo.get_by_id(stage_1.id)
        assert reverted_stage_1.status is StageStatus.PENDING

        # create_stage() never succeeded, so there is nothing to have
        # created — the request was never touched at all in this path.
        assert len(env.workflow_stage_repo.list_for_request(request.id).items) == 1
        reverted_request = env.request_repo.get_by_id(request.id)
        assert reverted_request.status == request_before.status
        assert reverted_request.current_stage_id == request_before.current_stage_id

    def test_request_advancement_failure_still_rolls_back_the_decision_and_new_stage(
        self, env, employee, approver, second_approver, make_definition, monkeypatch
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
        request = _submit(env, employee_identity)
        stage_1 = env.workflow_stage_repo.list_for_request(request.id).items[0]

        # Patched only after request creation completes (create_request
        # also calls set_current_stage) so only the approval flow's own
        # call is affected.
        monkeypatch.setattr(env.request_repo, "set_current_stage", _raise_repository_error)

        with pytest.raises(EAHError):
            env.approval_service.approve_stage(approver_a_identity, stage_1.id)

        reverted_stage_1 = env.workflow_stage_repo.get_by_id(stage_1.id)
        assert reverted_stage_1.status is StageStatus.PENDING

        # The second stage's own create_stage() succeeded before the
        # patched set_current_stage call failed — its compensation must
        # still have deleted it.
        assert len(env.workflow_stage_repo.list_for_request(request.id).items) == 1

    def test_escalation_audit_failure_rolls_back_the_reassignment(
        self, env, employee, approver, make_definition, monkeypatch
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[
                specific_user_stage(
                    1, "Manager Review", user_id=approver_profile.id, escalation_hours=1
                )
            ],
        )
        request = _submit(env, employee_identity)
        stage_before = env.workflow_stage_repo.list_for_request(request.id).items[0]
        assert stage_before.assigned_to == approver_profile.id

        monkeypatch.setattr(env.audit_repo, "record_event", _raise_repository_error)

        with pytest.raises(EAHError):
            env.approval_service.escalate_stage(stage_before.id)

        reverted_stage = env.workflow_stage_repo.get_by_id(stage_before.id)
        assert reverted_stage.assigned_to == approver_profile.id
        assert reverted_stage.assigned_role == stage_before.assigned_role
        assert reverted_stage.status is StageStatus.PENDING


class TestNotificationFailureIsolation:
    """A notification is a best-effort side effect dispatched after the
    decision has already durably committed — its own failure must never
    turn an already-successful decision into an API-level error, and must
    never undo the decision either."""

    def test_a_notification_failure_does_not_prevent_a_successful_approval_outcome(
        self, env, employee, approver, make_definition, monkeypatch
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        monkeypatch.setattr(env.notification_repo, "create_notification", _raise_repository_error)

        # No exception propagates, despite the notification write failing.
        outcome = env.approval_service.approve_stage(approver_identity, stage.id)

        assert outcome.request_status is RequestStatus.COMPLETED
        assert outcome.stage.status is StageStatus.APPROVED

        # The decision itself is durably committed — not rolled back —
        # since the failure happened strictly after the transaction
        # boundary (and its own audit entry) already closed successfully.
        committed_stage = env.workflow_stage_repo.get_by_id(stage.id)
        assert committed_stage.status is StageStatus.APPROVED
        committed_request = env.request_repo.get_by_id(request.id)
        assert committed_request.status is RequestStatus.COMPLETED
        audit_actions = [a.action for a in env.audit_repo.list_for_request(request.id).items]
        assert "STAGE_APPROVED" in audit_actions

    def test_an_escalation_notification_failure_does_not_prevent_a_successful_outcome(
        self, env, employee, approver, make_definition, monkeypatch
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[
                specific_user_stage(
                    1, "Manager Review", user_id=approver_profile.id, escalation_hours=1
                )
            ],
        )
        request = _submit(env, employee_identity)
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        monkeypatch.setattr(env.notification_repo, "create_notification", _raise_repository_error)

        escalated = env.approval_service.escalate_stage(stage.id)

        assert escalated.assigned_role is UserRole.ADMIN
        committed_stage = env.workflow_stage_repo.get_by_id(stage.id)
        assert committed_stage.assigned_role is UserRole.ADMIN
