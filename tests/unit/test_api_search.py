"""Tests for the ``/api/v1/search/*`` routes: enterprise-wide search,
saved filters, and search history.

Exercises the router against the real ``GlobalSearchService`` (backed by
``tests/fixtures/fakes.py``, matching ``env``'s usual shape) through a
real ``TestClient``, mirroring ``test_api_platform.py``'s exact pattern
for a service-backed router.
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
from app.config.settings import load_settings
from tests.fixtures.factories import specific_user_stage

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


def _build_client(env, identity: AuthenticatedIdentity) -> TestClient:
    settings = load_settings(env=_TEST_ENV)

    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            settings=settings,
            token_verifier=_FakeTokenVerifier(identity),
            search_service=env.search_service,
            redis_client=None,
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


class TestSearchEndpoint:
    def test_missing_query_is_rejected(self, env, employee):
        _, identity = employee
        client = _build_client(env, identity)

        response = client.get("/api/v1/search")

        assert response.status_code == 422

    def test_finds_the_callers_own_request(
        self, env, employee, approver, make_definition
    ):
        _, identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        env.request_service.create_request(
            identity, request_type="expense_reimbursement", title="Onboarding laptop"
        )
        client = _build_client(env, identity)

        response = client.get("/api/v1/search", params={"q": "laptop"})

        assert response.status_code == 200
        body = response.json()
        assert any(item["entity_type"] == "request" for item in body["data"])
        assert body["pagination"]["total_records"] >= 1

    def test_entity_types_filter_narrows_results(
        self, env, employee, approver, make_definition
    ):
        _, identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        env.request_service.create_request(
            identity, request_type="expense_reimbursement", title="Zephyr project"
        )
        client = _build_client(env, identity)

        response = client.get(
            "/api/v1/search", params={"q": "Zephyr", "entity_types": "workflow"}
        )

        assert response.status_code == 200
        entity_types_found = {item["entity_type"] for item in response.json()["data"]}
        assert entity_types_found <= {"workflow"}

    def test_a_non_admin_never_gets_user_results(self, env, employee, approver):
        _, identity = employee
        approver_profile, _ = approver
        client = _build_client(env, identity)

        response = client.get(
            "/api/v1/search",
            params={"q": approver_profile.full_name, "entity_types": "user"},
        )

        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_pagination_params_are_respected(
        self, env, employee, approver, make_definition
    ):
        _, identity = employee
        approver_profile, _ = approver
        make_definition(
            request_type="expense_reimbursement",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
        )
        for i in range(3):
            env.request_service.create_request(
                identity, request_type="expense_reimbursement", title=f"Widget order {i}"
            )
        client = _build_client(env, identity)

        response = client.get(
            "/api/v1/search",
            params={"q": "Widget", "entity_types": "request", "page": 1, "page_size": 2},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 2
        assert body["pagination"]["total_records"] == 3


class TestSavedFilters:
    def test_create_list_and_delete_round_trip(self, env, employee):
        _, identity = employee
        client = _build_client(env, identity)

        created = client.post(
            "/api/v1/search/saved-filters",
            json={"name": "My filter", "query_text": "widgets", "entity_types": ["request"]},
        )
        assert created.status_code == 201
        filter_id = created.json()["data"]["id"]

        listed = client.get("/api/v1/search/saved-filters")
        assert listed.status_code == 200
        assert any(f["id"] == filter_id for f in listed.json()["data"])

        deleted = client.delete(f"/api/v1/search/saved-filters/{filter_id}")
        assert deleted.status_code == 204

        listed_after = client.get("/api/v1/search/saved-filters")
        assert listed_after.json()["data"] == []

    def test_deleting_an_unknown_filter_is_a_404(self, env, employee):
        _, identity = employee
        client = _build_client(env, identity)

        response = client.delete(
            "/api/v1/search/saved-filters/00000000-0000-0000-0000-000000000000"
        )

        assert response.status_code == 404


class TestSearchHistory:
    def test_a_search_populates_history_and_clear_empties_it(self, env, employee):
        _, identity = employee
        client = _build_client(env, identity)

        client.get("/api/v1/search", params={"q": "anything", "entity_types": "request"})

        history = client.get("/api/v1/search/history")
        assert history.status_code == 200
        assert [h["query_text"] for h in history.json()["data"]] == ["anything"]

        cleared = client.delete("/api/v1/search/history")
        assert cleared.status_code == 204

        history_after = client.get("/api/v1/search/history")
        assert history_after.json()["data"] == []
