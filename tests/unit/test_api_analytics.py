"""Tests for the ``/api/v1/analytics*`` and ``/api/v1/audit-logs`` routes.

Like ``test_api_approvals.py``, these use the real ``AnalyticsEngine``/
``ReportingEngine`` wired to in-memory fake repositories — including a new
``FakeAnalyticsRepository`` (``tests/fixtures/fakes.py``) added specifically
for this test module, since no fake existed for
``app.database.repositories.analytics_repository.AnalyticsRepository``
before Phase 4. Everything else reuses ``tests/conftest.py``'s ``env``
fixture unmodified.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.reporting import ReportingEngine
from app.api.main import create_app
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
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


def _build_analytics_stack(env) -> tuple[AnalyticsEngine, ReportingEngine]:
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


def _build_client(env, identity: AuthenticatedIdentity) -> TestClient:
    analytics_engine, reporting_engine = _build_analytics_stack(env)

    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            request_service=env.request_service,
            approval_service=env.approval_service,
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


def _make_single_stage_definition(env, admin_identity: AuthenticatedIdentity, approver_id) -> None:
    created = env.workflow_definition_service.create_definition(
        admin_identity,
        request_type="expense_reimbursement",
        definition={"stages": [specific_user_stage(1, "Manager Review", user_id=approver_id)]},
    )
    env.workflow_definition_service.activate_version(admin_identity, created.id)


def _create_request(
    client: TestClient, *, title: str = "Team lunch", department: str = "sales"
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/requests",
        json={"request_type": "expense_reimbursement", "title": title, "department": department},
    )
    assert response.status_code == 201
    return response.json()["data"]


class TestDashboardMetrics:
    def test_returns_totals_and_status_breakdown_for_approver(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        approver_client = _build_client(env, approver_identity)
        response = approver_client.get("/api/v1/analytics/dashboard")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total_requests"] >= 1
        assert data["active_requests"] >= 1
        assert "pending" in data["status_breakdown"]["counts"]

    def test_returns_403_for_employee(self, env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.get("/api/v1/analytics/dashboard")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    def test_csv_format_returns_csv_content_type(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        approver_client = _build_client(env, approver_identity)
        response = approver_client.get("/api/v1/analytics/dashboard", params={"format": "csv"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "total_requests" in response.text


class TestScopedMetrics:
    def test_workflow_metrics_scoped_to_request_type(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        approver_client = _build_client(env, approver_identity)
        response = approver_client.get("/api/v1/analytics/workflow/expense_reimbursement")

        assert response.status_code == 200
        assert response.json()["data"]["request_type"] == "expense_reimbursement"

    def test_department_metrics_scoped_to_department(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client, department="sales")

        approver_client = _build_client(env, approver_identity)
        response = approver_client.get("/api/v1/analytics/departments/sales")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["department"] == "sales"
        assert data["workload"] >= 1

    def test_workload_summary_returns_data(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        approver_client = _build_client(env, approver_identity)
        response = approver_client.get("/api/v1/analytics/workload")

        assert response.status_code == 200
        assert isinstance(response.json()["data"], list)

    def test_trend_returns_time_series(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        approver_client = _build_client(env, approver_identity)
        response = approver_client.get("/api/v1/analytics/trend", params={"granularity": "day"})

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["granularity"] == "day"
        assert data["total"] >= 1


class TestUserMetrics:
    def test_self_lookup_allowed_for_approver(self, env, approver):
        approver_profile, approver_identity = approver
        client = _build_client(env, approver_identity)

        response = client.get(f"/api/v1/analytics/users/{approver_profile.id}")

        assert response.status_code == 200
        assert response.json()["data"]["user_id"] == str(approver_profile.id)

    def test_other_user_lookup_requires_admin(self, env, approver, second_approver):
        _, approver_identity = approver
        other_profile, _ = second_approver
        client = _build_client(env, approver_identity)

        response = client.get(f"/api/v1/analytics/users/{other_profile.id}")

        assert response.status_code == 403

    def test_other_user_lookup_allowed_for_admin(self, env, approver, admin):
        approver_profile, _ = approver
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.get(f"/api/v1/analytics/users/{approver_profile.id}")

        assert response.status_code == 200


class TestSummaries:
    def test_executive_summary_returns_narrative(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        approver_client = _build_client(env, approver_identity)
        response = approver_client.get("/api/v1/analytics/summary/executive")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["narrative"]
        assert data["dashboard"] is not None


class TestAgingRequests:
    def test_admin_only(self, env, approver):
        _, approver_identity = approver
        client = _build_client(env, approver_identity)

        response = client.get("/api/v1/analytics/aging-requests")

        assert response.status_code == 403

    def test_admin_sees_pending_stages(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        created = _create_request(employee_client, title="Aging test")

        admin_client = _build_client(env, admin_identity)
        response = admin_client.get(
            "/api/v1/analytics/aging-requests", params={"older_than_hours": 0}
        )

        assert response.status_code == 200
        body = response.json()
        assert any(item["request_id"] == created["id"] for item in body["data"])
        item = next(item for item in body["data"] if item["request_id"] == created["id"])
        assert item["request_title"] == "Aging test"
        assert item["age_hours"] >= 0


class TestRecentActivity:
    def test_admin_only(self, env, approver):
        _, approver_identity = approver
        client = _build_client(env, approver_identity)

        response = client.get("/api/v1/audit-logs")

        assert response.status_code == 403

    def test_admin_sees_activity_with_resolved_actor_name(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_profile, _ = employee
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client, title="Activity test")

        admin_client = _build_client(env, admin_identity)
        response = admin_client.get("/api/v1/audit-logs")

        assert response.status_code == 200
        entries = response.json()["data"]
        created_entries = [e for e in entries if e["action"] == "REQUEST_CREATED"]
        assert created_entries
        assert created_entries[0]["actor_name"] == employee_profile.full_name
