"""Concurrency tests: simultaneous decisions racing for the same stage.

These tests use real OS threads to genuinely race multiple callers
against the same in-memory row, rather than only simulating a race
sequentially — proving the optimistic-locking guarantee (a single row
version, checked and incremented under a lock, exactly like a real
``UPDATE ... WHERE version = :expected``) holds under actual concurrent
execution. The outcome is nonetheless fully deterministic: regardless of
thread interleaving, exactly one decision may ever win.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.database.exceptions import ConcurrentUpdateError
from tests.fixtures.factories import specific_user_stage

pytestmark = pytest.mark.performance


def test_exactly_one_concurrent_approval_attempt_succeeds(env, employee, approver, make_definition):
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

    attempts = 8

    def _attempt(_: int) -> str:
        try:
            env.approval_repo.approve_stage(
                stage.id, expected_version=stage.version, decided_by=approver_profile.id
            )
            return "succeeded"
        except ConcurrentUpdateError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=attempts) as executor:
        results = list(executor.map(_attempt, range(attempts)))

    assert results.count("succeeded") == 1
    assert results.count("rejected") == attempts - 1

    final_stage = env.workflow_stage_repo.get_by_id(stage.id)
    assert final_stage.version == stage.version + 1


def test_concurrent_notification_creation_for_the_same_recipient_never_loses_a_record(
    env, employee
):
    """A high-volume sanity check that concurrent writes to independent
    rows (distinct notifications, same recipient) are never dropped —
    unlike the single-row race above, these do not contend for the same
    optimistic-locking version at all, so every attempt must succeed.
    """
    employee_profile, _ = employee
    attempts = 20

    def _notify(i: int) -> None:
        env.notification_service.notify_system(
            recipient_id=employee_profile.id, message=f"Message {i}"
        )

    with ThreadPoolExecutor(max_workers=attempts) as executor:
        list(executor.map(_notify, range(attempts)))

    stored = env.notification_repo._table.values()
    assert len(stored) == attempts
