"""Tests for the ``/api/v1/ai/*`` routes: every AI-generated insight.

Exercises the router against a real ``AiInsightService`` (backed by
``tests/fixtures/fakes.py``, matching ``env``'s usual shape, plus a
``FakeAiProvider``) through a real ``TestClient``, mirroring
``test_api_search.py``'s exact pattern for a service-backed router.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.operational_engine import OperationalAnalyticsEngine
from app.analytics.reporting import ReportingEngine
from app.api.main import create_app
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
from app.config.settings import load_settings
from app.services.ai_insight_service import AiInsightService
from app.services.analytics_service import AnalyticsService as ServicesAnalyticsService
from app.services.dashboard_service import DashboardService
from tests.fixtures.factories import specific_user_stage
from tests.fixtures.fakes import FakeAiProvider, FakeAnalyticsRepository

pytestmark = pytest.mark.unit

_TOKEN = "test-token"
_TEST_ENV = {
    "APP_ENVIRONMENT": "development",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_ANON_KEY": "anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
}


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


def _build_ai_insight_service(env, *, ai_provider: FakeAiProvider | None) -> AiInsightService:
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
    operational_engine = OperationalAnalyticsEngine(
        analytics_provider=analytics_engine,
        analytics_repo=analytics_repo,
        request_repo=env.request_repo,
        workflow_stage_repo=env.workflow_stage_repo,
        approval_repo=env.approval_repo,
        workflow_definition_repo=env.workflow_definition_repo,
        audit_repo=env.audit_repo,
        workflow_engine=env.workflow_engine,
    )
    reporting_engine = ReportingEngine(analytics_provider=analytics_engine)
    dashboard_service = DashboardService(
        request_service=env.request_service,
        approval_service=env.approval_service,
        notification_service=env.notification_service,
        analytics_service=ServicesAnalyticsService(analytics_repo=analytics_repo),
    )
    return AiInsightService(
        request_service=env.request_service,
        comment_service=env.comment_service,
        workflow_definition_service=env.workflow_definition_service,
        operational_engine=operational_engine,
        reporting_engine=reporting_engine,
        dashboard_service=dashboard_service,
        ai_provider=ai_provider,
    )


def _build_client(
    env, identity: AuthenticatedIdentity, *, ai_provider: FakeAiProvider | None
) -> TestClient:
    settings = load_settings(env=_TEST_ENV)
    ai_insight_service = _build_ai_insight_service(env, ai_provider=ai_provider)

    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            settings=settings,
            token_verifier=_FakeTokenVerifier(identity),
            ai_insight_service=ai_insight_service,
            redis_client=None,
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


class TestRequestSummaryEndpoint:
    def test_returns_an_ai_insight(self, env, employee, approver, make_definition):
        _, identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="equipment",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = env.request_service.create_request(
            identity, request_type="equipment", title="Laptop purchase"
        )
        client = _build_client(env, identity, ai_provider=FakeAiProvider(response_text="Summary text."))

        response = client.get(f"/api/v1/ai/requests/{request.id}/summary")

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["text"] == "Summary text."
        assert body["is_fallback"] is False

    def test_unknown_request_is_a_404(self, env, employee):
        _, identity = employee
        client = _build_client(env, identity, ai_provider=FakeAiProvider())

        response = client.get(
            "/api/v1/ai/requests/00000000-0000-0000-0000-000000000000/summary"
        )

        assert response.status_code == 404


class TestApprovalSummaryEndpoint:
    def test_returns_an_ai_insight(self, env, employee, approver, make_definition):
        _, identity = employee
        approver_profile, approver_identity = approver
        make_definition(
            request_type="equipment",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        request = env.request_service.create_request(
            identity, request_type="equipment", title="Laptop purchase"
        )
        client = _build_client(
            env, approver_identity, ai_provider=FakeAiProvider(response_text="Approve.")
        )

        response = client.get(f"/api/v1/ai/requests/{request.id}/approval-summary")

        assert response.status_code == 200
        assert response.json()["data"]["text"] == "Approve."


class TestWorkflowImprovementsEndpoint:
    def test_admin_receives_suggestions(self, env, admin, approver, make_definition):
        _, admin_identity = admin
        approver_profile, _ = approver
        make_definition(
            request_type="equipment",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        client = _build_client(
            env, admin_identity, ai_provider=FakeAiProvider(response_text="Improve it.")
        )

        response = client.get("/api/v1/ai/workflows/equipment/improvements")

        assert response.status_code == 200
        assert response.json()["data"]["text"] == "Improve it."

    def test_non_admin_is_forbidden(self, env, approver):
        _, approver_identity = approver
        client = _build_client(env, approver_identity, ai_provider=FakeAiProvider())

        response = client.get("/api/v1/ai/workflows/equipment/improvements")

        assert response.status_code == 403


class TestOperationalEndpoints:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/ai/operations/bottlenecks",
            "/api/v1/ai/operations/policy-recommendations",
            "/api/v1/ai/operations/insights",
            "/api/v1/ai/operations/executive-summary",
        ],
    )
    def test_approver_can_access(self, env, approver, path: str):
        _, approver_identity = approver
        client = _build_client(env, approver_identity, ai_provider=FakeAiProvider(response_text="OK."))

        response = client.get(path)

        assert response.status_code == 200
        assert response.json()["data"]["text"] == "OK."

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/ai/operations/bottlenecks",
            "/api/v1/ai/operations/policy-recommendations",
            "/api/v1/ai/operations/insights",
            "/api/v1/ai/operations/executive-summary",
        ],
    )
    def test_employee_is_forbidden(self, env, employee, path: str):
        _, identity = employee
        client = _build_client(env, identity, ai_provider=FakeAiProvider())

        response = client.get(path)

        assert response.status_code == 403


class TestAssistantEndpoint:
    def test_approver_receives_an_answer(self, env, approver):
        _, approver_identity = approver
        client = _build_client(
            env, approver_identity, ai_provider=FakeAiProvider(response_text="You have 0 open requests.")
        )

        response = client.post(
            "/api/v1/ai/assistant/ask", json={"question": "How many requests are open?"}
        )

        assert response.status_code == 200
        assert response.json()["data"]["text"] == "You have 0 open requests."

    def test_history_round_trips(self, env, approver):
        _, approver_identity = approver
        client = _build_client(env, approver_identity, ai_provider=FakeAiProvider())

        response = client.post(
            "/api/v1/ai/assistant/ask",
            json={
                "question": "follow-up",
                "history": [
                    {"role": "user", "content": "first question"},
                    {"role": "assistant", "content": "first answer"},
                ],
            },
        )

        assert response.status_code == 200

    def test_blank_question_is_rejected(self, env, approver):
        _, approver_identity = approver
        client = _build_client(env, approver_identity, ai_provider=FakeAiProvider())

        response = client.post("/api/v1/ai/assistant/ask", json={"question": ""})

        assert response.status_code == 422

    def test_employee_is_forbidden(self, env, employee):
        _, identity = employee
        client = _build_client(env, identity, ai_provider=FakeAiProvider())

        response = client.post("/api/v1/ai/assistant/ask", json={"question": "question"})

        assert response.status_code == 403
