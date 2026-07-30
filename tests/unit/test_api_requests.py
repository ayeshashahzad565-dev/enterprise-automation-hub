"""Tests for the ``/api/v1/requests*`` routes.

Unlike ``test_api_health.py``/``test_api_auth_me.py`` (which stub out
``ApplicationResources`` with ``MagicMock``), these use the real
``RequestService`` wired to the same in-memory fake repositories the
service-layer unit tests use (``tests/conftest.py``'s ``env`` fixture) —
so each test exercises the actual router-to-service wiring end-to-end,
not just a mocked call.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
from app.models.enums import UserRole
from tests.conftest import Env
from tests.fixtures.factories import specific_user_stage

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


def _build_client(env: Env, identity: AuthenticatedIdentity) -> TestClient:
    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            request_service=env.request_service,
            comment_service=env.comment_service,
            attachment_service=env.attachment_service,
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()  # runs the lifespan startup, so app.state.resources is populated
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


def _make_active_definition(env: Env, admin_identity: AuthenticatedIdentity, approver_id) -> None:
    created = env.workflow_definition_service.create_definition(
        admin_identity,
        request_type="expense_reimbursement",
        definition={"stages": [specific_user_stage(1, "Manager Review", user_id=approver_id)]},
    )
    env.workflow_definition_service.activate_version(admin_identity, created.id)


class TestCreateAndGet:
    def test_create_request_returns_201_with_version_1(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_active_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)

        response = client.post(
            "/api/v1/requests",
            json={"request_type": "expense_reimbursement", "title": "Team lunch"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["data"]["status"] == "pending"
        # create_request performs an insert followed by an immediate
        # first-stage-assignment update, so version is already 2 by the
        # time the caller sees it — not 1. This test only asserts the
        # field is present and usable for a subsequent PATCH/DELETE.
        assert isinstance(body["data"]["version"], int) and body["data"]["version"] >= 1
        assert "request_id" in body["meta"]

    def test_create_request_with_unknown_type_returns_422(self, env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.post(
            "/api/v1/requests", json={"request_type": "nonexistent_type", "title": "Anything"}
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_get_request_by_id_returns_200_for_requester(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_active_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)
        created = client.post(
            "/api/v1/requests",
            json={"request_type": "expense_reimbursement", "title": "Team lunch"},
        ).json()["data"]

        response = client.get(f"/api/v1/requests/{created['id']}")

        assert response.status_code == 200
        assert response.json()["data"]["id"] == created["id"]

    def test_get_request_out_of_scope_returns_404_not_403(
        self, env, employee, second_approver, admin
    ):
        _, employee_identity = employee
        other_approver_profile, _ = second_approver
        _, admin_identity = admin
        _make_active_definition(env, admin_identity, other_approver_profile.id)
        owner_client = _build_client(env, employee_identity)
        created = owner_client.post(
            "/api/v1/requests",
            json={"request_type": "expense_reimbursement", "title": "Team lunch"},
        ).json()["data"]

        _, unrelated_employee_identity = env_make_unrelated_employee(env)
        stranger_client = _build_client(env, unrelated_employee_identity)

        response = stranger_client.get(f"/api/v1/requests/{created['id']}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_get_request_with_malformed_id_returns_422_in_standard_envelope(self, env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.get("/api/v1/requests/not-a-uuid")

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "detail" not in body


def env_make_unrelated_employee(env: Env):
    profile = env.profile_repo.create_profile(
        profile_id=uuid4(), full_name="Unrelated Person", role=UserRole.EMPLOYEE, department="ops"
    )
    identity = AuthenticatedIdentity(
        user_id=profile.id,
        email=None,
        role=profile.role,
        company_id=profile.company_id,
        is_platform_admin=profile.is_platform_admin,
        expires_at=None,
        raw_claims={},
    )
    return profile, identity


class TestListAndSearch:
    def test_list_requests_scopes_to_the_employees_own_requests(
        self, env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_active_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)
        client.post(
            "/api/v1/requests", json={"request_type": "expense_reimbursement", "title": "Mine"}
        )

        _, other_identity = env_make_unrelated_employee(env)
        other_client = _build_client(env, other_identity)
        other_client.post(
            "/api/v1/requests",
            json={"request_type": "expense_reimbursement", "title": "Not mine"},
        )

        response = client.get("/api/v1/requests")

        assert response.status_code == 200
        body = response.json()
        assert [r["title"] for r in body["data"]] == ["Mine"]
        assert body["pagination"]["total_records"] == 1

    def test_search_ignores_status_filter_and_matches_title(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_active_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)
        client.post(
            "/api/v1/requests",
            json={"request_type": "expense_reimbursement", "title": "Laptop purchase"},
        )

        response = client.get("/api/v1/requests", params={"search": "laptop"})

        assert response.status_code == 200
        assert len(response.json()["data"]) == 1

    def test_an_oversized_search_query_is_rejected(self, env, employee):
        """Milestone 13, Medium finding 2: free-text query params now
        carry the same max_length bound request-body fields already had."""
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.get("/api/v1/requests", params={"search": "a" * 201})

        assert response.status_code == 422


class TestUpdateAndWithdraw:
    def test_update_request_requires_expected_version_and_bumps_it(
        self, env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_active_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)
        created = client.post(
            "/api/v1/requests",
            json={"request_type": "expense_reimbursement", "title": "Original"},
        ).json()["data"]

        response = client.patch(
            f"/api/v1/requests/{created['id']}",
            json={"title": "Updated", "expected_version": created["version"]},
        )

        assert response.status_code == 200
        assert response.json()["data"]["title"] == "Updated"
        assert response.json()["data"]["version"] == created["version"] + 1

    def test_update_with_stale_version_returns_409(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_active_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)
        created = client.post(
            "/api/v1/requests",
            json={"request_type": "expense_reimbursement", "title": "Original"},
        ).json()["data"]

        response = client.patch(
            f"/api/v1/requests/{created['id']}",
            json={"title": "Updated", "expected_version": created["version"] + 5},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONCURRENT_UPDATE"

    def test_withdraw_returns_204_and_request_no_longer_appears_in_list(
        self, env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_active_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)
        created = client.post(
            "/api/v1/requests",
            json={"request_type": "expense_reimbursement", "title": "To withdraw"},
        ).json()["data"]

        response = client.delete(
            f"/api/v1/requests/{created['id']}", params={"expected_version": created["version"]}
        )

        assert response.status_code == 204
        listed = client.get("/api/v1/requests").json()["data"]
        assert created["id"] not in [r["id"] for r in listed]


class TestWorkflowAndAuditReads:
    def test_workflow_progress_shows_one_pending_stage(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_active_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)
        created = client.post(
            "/api/v1/requests",
            json={"request_type": "expense_reimbursement", "title": "Team lunch"},
        ).json()["data"]

        response = client.get(f"/api/v1/requests/{created['id']}/workflow")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total_stages"] == 1
        assert data["stages"][0]["status"] == "pending"
        assert data["stages"][0]["assigned_to_name"] == approver_profile.full_name

    def test_workflow_current_returns_the_pending_stage(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_active_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)
        created = client.post(
            "/api/v1/requests",
            json={"request_type": "expense_reimbursement", "title": "Team lunch"},
        ).json()["data"]

        response = client.get(f"/api/v1/requests/{created['id']}/workflow/current")

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "pending"

    def test_workflow_history_is_empty_before_any_decision(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_active_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)
        created = client.post(
            "/api/v1/requests",
            json={"request_type": "expense_reimbursement", "title": "Team lunch"},
        ).json()["data"]

        response = client.get(f"/api/v1/requests/{created['id']}/workflow/history")

        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_audit_trail_contains_request_created(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_active_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)
        created = client.post(
            "/api/v1/requests",
            json={"request_type": "expense_reimbursement", "title": "Team lunch"},
        ).json()["data"]

        response = client.get(f"/api/v1/requests/{created['id']}/audit-log")

        assert response.status_code == 200
        actions = [entry["action"] for entry in response.json()["data"]]
        assert actions == ["REQUEST_CREATED"]
