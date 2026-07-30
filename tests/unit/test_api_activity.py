"""Tests for the ``/api/v1/activity/mine`` route and the new ``actor_id``
filter on the existing ``/api/v1/audit-logs`` route.

Both are thin wrappers over the real, unmodified ``AuditRepository``
(already wired on ``tests/conftest.py``'s ``env`` fixture) — real audit
entries are produced the same way production does, by exercising
``RequestService`` through the API, not by inserting fake rows directly.
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


def _build_client(env, identity: AuthenticatedIdentity) -> TestClient:
    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            request_service=env.request_service,
            audit_repo=env.audit_repo,
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


def _create_request(client: TestClient, *, title: str = "Team lunch") -> dict[str, Any]:
    response = client.post(
        "/api/v1/requests",
        json={"request_type": "expense_reimbursement", "title": title, "department": "sales"},
    )
    assert response.status_code == 201
    return response.json()["data"]


class TestMyActivity:
    def test_accessible_to_employee_and_scoped_to_self(self, env, employee, approver, admin):
        employee_profile, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client, title="Mine")

        response = employee_client.get("/api/v1/activity/mine")

        assert response.status_code == 200
        entries = response.json()["data"]
        assert entries
        assert all(e["actor_id"] == str(employee_profile.id) for e in entries)
        assert any(e["action"] == "REQUEST_CREATED" for e in entries)

        approver_client = _build_client(env, approver_identity)
        approver_response = approver_client.get("/api/v1/activity/mine")
        assert approver_response.status_code == 200
        assert approver_response.json()["data"] == []

    def test_actor_name_resolves_to_caller(self, env, employee, approver, admin):
        employee_profile, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)
        _create_request(client)

        response = client.get("/api/v1/activity/mine")

        entries = response.json()["data"]
        assert entries[0]["actor_name"] == employee_profile.full_name

    def test_action_filter(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        client = _build_client(env, employee_identity)
        created = _create_request(client)
        withdraw = client.delete(
            f"/api/v1/requests/{created['id']}", params={"expected_version": created["version"]}
        )
        assert withdraw.status_code == 204

        response = client.get("/api/v1/activity/mine", params={"action": "REQUEST_WITHDRAWN"})

        entries = response.json()["data"]
        assert entries
        assert all(e["action"] == "REQUEST_WITHDRAWN" for e in entries)


class TestOrganizationActivityActorFilter:
    def test_actor_id_filters_to_specific_user(self, env, employee, second_approver, admin):
        employee_profile, employee_identity = employee
        approver_profile, _ = second_approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client, title="From employee")

        admin_client = _build_client(env, admin_identity)
        response = admin_client.get(
            "/api/v1/audit-logs", params={"actor_id": str(employee_profile.id)}
        )

        assert response.status_code == 200
        entries = response.json()["data"]
        assert entries
        assert all(e["actor_id"] == str(employee_profile.id) for e in entries)
