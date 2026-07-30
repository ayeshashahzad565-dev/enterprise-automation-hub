"""Tests for the ``/api/v1/analytics/operational/*`` routes (Milestone 12).

Same pattern as ``test_api_analytics.py``: the real ``OperationalAnalyticsEngine``
(and the ``AnalyticsEngine`` it composes) wired to in-memory fake
repositories, exercised end-to-end through a real ``TestClient``. Covers
RBAC, response contract/shape, and — critically — cross-tenant isolation:
a second company's data must never leak into these endpoints, even when
both companies use identical department/request_type/stage names.
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
from app.analytics.operational_engine import OperationalAnalyticsEngine
from app.api.main import create_app
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
from app.models.enums import UserRole
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


def _build_operational_stack(env: Env) -> OperationalAnalyticsEngine:
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


def _build_client(env: Env, identity: AuthenticatedIdentity) -> TestClient:
    operational_engine = _build_operational_stack(env)

    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            operational_analytics_provider=operational_engine,
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


def _activate_definition(env: Env, admin_identity, approver_id, *, request_type: str = "expense"):
    created = env.workflow_definition_service.create_definition(
        admin_identity,
        request_type=request_type,
        definition={"stages": [specific_user_stage(1, "Manager Review", user_id=approver_id)]},
    )
    env.workflow_definition_service.activate_version(admin_identity, created.id)


def _seed_request(env: Env, admin_identity, employee_identity, approver_id, *, department="sales"):
    _activate_definition(env, admin_identity, approver_id)
    env.request_service.create_request(
        employee_identity, request_type="expense", title="Team lunch", department=department
    )


class TestRBAC:
    def test_employee_forbidden_on_every_endpoint(self, env: Env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        for path in [
            "/api/v1/analytics/operational/sla",
            "/api/v1/analytics/operational/approval-delays",
            "/api/v1/analytics/operational/bottlenecks",
            "/api/v1/analytics/operational/workload",
            "/api/v1/analytics/operational/trends",
            "/api/v1/analytics/operational/executive",
            "/api/v1/analytics/operational/departments/sales",
        ]:
            response = client.get(path)
            assert response.status_code == 403, path


class TestResponseContracts:
    def test_sla_endpoint_returns_expected_shape(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(env, admin_identity, employee_identity, approver_profile.id)
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/analytics/operational/sla")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["pending_stage_count"] == 1
        assert "sla_compliance_percentage" in data

    def test_sla_endpoint_accepts_override(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(env, admin_identity, employee_identity, approver_profile.id)
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/analytics/operational/sla", params={"sla_hours": 0.0001})

        assert response.status_code == 200
        assert response.json()["data"]["sla_hours_override"] == pytest.approx(0.0001)

    def test_approval_delays_endpoint(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(env, admin_identity, employee_identity, approver_profile.id)
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/analytics/operational/approval-delays")

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["longest_pending"]) == 1
        assert data["longest_pending"][0]["stage_name"] == "Manager Review"

    def test_bottlenecks_endpoint(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(env, admin_identity, employee_identity, approver_profile.id)
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/analytics/operational/bottlenecks")

        assert response.status_code == 200
        data = response.json()["data"]
        assert "approver_queue_depth" in data
        assert "rejection_hotspots" in data

    def test_workload_endpoint(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(env, admin_identity, employee_identity, approver_profile.id)
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/analytics/operational/workload")

        assert response.status_code == 200
        assert response.json()["data"]["pending_workload"] == 1

    def test_trends_endpoint_accepts_granularity(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(env, admin_identity, employee_identity, approver_profile.id)
        client = _build_client(env, admin_identity)

        response = client.get(
            "/api/v1/analytics/operational/trends", params={"granularity": "week"}
        )

        assert response.status_code == 200
        assert response.json()["data"]["request_volume"]["granularity"] == "week"

    def test_executive_endpoint(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(env, admin_identity, employee_identity, approver_profile.id)
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/analytics/operational/executive")

        assert response.status_code == 200
        assert response.json()["data"]["pending_approvals"] == 1

    def test_department_endpoint(self, env: Env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(
            env, admin_identity, employee_identity, approver_profile.id, department="sales"
        )
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/analytics/operational/departments/sales")

        assert response.status_code == 200
        assert response.json()["data"]["department"] == "sales"
        assert response.json()["data"]["active_workload"] == 1


@pytest.fixture
def company_b_id():
    return uuid4()


@pytest.fixture
def company_b_admin(env: Env, make_user, company_b_id):
    return make_user(role=UserRole.ADMIN, full_name="Bob Admin (B)", company_id=company_b_id)


class TestTenantIsolation:
    def test_sla_metrics_isolated_by_company(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(env, admin_identity, employee_identity, approver_profile.id)

        _, other_admin_identity = company_b_admin
        client = _build_client(env, other_admin_identity)

        response = client.get("/api/v1/analytics/operational/sla")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["pending_stage_count"] == 0
        assert data["overdue_stage_count"] == 0

    def test_approval_delays_isolated_by_company(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(env, admin_identity, employee_identity, approver_profile.id)

        _, other_admin_identity = company_b_admin
        client = _build_client(env, other_admin_identity)

        response = client.get("/api/v1/analytics/operational/approval-delays")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["longest_pending"] == []
        assert data["oldest_pending_requests"] == []

    def test_bottlenecks_isolated_despite_identical_stage_name(
        self, env: Env, employee, approver, admin, company_b_admin, make_user, company_b_id
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(env, admin_identity, employee_identity, approver_profile.id)

        _, other_admin_identity = company_b_admin
        # Company B's own approver, same role, same stage name as Company A.
        other_approver_profile, _ = make_user(
            role=UserRole.APPROVER, full_name="Amy (B)", company_id=company_b_id
        )
        _activate_definition(env, other_admin_identity, other_approver_profile.id)

        client = _build_client(env, other_admin_identity)
        response = client.get("/api/v1/analytics/operational/bottlenecks")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["frequently_overdue_stages"] == []
        assert data["rejection_hotspots"] == []

    def test_workload_isolated_by_company(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(env, admin_identity, employee_identity, approver_profile.id)

        _, other_admin_identity = company_b_admin
        client = _build_client(env, other_admin_identity)

        response = client.get("/api/v1/analytics/operational/workload")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["pending_workload"] == 0
        assert data["active_workload"] == 0

    def test_executive_kpis_isolated_by_company(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(env, admin_identity, employee_identity, approver_profile.id)

        _, other_admin_identity = company_b_admin
        client = _build_client(env, other_admin_identity)

        response = client.get("/api/v1/analytics/operational/executive")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["pending_approvals"] == 0
        assert data["active_requests"] == 0

    def test_department_analytics_isolated_despite_identical_department_name(
        self, env: Env, employee, approver, admin, company_b_admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _seed_request(
            env, admin_identity, employee_identity, approver_profile.id, department="sales"
        )

        _, other_admin_identity = company_b_admin
        client = _build_client(env, other_admin_identity)

        response = client.get("/api/v1/analytics/operational/departments/sales")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["active_workload"] == 0
        assert data["backlog_count"] == 0
