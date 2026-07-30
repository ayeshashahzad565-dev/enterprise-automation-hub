"""Tests for the ``/api/v1/dashboard-summary`` route: a thin wrapper over
the real, unmodified ``DashboardService`` (already wired on
``tests/conftest.py``'s ``env`` fixture) — no new fake repository was
needed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
from app.services.analytics_service import AnalyticsService
from app.services.dashboard_service import DashboardService
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


def _build_client(env, identity: AuthenticatedIdentity) -> TestClient:
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

    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            dashboard_service=dashboard_service,
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


def test_employee_sees_own_summary_with_no_org_figures(env, employee, make_definition):
    _, employee_identity = employee
    make_definition(
        request_type="expense_reimbursement",
        stages=[
            {
                "order": 1,
                "name": "Manager Review",
                "assignment_strategy": "department_queue",
                "assigned_role": "approver",
                "department": "sales",
                "escalation_hours": 24,
            }
        ],
    )
    env.request_service.create_request(
        employee_identity,
        request_type="expense_reimbursement",
        title="Team lunch",
        description=None,
        department=None,
    )
    client = _build_client(env, employee_identity)

    response = client.get("/api/v1/dashboard-summary")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["open_requests_count"] == 1
    assert data["pending_approvals_count"] == 0
    assert len(data["recent_requests"]) == 1
    assert data["recent_requests"][0]["title"] == "Team lunch"
    assert data["status_breakdown"] is None
    assert data["approval_throughput"] is None


def test_admin_sees_org_wide_figures(env, admin):
    _, admin_identity = admin
    client = _build_client(env, admin_identity)

    response = client.get("/api/v1/dashboard-summary")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status_breakdown"] is not None
    assert data["approval_throughput"] is not None
