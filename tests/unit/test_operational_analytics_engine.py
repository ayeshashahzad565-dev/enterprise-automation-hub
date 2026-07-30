"""Unit tests for ``app.analytics.operational_engine.OperationalAnalyticsEngine``
(Milestone 12): SLA calculations, approval-delay detection, bottleneck
detection, workload analytics, trend analytics, executive KPIs, and
department analytics.

Every test exercises the real, unmodified ``OperationalAnalyticsEngine``
end-to-end against ``tests/conftest.py``'s ``env`` fixture's in-memory
fakes — the same pattern ``test_api_analytics.py`` already established.
Since every calculation here is time-sensitive (stage age, SLA breach,
decision duration), tests that need a specific elapsed time backdate the
relevant fake record's ``created_at``/``decided_at`` directly via
``FakeTable.update_unconditional`` — the same "arbitrary field override
for deterministic test setup" tool this suite already relies on — rather
than sleeping in real time or mocking the clock.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.dto import TimeGranularity
from app.analytics.operational_engine import OperationalAnalyticsEngine
from app.utils.datetime_utils import utc_now
from tests.conftest import Env
from tests.fixtures.factories import specific_user_stage
from tests.fixtures.fakes import FakeAnalyticsRepository

pytestmark = pytest.mark.unit


def _build_engine(env: Env) -> OperationalAnalyticsEngine:
    analytics_repo = FakeAnalyticsRepository(env.request_repo, env.stages_table)
    analytics_engine = AnalyticsEngine(
        analytics_repo=analytics_repo,
        request_repo=env.request_repo,
        approval_repo=env.approval_repo,
        workflow_stage_repo=env.workflow_stage_repo,
        profile_repo=env.profile_repo,
        audit_repo=env.audit_repo,
        notification_repo=env.notification_repo,
    )
    return OperationalAnalyticsEngine(
        analytics_provider=analytics_engine,
        analytics_repo=analytics_repo,
        request_repo=env.request_repo,
        workflow_stage_repo=env.workflow_stage_repo,
        approval_repo=env.approval_repo,
        workflow_definition_repo=env.workflow_definition_repo,
        audit_repo=env.audit_repo,
        workflow_engine=env.workflow_engine,
    )


def _activate_definition(
    env: Env, admin_identity, approver_id, *, request_type: str, escalation_hours: float = 24.0
):
    created = env.workflow_definition_service.create_definition(
        admin_identity,
        request_type=request_type,
        definition={
            "stages": [
                specific_user_stage(
                    1, "Manager Review", user_id=approver_id, escalation_hours=escalation_hours
                )
            ]
        },
    )
    return env.workflow_definition_service.activate_version(admin_identity, created.id)


def _current_stage(env: Env, request_id):
    return env.workflow_stage_repo.list_for_request(request_id).items[0]


def _backdate_stage(env: Env, stage_id, *, hours_ago: float | None = None, **overrides):
    changes = dict(overrides)
    if hours_ago is not None:
        changes["created_at"] = utc_now() - timedelta(hours=hours_ago)
    return env.stages_table.update_unconditional(stage_id, **changes)


class TestDefinitionResolutionAvoidsN1:
    def test_resolving_multiple_distinct_definitions_never_calls_get_by_id(
        self, env: Env, employee, approver, admin
    ):
        """Milestone 13, Medium finding 8: _resolve_definitions used to
        call workflow_definition_repo.get_by_id once per distinct
        definition id — a real N+1. It now resolves every distinct
        definition referenced by the stages in scope through a single
        bulk list_by_ids fetch instead."""
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(
            env, admin_identity, approver_profile.id, request_type="expense", escalation_hours=24
        )
        _activate_definition(
            env, admin_identity, approver_profile.id, request_type="equipment", escalation_hours=24
        )
        env.request_service.create_request(employee_identity, request_type="expense", title="One")
        env.request_service.create_request(employee_identity, request_type="equipment", title="Two")

        engine = _build_engine(env)
        with (
            patch.object(
                env.workflow_definition_repo,
                "get_by_id",
                wraps=env.workflow_definition_repo.get_by_id,
            ) as get_by_id_spy,
            patch.object(
                env.workflow_definition_repo,
                "list_by_ids",
                wraps=env.workflow_definition_repo.list_by_ids,
            ) as list_by_ids_spy,
        ):
            result = engine.get_sla_metrics(company_id=admin_identity.company_id)

        assert result.pending_stage_count == 2
        assert get_by_id_spy.call_count == 0
        assert list_by_ids_spy.call_count == 1


class TestSLAMetrics:
    def test_pending_stage_within_sla_is_not_overdue(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(
            env, admin_identity, approver_profile.id, request_type="expense", escalation_hours=24
        )
        env.request_service.create_request(
            employee_identity, request_type="expense", title="Team lunch"
        )

        engine = _build_engine(env)
        result = engine.get_sla_metrics(company_id=admin_identity.company_id)

        assert result.pending_stage_count == 1
        assert result.overdue_stage_count == 0
        assert result.overdue_request_count == 0
        assert result.average_current_stage_age_hours is not None
        assert result.average_current_stage_age_hours < 1.0

    def test_pending_stage_past_sla_is_overdue(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(
            env, admin_identity, approver_profile.id, request_type="expense", escalation_hours=24
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense", title="Team lunch"
        )
        stage = _current_stage(env, created.id)
        _backdate_stage(env, stage.id, hours_ago=30)

        engine = _build_engine(env)
        result = engine.get_sla_metrics(company_id=admin_identity.company_id)

        assert result.overdue_stage_count == 1
        assert result.overdue_request_count == 1

    def test_sla_hours_override_takes_precedence_over_definition(
        self, env: Env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(
            env, admin_identity, approver_profile.id, request_type="expense", escalation_hours=100
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense", title="Team lunch"
        )
        stage = _current_stage(env, created.id)
        _backdate_stage(env, stage.id, hours_ago=2)

        engine = _build_engine(env)
        not_overdue = engine.get_sla_metrics(company_id=admin_identity.company_id)
        assert not_overdue.overdue_stage_count == 0

        overdue = engine.get_sla_metrics(
            company_id=admin_identity.company_id, sla_hours_override=1.0
        )
        assert overdue.overdue_stage_count == 1
        assert overdue.sla_hours_override == 1.0

    def test_sla_compliance_percentage_over_decided_stages(
        self, env: Env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _activate_definition(
            env, admin_identity, approver_profile.id, request_type="expense", escalation_hours=1
        )

        # Decided in time: created "now", decided "now" (well within 1h).
        on_time = env.request_service.create_request(
            employee_identity, request_type="expense", title="On time"
        )
        on_time_stage = _current_stage(env, on_time.id)
        env.approval_service.approve_stage(approver_identity, on_time_stage.id)

        # Decided late: created 5h ago, decided "now" (breached the 1h SLA).
        late = env.request_service.create_request(
            employee_identity, request_type="expense", title="Late"
        )
        late_stage = _current_stage(env, late.id)
        _backdate_stage(env, late_stage.id, hours_ago=5)
        late_stage = _current_stage(env, late.id)
        env.approval_service.approve_stage(approver_identity, late_stage.id)

        engine = _build_engine(env)
        result = engine.get_sla_metrics(company_id=admin_identity.company_id)

        assert result.decided_stage_count == 2
        assert result.sla_breaches_decided == 1
        assert result.sla_compliance_percentage == pytest.approx(0.5)

    def test_average_approval_duration_reuses_analytics_repository(
        self, env: Env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")
        created = env.request_service.create_request(
            employee_identity, request_type="expense", title="Team lunch"
        )
        stage = _current_stage(env, created.id)
        env.approval_service.approve_stage(approver_identity, stage.id)

        engine = _build_engine(env)
        analytics_repo = FakeAnalyticsRepository(env.request_repo, env.stages_table)
        expected = analytics_repo.approval_throughput(
            company_id=admin_identity.company_id
        ).average_decision_seconds

        result = engine.get_sla_metrics(company_id=admin_identity.company_id)

        assert result.average_approval_duration_seconds == expected

    def test_department_scope_disables_average_approval_duration(
        self, env: Env, employee, approver, admin
    ):
        """Mirrors ``ApprovalMetrics``'s own documented rule: department
        scope disables ``average_decision_seconds`` since
        ``AnalyticsRepository.approval_throughput`` has no department
        parameter — this engine must not silently fabricate one."""
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")
        created = env.request_service.create_request(
            employee_identity, request_type="expense", title="Team lunch", department="sales"
        )
        stage = _current_stage(env, created.id)
        env.approval_service.approve_stage(approver_identity, stage.id)

        engine = _build_engine(env)
        result = engine.get_sla_metrics(company_id=admin_identity.company_id, department="sales")

        assert result.average_approval_duration_seconds is None


class TestApprovalDelays:
    def test_longest_pending_sorted_by_age_descending(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")

        older = env.request_service.create_request(
            employee_identity, request_type="expense", title="Older"
        )
        older_stage = _current_stage(env, older.id)
        _backdate_stage(env, older_stage.id, hours_ago=10)

        newer = env.request_service.create_request(
            employee_identity, request_type="expense", title="Newer"
        )
        newer_stage = _current_stage(env, newer.id)
        _backdate_stage(env, newer_stage.id, hours_ago=1)

        engine = _build_engine(env)
        result = engine.get_approval_delays(company_id=admin_identity.company_id)

        assert [p.stage_id for p in result.longest_pending[:2]] == [older_stage.id, newer_stage.id]

    def test_oldest_pending_requests_ordered_by_request_created_at(
        self, env: Env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")

        first = env.request_service.create_request(
            employee_identity, request_type="expense", title="First"
        )
        second = env.request_service.create_request(
            employee_identity, request_type="expense", title="Second"
        )

        engine = _build_engine(env)
        result = engine.get_approval_delays(company_id=admin_identity.company_id)

        request_ids = [p.request_id for p in result.oldest_pending_requests]
        assert request_ids == [first.id, second.id]

    def test_median_and_average_approval_seconds(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")

        durations_hours = [1.0, 2.0, 9.0]  # -> 3600s, 7200s, 32400s; mean=14400, median=7200
        for hours in durations_hours:
            created = env.request_service.create_request(
                employee_identity, request_type="expense", title=f"Req {hours}"
            )
            stage = _current_stage(env, created.id)
            _backdate_stage(env, stage.id, hours_ago=hours)
            stage = _current_stage(env, created.id)
            env.approval_service.approve_stage(approver_identity, stage.id)

        engine = _build_engine(env)
        result = engine.get_approval_delays(company_id=admin_identity.company_id)

        assert result.average_approval_seconds == pytest.approx(14400, rel=0.01)
        assert result.median_approval_seconds == pytest.approx(7200, rel=0.01)

    def test_duration_by_department_buckets_slowest_first(
        self, env: Env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")

        fast = env.request_service.create_request(
            employee_identity, request_type="expense", title="Fast", department="sales"
        )
        fast_stage = _current_stage(env, fast.id)
        env.approval_service.approve_stage(approver_identity, fast_stage.id)

        slow = env.request_service.create_request(
            employee_identity, request_type="expense", title="Slow", department="engineering"
        )
        slow_stage = _current_stage(env, slow.id)
        _backdate_stage(env, slow_stage.id, hours_ago=10)
        slow_stage = _current_stage(env, slow.id)
        env.approval_service.approve_stage(approver_identity, slow_stage.id)

        engine = _build_engine(env)
        result = engine.get_approval_delays(company_id=admin_identity.company_id)

        keys = [bucket.key for bucket in result.duration_by_department]
        assert keys[0] == "engineering"
        assert keys[1] == "sales"


class TestBottlenecks:
    def test_approver_queue_depth_reuses_workload_summary(
        self, env: Env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")
        env.request_service.create_request(employee_identity, request_type="expense", title="One")
        env.request_service.create_request(employee_identity, request_type="expense", title="Two")

        engine = _build_engine(env)
        result = engine.get_bottlenecks(company_id=admin_identity.company_id)

        matching = [u for u in result.approver_queue_depth if u.user_id == approver_profile.id]
        assert matching
        assert matching[0].pending_assigned_count == 2

    def test_get_bottlenecks_fetches_the_pending_stage_population_only_once(
        self, env: Env, employee, approver, admin
    ):
        """Milestone 13, High finding 6: get_bottlenecks used to trigger
        two independent full scans of the pending-stage population — its
        own, plus a second one inside get_workload_summary. Passing the
        already-fetched population through collapses this to one."""
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")
        env.request_service.create_request(employee_identity, request_type="expense", title="One")

        engine = _build_engine(env)
        with patch.object(
            env.approval_repo, "list_overdue_stages", wraps=env.approval_repo.list_overdue_stages
        ) as spy:
            engine.get_bottlenecks(company_id=admin_identity.company_id)

        assert spy.call_count == 1

    def test_resolving_many_distinct_requests_batches_the_in_clause(
        self, env: Env, employee, approver, admin
    ):
        """A large ``.in_("id", [...])`` filter can exceed the gateway's
        URL length limit and be rejected outright before it ever reaches
        PostgREST. ``_bulk_requests_by_id`` must split more than
        ``_ID_FILTER_BATCH_SIZE`` distinct request ids across several
        bounded-size calls rather than one unbounded one."""
        from app.analytics.operational_engine import _ID_FILTER_BATCH_SIZE

        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")
        request_count = _ID_FILTER_BATCH_SIZE + 1
        for i in range(request_count):
            env.request_service.create_request(
                employee_identity, request_type="expense", title=f"Request {i}"
            )

        engine = _build_engine(env)
        with patch.object(
            env.request_repo, "list_requests", wraps=env.request_repo.list_requests
        ) as spy:
            result = engine.get_bottlenecks(company_id=admin_identity.company_id)

        assert result is not None
        request_id_batches = [
            call.kwargs["request_ids"] for call in spy.call_args_list if "request_ids" in call.kwargs
        ]
        assert len(request_id_batches) >= 2, "expected more than one batch for > batch-size ids"
        assert all(len(batch) <= _ID_FILTER_BATCH_SIZE for batch in request_id_batches)
        assert sum(len(batch) for batch in request_id_batches) == request_count

    def test_frequently_overdue_stages_counts_only_currently_overdue(
        self, env: Env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(
            env, admin_identity, approver_profile.id, request_type="expense", escalation_hours=24
        )

        overdue = env.request_service.create_request(
            employee_identity, request_type="expense", title="Overdue"
        )
        overdue_stage = _current_stage(env, overdue.id)
        _backdate_stage(env, overdue_stage.id, hours_ago=48)

        env.request_service.create_request(
            employee_identity, request_type="expense", title="On time"
        )

        engine = _build_engine(env)
        result = engine.get_bottlenecks(company_id=admin_identity.company_id)

        matching = [b for b in result.frequently_overdue_stages if b.key == "Manager Review"]
        assert len(matching) == 1
        assert matching[0].count == 1

    def test_rejection_hotspots_rate(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")

        approved = env.request_service.create_request(
            employee_identity, request_type="expense", title="Approved"
        )
        approved_stage = _current_stage(env, approved.id)
        env.approval_service.approve_stage(approver_identity, approved_stage.id)

        rejected = env.request_service.create_request(
            employee_identity, request_type="expense", title="Rejected"
        )
        rejected_stage = _current_stage(env, rejected.id)
        env.approval_service.reject_stage(
            approver_identity, rejected_stage.id, decision_note="Not valid."
        )

        engine = _build_engine(env)
        result = engine.get_bottlenecks(company_id=admin_identity.company_id)

        matching = [b for b in result.rejection_hotspots if b.key == "Manager Review"]
        assert matching
        assert matching[0].decided_count == 2
        assert matching[0].rejected_count == 1
        assert matching[0].rejection_rate == pytest.approx(0.5)


class TestWorkloadReport:
    def test_get_workload_report_fetches_the_pending_stage_population_only_once(
        self, env: Env, employee, approver, admin
    ):
        """Milestone 13, High finding 6 — same duplication as
        get_bottlenecks, fixed the same way."""
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")
        env.request_service.create_request(employee_identity, request_type="expense", title="One")

        engine = _build_engine(env)
        with patch.object(
            env.approval_repo, "list_overdue_stages", wraps=env.approval_repo.list_overdue_stages
        ) as spy:
            engine.get_workload_report(company_id=admin_identity.company_id)

        assert spy.call_count == 1

    def test_completed_today_week_month_boundaries(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")

        today = env.request_service.create_request(
            employee_identity, request_type="expense", title="Today"
        )
        env.approval_service.approve_stage(approver_identity, _current_stage(env, today.id).id)

        within_week = env.request_service.create_request(
            employee_identity, request_type="expense", title="Within week"
        )
        env.approval_service.approve_stage(
            approver_identity, _current_stage(env, within_week.id).id
        )
        env.request_repo._table.update_unconditional(
            within_week.id, completed_at=utc_now() - timedelta(days=3)
        )

        outside_month = env.request_service.create_request(
            employee_identity, request_type="expense", title="Outside month"
        )
        env.approval_service.approve_stage(
            approver_identity, _current_stage(env, outside_month.id).id
        )
        env.request_repo._table.update_unconditional(
            outside_month.id, completed_at=utc_now() - timedelta(days=45)
        )

        engine = _build_engine(env)
        result = engine.get_workload_report(company_id=admin_identity.company_id)

        assert result.completed_today == 1
        assert result.completed_this_week == 2
        assert result.completed_this_month == 2

    def test_reuses_dashboard_metrics_for_active_and_completed_workload(
        self, env: Env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")
        env.request_service.create_request(
            employee_identity, request_type="expense", title="Active"
        )

        engine = _build_engine(env)
        analytics_repo = FakeAnalyticsRepository(env.request_repo, env.stages_table)
        analytics_engine = AnalyticsEngine(
            analytics_repo=analytics_repo,
            request_repo=env.request_repo,
            approval_repo=env.approval_repo,
            workflow_stage_repo=env.workflow_stage_repo,
            profile_repo=env.profile_repo,
            audit_repo=env.audit_repo,
            notification_repo=env.notification_repo,
        )
        dashboard = analytics_engine.get_dashboard_metrics(company_id=admin_identity.company_id)

        result = engine.get_workload_report(company_id=admin_identity.company_id)

        assert result.active_workload == dashboard.active_requests
        assert result.completed_workload == dashboard.completed_requests
        assert result.pending_workload == 1


class TestTrends:
    def test_request_volume_matches_analytics_provider(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")
        env.request_service.create_request(employee_identity, request_type="expense", title="One")

        engine = _build_engine(env)
        analytics_repo = FakeAnalyticsRepository(env.request_repo, env.stages_table)
        analytics_engine = AnalyticsEngine(
            analytics_repo=analytics_repo,
            request_repo=env.request_repo,
            approval_repo=env.approval_repo,
            workflow_stage_repo=env.workflow_stage_repo,
            profile_repo=env.profile_repo,
            audit_repo=env.audit_repo,
            notification_repo=env.notification_repo,
        )
        expected = analytics_engine.get_request_trend(
            company_id=admin_identity.company_id, granularity=TimeGranularity.DAY
        )

        result = engine.get_trends(
            company_id=admin_identity.company_id, granularity=TimeGranularity.DAY
        )

        assert result.request_volume == expected

    def test_approval_and_rejection_trend_counts(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")

        approved = env.request_service.create_request(
            employee_identity, request_type="expense", title="Approved"
        )
        env.approval_service.approve_stage(approver_identity, _current_stage(env, approved.id).id)

        rejected = env.request_service.create_request(
            employee_identity, request_type="expense", title="Rejected"
        )
        env.approval_service.reject_stage(
            approver_identity, _current_stage(env, rejected.id).id, decision_note="No."
        )

        engine = _build_engine(env)
        result = engine.get_trends(
            company_id=admin_identity.company_id, granularity=TimeGranularity.DAY
        )

        assert result.approval_trend.total == 1
        assert result.rejection_trend.total == 1

    def test_completion_and_average_duration_trend(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")

        created = env.request_service.create_request(
            employee_identity, request_type="expense", title="Done"
        )
        env.approval_service.approve_stage(approver_identity, _current_stage(env, created.id).id)

        engine = _build_engine(env)
        result = engine.get_trends(
            company_id=admin_identity.company_id, granularity=TimeGranularity.DAY
        )

        assert result.completion_trend.total == 1
        assert len(result.average_completion_time_trend.points) == 1
        assert result.average_completion_time_trend.points[0].value >= 0


class TestExecutiveKPIs:
    def test_composes_dashboard_and_sla_metrics(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _activate_definition(env, admin_identity, approver_profile.id, request_type="expense")
        created = env.request_service.create_request(
            employee_identity, request_type="expense", title="One"
        )
        env.approval_service.approve_stage(approver_identity, _current_stage(env, created.id).id)

        engine = _build_engine(env)
        sla = engine.get_sla_metrics(company_id=admin_identity.company_id)

        result = engine.get_executive_kpis(company_id=admin_identity.company_id)

        assert result.average_approval_seconds == sla.average_approval_duration_seconds
        assert result.sla_compliance_percentage == sla.sla_compliance_percentage
        assert result.completed_requests == 1
        assert result.rejection_rate == pytest.approx(0.0)

    def test_workflow_efficiency_score_is_product_of_completion_and_sla_compliance(
        self, env: Env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _activate_definition(
            env, admin_identity, approver_profile.id, request_type="expense", escalation_hours=24
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense", title="One"
        )
        env.approval_service.approve_stage(approver_identity, _current_stage(env, created.id).id)

        engine = _build_engine(env)
        result = engine.get_executive_kpis(company_id=admin_identity.company_id)

        # A single, on-time, completed request: completion_rate = 1.0,
        # sla_compliance = 1.0 -> efficiency score = 1.0.
        assert result.workflow_efficiency_score == pytest.approx(1.0)


class TestDepartmentAnalytics:
    def test_reuses_department_metrics_and_sla_backlog(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _activate_definition(
            env, admin_identity, approver_profile.id, request_type="expense", escalation_hours=24
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense", title="One", department="sales"
        )
        stage = _current_stage(env, created.id)
        _backdate_stage(env, stage.id, hours_ago=48)

        engine = _build_engine(env)
        sla = engine.get_sla_metrics(company_id=admin_identity.company_id, department="sales")

        result = engine.get_department_analytics("sales", company_id=admin_identity.company_id)

        assert result.department == "sales"
        assert result.backlog_count == sla.overdue_stage_count == 1
        assert result.active_workload == 1

    def test_department_with_no_activity_returns_zeroed_report(
        self, env: Env, employee, approver, admin
    ):
        _, _ = employee
        _, _ = approver
        _, admin_identity = admin

        engine = _build_engine(env)
        result = engine.get_department_analytics(
            "nonexistent", company_id=admin_identity.company_id
        )

        assert result.active_workload == 0
        assert result.backlog_count == 0
        assert result.sla_compliance_percentage is None
