"""Tests for ``app.scheduler.jobs.load_stage_context``'s optional
definition cache, and ``EscalationJob``/``ReminderJob``'s use of it
(Milestone 13, Medium finding 1).

Both jobs used to re-fetch a stage's pinned workflow definition
independently for every candidate stage in a run, even when many stages
share the same definition (the common case — one definition per active
request type/version). Passing one shared cache dict across every
``load_stage_context`` call within a single run collapses repeated
fetches for the same definition id down to one.
"""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.scheduler.escalation_job import EscalationJob
from app.scheduler.interfaces import ExecutionContext
from app.scheduler.jobs import load_stage_context
from app.scheduler.reminder_job import ReminderJob
from app.utils.datetime_utils import utc_now
from tests.fixtures.factories import specific_user_stage

pytestmark = pytest.mark.unit


def _context() -> ExecutionContext:
    return ExecutionContext(job_name="test", scheduled_time=utc_now(), run_id=str(uuid4()))


class _RecordingJobDispatcher:
    """A minimal ``JobDispatcher`` fake that just records enqueue calls.

    Every stage in these tests uses ``escalation_hours=24`` on a
    freshly-created request, so neither ``EscalationJob`` nor
    ``ReminderJob`` ever considers a stage eligible/due within a single
    test run — ``enqueue`` is therefore never actually invoked here; this
    fake exists only to satisfy the constructor's ``job_dispatcher``
    parameter.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def enqueue(self, **kwargs):
        self.calls.append(kwargs)
        return None


class TestLoadStageContextCache:
    def test_a_shared_cache_avoids_refetching_the_same_definition(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[
                specific_user_stage(
                    1, "Manager Review", user_id=approver_profile.id, escalation_hours=24
                )
            ],
        )
        request = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        cache: dict = {}
        with patch.object(
            env.workflow_definition_repo,
            "get_by_id",
            wraps=env.workflow_definition_repo.get_by_id,
        ) as spy:
            load_stage_context(
                stage,
                request_repo=env.request_repo,
                workflow_definition_repo=env.workflow_definition_repo,
                definition_cache=cache,
            )
            load_stage_context(
                stage,
                request_repo=env.request_repo,
                workflow_definition_repo=env.workflow_definition_repo,
                definition_cache=cache,
            )

        assert spy.call_count == 1

    def test_with_no_cache_every_call_refetches(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[
                specific_user_stage(
                    1, "Manager Review", user_id=approver_profile.id, escalation_hours=24
                )
            ],
        )
        request = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )
        stage = env.workflow_stage_repo.list_for_request(request.id).items[0]

        with patch.object(
            env.workflow_definition_repo,
            "get_by_id",
            wraps=env.workflow_definition_repo.get_by_id,
        ) as spy:
            load_stage_context(
                stage,
                request_repo=env.request_repo,
                workflow_definition_repo=env.workflow_definition_repo,
            )
            load_stage_context(
                stage,
                request_repo=env.request_repo,
                workflow_definition_repo=env.workflow_definition_repo,
            )

        assert spy.call_count == 2


class TestSchedulerJobDefinitionCaching:
    def test_escalation_job_fetches_a_shared_definition_only_once_per_run(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[
                specific_user_stage(
                    1, "Manager Review", user_id=approver_profile.id, escalation_hours=24
                )
            ],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="One"
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Two"
        )

        job = EscalationJob(
            job_dispatcher=_RecordingJobDispatcher(),
            approval_repo=env.approval_repo,
            request_repo=env.request_repo,
            workflow_definition_repo=env.workflow_definition_repo,
            workflow_engine=env.workflow_engine,
        )

        with patch.object(
            env.workflow_definition_repo,
            "get_by_id",
            wraps=env.workflow_definition_repo.get_by_id,
        ) as spy:
            result = job.run(_context())

        assert result.success is True
        assert result.items_processed == 2
        assert spy.call_count == 1

    def test_reminder_job_fetches_a_shared_definition_only_once_per_run(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[
                specific_user_stage(
                    1, "Manager Review", user_id=approver_profile.id, escalation_hours=24
                )
            ],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="One"
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Two"
        )

        job = ReminderJob(
            job_dispatcher=_RecordingJobDispatcher(),
            approval_repo=env.approval_repo,
            request_repo=env.request_repo,
            workflow_definition_repo=env.workflow_definition_repo,
            notification_repo=env.notification_repo,
            workflow_engine=env.workflow_engine,
        )

        with patch.object(
            env.workflow_definition_repo,
            "get_by_id",
            wraps=env.workflow_definition_repo.get_by_id,
        ) as spy:
            result = job.run(_context())

        assert result.success is True
        assert result.items_processed == 2
        assert spy.call_count == 1
