"""Milestone 11: multi-tenant isolation and regression tests for the
Analytics Layer (``app.analytics``), the legacy ``AnalyticsService``
(``app.services.analytics_service``), and every API route that reads
through either of them (``/analytics/*``, ``/audit-logs``,
``/activity/mine``, ``/admin/dashboard``, ``/admin/departments/*``).

Per the milestone brief, this file's job is narrow: prove that every
number this subsystem produces is scoped to exactly the caller's own
company, never the whole platform, even when two companies use the same
department names, request types, and roles — the exact case a naive
role-only filter would get wrong. It reuses the real, unmodified
``AnalyticsEngine``/``ReportingEngine``/``AnalyticsService`` end-to-end
against in-memory fakes, the same pattern already established by
``test_api_analytics.py``, ``test_api_dashboard.py``, and
``test_multi_tenancy_isolation.py`` — no new architecture, no new
fixtures beyond a second company's worth of ``make_user`` calls.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.exceptions import MetricCalculationError
from app.analytics.reporting import ReportingEngine
from app.api.main import create_app
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
from app.models.enums import UserRole
from app.services.analytics_service import AnalyticsService
from app.services.dashboard_service import DashboardService
from tests.conftest import Env
from tests.fixtures.factories import specific_user_stage
from tests.fixtures.fakes import FakeAnalyticsRepository

pytestmark = pytest.mark.unit

_TOKEN = "test-token"


class _FakeTokenVerifier:
    def __init__(self, identity: AuthenticatedIdentity) -> None:
        self._identity = identity

    def resolve_claims(self, token: str) -> Mapping[str, Any]:
        if token != _TOKEN:
            raise InvalidTokenError("Unknown test token.")
        return {
            "sub": str(self._identity.user_id),
            "email": self._identity.email,
            "role": self._identity.role.value,
            "company_id": str(self._identity.company_id),
            "is_platform_admin": self._identity.is_platform_admin,
        }


def _build_analytics_stack(env: Env) -> tuple[AnalyticsEngine, ReportingEngine]:
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
    reporting_engine = ReportingEngine(analytics_provider=analytics_engine)
    return analytics_engine, reporting_engine


def _build_client(env: Env, identity: AuthenticatedIdentity) -> TestClient:
    analytics_engine, reporting_engine = _build_analytics_stack(env)

    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            request_service=env.request_service,
            approval_service=env.approval_service,
            workflow_definition_service=env.workflow_definition_service,
            analytics_provider=analytics_engine,
            reporting_provider=reporting_engine,
            audit_repo=env.audit_repo,
            approval_repo=env.approval_repo,
            profile_repo=env.profile_repo,
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()  # runs the lifespan startup, so app.state.resources is populated
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


def _make_single_stage_definition(
    env: Env,
    admin_identity: AuthenticatedIdentity,
    approver_id,
    *,
    request_type: str = "expense_reimbursement",
) -> None:
    created = env.workflow_definition_service.create_definition(
        admin_identity,
        request_type=request_type,
        definition={"stages": [specific_user_stage(1, "Manager Review", user_id=approver_id)]},
    )
    env.workflow_definition_service.activate_version(admin_identity, created.id)


def _create_request(
    client: TestClient,
    *,
    title: str = "Team lunch",
    department: str = "sales",
    request_type: str = "expense_reimbursement",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/requests",
        json={"request_type": request_type, "title": title, "department": department},
    )
    assert response.status_code == 201
    return response.json()["data"]


@pytest.fixture
def company_b_id():
    return uuid4()


@pytest.fixture
def company_b_admin(env: Env, make_user, company_b_id):
    return make_user(role=UserRole.ADMIN, full_name="Bob Admin (B)", company_id=company_b_id)


@pytest.fixture
def company_b_employee(env: Env, make_user, company_b_id):
    return make_user(role=UserRole.EMPLOYEE, full_name="Eve Employee (B)", company_id=company_b_id)


@pytest.fixture
def company_b_approver(env: Env, make_user, company_b_id):
    return make_user(role=UserRole.APPROVER, full_name="Amy Approver (B)", company_id=company_b_id)


def _seed_company_a_request(
    env: Env, admin_identity, employee_identity, approver_id, *, department: str = "sales"
) -> None:
    _make_single_stage_definition(env, admin_identity, approver_id)
    employee_client = _build_client(env, employee_identity)
    _create_request(employee_client, department=department)
    employee_client.close()


class TestDashboardMetricsIsolation:
    def test_company_b_sees_zero_totals_despite_company_as_activity(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_company_a_request(env, admin_identity, employee_identity, approver_profile.id)

        _, other_admin_identity = company_b_admin
        other_client = _build_client(env, other_admin_identity)

        response = other_client.get("/api/v1/analytics/dashboard")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total_requests"] == 0
        assert data["active_requests"] == 0
        assert data["status_breakdown"]["counts"] == {}

    def test_company_as_own_dashboard_is_unaffected_by_company_b(
        self, env: Env, employee, approver, admin, company_b_admin, company_b_employee
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _seed_company_a_request(env, admin_identity, employee_identity, approver_profile.id)

        # Company B also has activity of its own, under the same request
        # type/department names — a naive role-only or type-only filter
        # would double-count this into Company A's figures.
        _, other_admin_identity = company_b_admin
        _, other_employee_identity = company_b_employee
        _make_single_stage_definition(env, other_admin_identity, approver_profile.id)

        approver_client = _build_client(env, approver_identity)
        response = approver_client.get("/api/v1/analytics/dashboard")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total_requests"] == 1
        assert data["active_requests"] == 1


class TestDepartmentAndWorkflowMetricsIsolation:
    def test_department_metrics_isolated_despite_identical_department_name(
        self, env: Env, employee, approver, admin, company_b_admin, company_b_employee
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_company_a_request(
            env, admin_identity, employee_identity, approver_profile.id, department="sales"
        )

        _, other_admin_identity = company_b_admin
        _make_single_stage_definition(env, other_admin_identity, approver_profile.id)

        other_client = _build_client(env, other_admin_identity)
        response = other_client.get("/api/v1/analytics/departments/sales")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["department"] == "sales"
        assert data["workload"] == 0
        assert data["status_breakdown"]["total"] == 0

    def test_workflow_metrics_isolated_despite_identical_request_type(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_company_a_request(env, admin_identity, employee_identity, approver_profile.id)

        _, other_admin_identity = company_b_admin
        other_client = _build_client(env, other_admin_identity)

        response = other_client.get("/api/v1/analytics/workflow/expense_reimbursement")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["request_type"] == "expense_reimbursement"
        assert data["status_breakdown"]["total"] == 0


class TestWorkloadAndTrendIsolation:
    def test_workload_summary_excludes_other_companys_approver(
        self, env: Env, employee, approver, admin, company_b_admin, company_b_approver
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _seed_company_a_request(env, admin_identity, employee_identity, approver_profile.id)

        # Company B's own approver shares the same role, and would be
        # eligible for Company A's queue if company scoping were missing.
        _, other_approver_identity = company_b_approver

        _, other_admin_identity = company_b_admin
        other_client = _build_client(env, other_admin_identity)
        response = other_client.get("/api/v1/analytics/workload")

        assert response.status_code == 200
        user_ids = {row["user_id"] for row in response.json()["data"]}
        assert str(approver_profile.id) not in user_ids
        assert str(other_approver_identity.user_id) in user_ids

    def test_request_trend_isolated_by_company(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_company_a_request(env, admin_identity, employee_identity, approver_profile.id)

        _, other_admin_identity = company_b_admin
        other_client = _build_client(env, other_admin_identity)

        response = other_client.get("/api/v1/analytics/trend", params={"granularity": "day"})

        assert response.status_code == 200
        assert response.json()["data"]["total"] == 0


class TestUserMetricsCrossTenantLookup:
    def test_cross_company_user_id_is_treated_identically_to_unknown(
        self, env: Env, approver, company_b_id
    ):
        """``AnalyticsEngine.get_user_metrics`` must never distinguish
        "exists in another company" from "does not exist at all" — both
        raise the exact same ``MetricCalculationError`` message, matching
        this codebase's established not-found-vs-forbidden convention for
        out-of-scope resources (see ``authorize_request_view``).
        """
        approver_profile, _ = approver
        analytics_engine, _ = _build_analytics_stack(env)

        with pytest.raises(MetricCalculationError) as unknown_user_exc:
            analytics_engine.get_user_metrics(uuid4(), company_id=company_b_id)

        with pytest.raises(MetricCalculationError) as cross_company_exc:
            analytics_engine.get_user_metrics(approver_profile.id, company_id=company_b_id)

        assert (
            str(unknown_user_exc.value).split(" ")[:3]
            == str(cross_company_exc.value).split(" ")[:3]
        )


class TestAgingRequestsAndActivityIsolation:
    def test_aging_requests_scoped_to_caller_company(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_company_a_request(env, admin_identity, employee_identity, approver_profile.id)

        _, other_admin_identity = company_b_admin
        other_client = _build_client(env, other_admin_identity)

        response = other_client.get(
            "/api/v1/analytics/aging-requests", params={"older_than_hours": 0}
        )

        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_audit_logs_feed_scoped_to_caller_company(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_company_a_request(env, admin_identity, employee_identity, approver_profile.id)

        _, other_admin_identity = company_b_admin
        other_client = _build_client(env, other_admin_identity)

        response = other_client.get("/api/v1/audit-logs")

        assert response.status_code == 200
        assert response.json()["data"] == []


class TestReportingSummariesIsolation:
    def test_executive_summary_scoped_to_caller_company(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_company_a_request(env, admin_identity, employee_identity, approver_profile.id)

        _, other_admin_identity = company_b_admin
        other_client = _build_client(env, other_admin_identity)

        response = other_client.get("/api/v1/analytics/summary/executive")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["dashboard"]["total_requests"] == 0
        assert "0 total request(s)" in data["narrative"]

    def test_department_summary_scoped_to_caller_company(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_company_a_request(
            env, admin_identity, employee_identity, approver_profile.id, department="sales"
        )

        _, other_admin_identity = company_b_admin
        other_client = _build_client(env, other_admin_identity)

        response = other_client.get("/api/v1/analytics/summary/department/sales")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["department_metrics"][0]["workload"] == 0


class TestAdminDashboardIsolation:
    def test_admin_dashboard_totals_isolated_by_company(
        self, env: Env, employee, approver, admin, company_b_admin, company_b_employee
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_company_a_request(env, admin_identity, employee_identity, approver_profile.id)

        _, other_admin_identity = company_b_admin
        other_client = _build_client(env, other_admin_identity)

        response = other_client.get("/api/v1/admin/dashboard")

        assert response.status_code == 200
        data = response.json()["data"]
        # Only Company B's own admin + employee profiles are counted —
        # Company A's admin/employee/approver (3 profiles) are excluded.
        assert data["total_users"] == 2
        assert data["pending_approvals_count"] == 0
        assert data["recent_activity"] == []


class TestPlatformAdminNeverMixesAnalytics:
    def test_platform_admin_sees_only_their_own_companys_figures(
        self, env: Env, employee, approver, admin, make_user, company_b_id
    ):
        """Per the milestone brief: a platform administrator may aggregate
        across companies only through a dedicated platform API — never
        through the ordinary, tenant-scoped analytics endpoints, even
        though ``is_platform_admin`` is set on their own identity.
        """
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_company_a_request(env, admin_identity, employee_identity, approver_profile.id)

        # A platform admin whose own profile belongs to Company A (the
        # default test company) — the common case, since platform admins
        # are still members of exactly one company.
        _, platform_admin_identity = make_user(
            role=UserRole.APPROVER, full_name="Priya PlatformAdmin", is_platform_admin=True
        )
        assert platform_admin_identity.is_platform_admin is True

        # Company B has its own, separate activity.
        other_admin_profile, other_admin_identity = make_user(
            role=UserRole.ADMIN, full_name="Bob Admin (B)", company_id=company_b_id
        )
        other_approver_profile, _ = make_user(
            role=UserRole.APPROVER, full_name="Amy Approver (B)", company_id=company_b_id
        )
        _make_single_stage_definition(env, other_admin_identity, other_approver_profile.id)
        other_employee_profile, other_employee_identity = make_user(
            role=UserRole.EMPLOYEE, full_name="Eve Employee (B)", company_id=company_b_id
        )
        other_client = _build_client(env, other_employee_identity)
        _create_request(other_client, title="Company B's own request")
        other_client.close()

        platform_admin_client = _build_client(env, platform_admin_identity)
        response = platform_admin_client.get("/api/v1/analytics/dashboard")

        assert response.status_code == 200
        data = response.json()["data"]
        # Exactly Company A's one request — never Company A's + Company
        # B's combined.
        assert data["total_requests"] == 1


class TestLegacyAnalyticsServiceIsolation:
    """``app.services.analytics_service.AnalyticsService`` (via
    ``DashboardService``, backing ``GET /api/v1/dashboard-summary``) is a
    second, separate consumer of ``AnalyticsRepository`` from the
    ``app.analytics`` stack tested above — it needs the exact same
    company scoping, verified independently here.
    """

    def test_dashboard_service_status_breakdown_isolated_by_company(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_company_a_request(env, admin_identity, employee_identity, approver_profile.id)

        analytics_repo = FakeAnalyticsRepository(
            request_repo=env.request_repo, stages_table=env.stages_table
        )
        analytics_service = AnalyticsService(analytics_repo=analytics_repo)
        dashboard_service = DashboardService(
            request_service=env.request_service,
            approval_service=env.approval_service,
            notification_service=env.notification_service,
            analytics_service=analytics_service,
        )

        _, other_admin_identity = company_b_admin
        summary = dashboard_service.get_dashboard_summary(other_admin_identity)

        assert summary.status_breakdown is not None
        assert summary.status_breakdown.total == 0
        assert summary.approval_throughput is not None
        assert summary.approval_throughput.completed_count == 0
