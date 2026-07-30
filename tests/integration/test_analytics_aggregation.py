"""Real-database proof that ``AnalyticsRepository``'s SQL-side aggregate
queries (``0022_analytics_aggregation_functions``) return the same shape
of result the prior Python-side ``Counter``/``sum`` implementation did —
against actual Postgres, not the in-memory fakes ``tests/unit`` substitutes
for this repository everywhere else (``FakeAnalyticsRepository`` in
``tests/fixtures/fakes.py`` has its own, independent implementation and is
never exercised by these tests).

Each test seeds a small, exactly-known population under a fresh, unique
``request_type`` (or, for the request-type grouping test, two of them),
so assertions can check specific keys/counts without needing to account
for whatever other integration tests have also created requests in the
same session-scoped ``test_company_id``.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import RequestStatus, UserRole
from tests.fixtures.factories import specific_user_stage

pytestmark = pytest.mark.integration


class TestAnalyticsRepositoryAggregation:
    def test_count_requests_by_status_matches_a_known_seeded_population(
        self, real_repos, make_test_profile, test_company_id, _committing_pg_conn
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        request_type = f"itest_analytics_status_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type, version=1, definition={"stages": []}, created_by=admin.id
        )
        pending = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Pending",
            company_id=test_company_id,
        )
        completed = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Completed",
            company_id=test_company_id,
        )
        rejected = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Rejected",
            company_id=test_company_id,
        )
        assert pending.status is RequestStatus.PENDING
        # count_requests_by_status has no repository-level method to move
        # a request past its first pending stage decision — these two
        # rows are pushed directly to their terminal status via a raw
        # superuser connection purely to seed a known population for the
        # aggregate query under test, the same technique test_company_id
        # itself already uses for setup.
        with _committing_pg_conn.cursor() as cur:
            cur.execute(
                "update public.requests set status = 'completed' where id = %s;",
                (str(completed.id),),
            )
            cur.execute(
                "update public.requests set status = 'rejected' where id = %s;",
                (str(rejected.id),),
            )

        breakdown = real_repos.analytics.count_requests_by_status(
            company_id=test_company_id, request_type=request_type
        )

        assert breakdown.counts == {
            RequestStatus.PENDING: 1,
            RequestStatus.COMPLETED: 1,
            RequestStatus.REJECTED: 1,
        }
        assert breakdown.total == 3

    def test_count_requests_by_type_groups_by_request_type(
        self, real_repos, make_test_profile, test_company_id
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        type_a = f"itest_analytics_type_a_{uuid.uuid4().hex[:8]}"
        type_b = f"itest_analytics_type_b_{uuid.uuid4().hex[:8]}"
        definition_a = real_repos.workflow_definition.create_definition(
            request_type=type_a, version=1, definition={"stages": []}, created_by=admin.id
        )
        definition_b = real_repos.workflow_definition.create_definition(
            request_type=type_b, version=1, definition={"stages": []}, created_by=admin.id
        )
        for title in ("A1", "A2"):
            real_repos.request.create_request(
                requester_id=employee.id,
                workflow_definition_id=definition_a.id,
                request_type=type_a,
                title=title,
                company_id=test_company_id,
            )
        real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition_b.id,
            request_type=type_b,
            title="B1",
            company_id=test_company_id,
        )

        # No request_type filter exists on this method by design (it's the
        # grouping key) — assert specific keys, not the full dict/total,
        # since other requests may exist in this session-scoped company
        # under other request types.
        volume = real_repos.analytics.count_requests_by_type(company_id=test_company_id)

        assert volume.counts[type_a] == 2
        assert volume.counts[type_b] == 1

    def test_count_requests_by_department_groups_null_and_empty_string_as_unspecified(
        self, real_repos, make_test_profile, test_company_id, _committing_pg_conn
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        request_type = f"itest_analytics_dept_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type, version=1, definition={"stages": []}, created_by=admin.id
        )
        real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Has department",
            company_id=test_company_id,
            department="finance",
        )
        real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Null department",
            company_id=test_company_id,
        )
        empty_department = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Empty-string department",
            company_id=test_company_id,
        )
        with _committing_pg_conn.cursor() as cur:
            cur.execute(
                "update public.requests set department = '' where id = %s;",
                (str(empty_department.id),),
            )

        volume = real_repos.analytics.count_requests_by_department(
            company_id=test_company_id, request_type=request_type
        )

        assert volume.counts == {"finance": 1, "unspecified": 2}
        assert volume.total == 3

    def test_approval_throughput_computes_completion_rate_and_average_latency(
        self, real_repos, make_test_profile, test_company_id, _committing_pg_conn
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        approver = make_test_profile(role=UserRole.APPROVER)
        request_type = f"itest_analytics_throughput_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type,
            version=1,
            definition={"stages": [specific_user_stage(1, "Manager Review", user_id=approver.id)]},
            created_by=admin.id,
        )
        request = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Throughput request",
            company_id=test_company_id,
        )
        stage = real_repos.workflow_stage.create_stage(
            request_id=request.id,
            stage_order=1,
            stage_name="Manager Review",
            assigned_to=approver.id,
        )
        real_repos.approval.approve_stage(stage.id, expected_version=1, decided_by=approver.id)
        with _committing_pg_conn.cursor() as cur:
            # approve_stage stamps decided_at = now(); create_stage stamps
            # created_at = now() a moment earlier. Backdating created_at
            # to exactly one hour before the real decided_at makes this
            # stage's contribution to the average a known, deterministic
            # 3600 seconds, rather than an unpredictable few-millisecond gap.
            cur.execute(
                "update public.workflow_stages set created_at = decided_at - interval '1 hour' "
                "where id = %s;",
                (str(stage.id),),
            )
            cur.execute(
                "update public.requests set status = 'completed' where id = %s;",
                (str(request.id),),
            )

        throughput = real_repos.analytics.approval_throughput(
            company_id=test_company_id, request_type=request_type
        )

        assert throughput.completed_count == 1
        assert throughput.rejected_count == 0
        assert throughput.completion_rate == pytest.approx(1.0)
        assert throughput.average_decision_seconds == pytest.approx(3600.0, abs=1.0)

    def test_approval_throughput_is_none_when_nothing_has_been_decided(
        self, real_repos, make_test_profile, test_company_id
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        request_type = f"itest_analytics_no_decisions_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type, version=1, definition={"stages": []}, created_by=admin.id
        )
        real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Still pending",
            company_id=test_company_id,
        )

        throughput = real_repos.analytics.approval_throughput(
            company_id=test_company_id, request_type=request_type
        )

        assert throughput.completed_count == 0
        assert throughput.rejected_count == 0
        assert throughput.completion_rate is None
        assert throughput.average_decision_seconds is None
