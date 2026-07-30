"""Tests for the ``/api/v1/workflow-definitions*`` routes.

Every route is a thin wrapper over the real, unmodified
``WorkflowDefinitionService`` (already wired on ``tests/conftest.py``'s
``env`` fixture) — no new fake repository was needed.
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

pytestmark = pytest.mark.unit

_TOKEN = "test-token"

_ONE_STAGE_BODY = {
    "request_type": "expense_reimbursement",
    "definition": {
        "stages": [
            {
                "order": 1,
                "name": "Manager Review",
                "assignment_strategy": "department_queue",
                "assigned_role": "approver",
                "department": "sales",
                "escalation_hours": 24,
            }
        ]
    },
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
    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            workflow_definition_service=env.workflow_definition_service,
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()  # runs the lifespan startup, so app.state.resources is populated
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


class TestCreate:
    def test_admin_can_create_draft(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY)

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["request_type"] == "expense_reimbursement"
        assert data["version"] == 1
        assert data["is_active"] is False
        assert data["definition"]["stages"][0]["name"] == "Manager Review"

    def test_employee_is_forbidden(self, env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY)

        assert response.status_code == 403

    def test_invalid_stage_ordering_is_422(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)
        body = {
            "request_type": "expense_reimbursement",
            "definition": {
                "stages": [
                    {
                        "order": 2,
                        "name": "Only stage",
                        "assignment_strategy": "requester_manager",
                        "escalation_hours": 24,
                    }
                ]
            },
        }

        response = client.post("/api/v1/workflow-definitions", json=body)

        assert response.status_code == 422

    def test_missing_strategy_field_is_422(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)
        body = {
            "request_type": "expense_reimbursement",
            "definition": {
                "stages": [
                    {
                        "order": 1,
                        "name": "Bad stage",
                        "assignment_strategy": "specific_user",
                        "escalation_hours": 24,
                    }
                ]
            },
        }

        response = client.post("/api/v1/workflow-definitions", json=body)

        assert response.status_code == 422


class TestUpdateDraft:
    def test_admin_can_update_own_draft(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)
        created = client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY).json()["data"]

        updated_body = {
            "definition": {
                "stages": [
                    {
                        "order": 1,
                        "name": "Manager Review (updated)",
                        "assignment_strategy": "department_queue",
                        "assigned_role": "approver",
                        "department": "sales",
                        "escalation_hours": 12,
                    }
                ]
            }
        }
        response = client.patch(f"/api/v1/workflow-definitions/{created['id']}", json=updated_body)

        assert response.status_code == 200
        assert (
            response.json()["data"]["definition"]["stages"][0]["name"] == "Manager Review (updated)"
        )

    def test_employee_is_forbidden(self, env, admin, employee):
        _, admin_identity = admin
        _, employee_identity = employee
        admin_client = _build_client(env, admin_identity)
        created = admin_client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY).json()[
            "data"
        ]

        employee_client = _build_client(env, employee_identity)
        response = employee_client.patch(
            f"/api/v1/workflow-definitions/{created['id']}",
            json={"definition": _ONE_STAGE_BODY["definition"]},
        )

        assert response.status_code == 403

    def test_editing_active_definition_is_rejected(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)
        created = client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY).json()["data"]
        client.post(f"/api/v1/workflow-definitions/{created['id']}/activate")

        response = client.patch(
            f"/api/v1/workflow-definitions/{created['id']}", json=_ONE_STAGE_BODY
        )

        assert response.status_code in (400, 409, 422)


class TestActivate:
    def test_admin_can_activate(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)
        created = client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY).json()["data"]

        response = client.post(f"/api/v1/workflow-definitions/{created['id']}/activate")

        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is True

    def test_activating_twice_conflicts(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)
        created = client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY).json()["data"]
        client.post(f"/api/v1/workflow-definitions/{created['id']}/activate")

        response = client.post(f"/api/v1/workflow-definitions/{created['id']}/activate")

        assert response.status_code == 409

    def test_activating_new_version_deactivates_previous(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)
        v1 = client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY).json()["data"]
        client.post(f"/api/v1/workflow-definitions/{v1['id']}/activate")
        v2 = client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY).json()["data"]

        client.post(f"/api/v1/workflow-definitions/{v2['id']}/activate")

        listing = client.get(
            "/api/v1/workflow-definitions", params={"request_type": "expense_reimbursement"}
        ).json()["data"]
        active_versions = [d["version"] for d in listing if d["is_active"]]
        assert active_versions == [v2["version"]]

    def test_employee_is_forbidden(self, env, admin, employee):
        _, admin_identity = admin
        _, employee_identity = employee
        admin_client = _build_client(env, admin_identity)
        created = admin_client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY).json()[
            "data"
        ]

        employee_client = _build_client(env, employee_identity)
        response = employee_client.post(f"/api/v1/workflow-definitions/{created['id']}/activate")

        assert response.status_code == 403


class TestList:
    def test_requires_request_type_or_query_text(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/workflow-definitions")

        assert response.status_code == 422

    def test_admin_sees_drafts_and_active(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)
        client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY)

        response = client.get(
            "/api/v1/workflow-definitions", params={"request_type": "expense_reimbursement"}
        )

        assert response.status_code == 200
        assert len(response.json()["data"]) == 1

    def test_employee_sees_only_active(self, env, admin, employee):
        _, admin_identity = admin
        _, employee_identity = employee
        admin_client = _build_client(env, admin_identity)
        admin_client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY)

        employee_client = _build_client(env, employee_identity)
        response = employee_client.get(
            "/api/v1/workflow-definitions", params={"request_type": "expense_reimbursement"}
        )

        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_search_by_partial_request_type(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)
        client.post("/api/v1/workflow-definitions", json=_ONE_STAGE_BODY)

        response = client.get("/api/v1/workflow-definitions", params={"query_text": "expense"})

        assert response.status_code == 200
        assert any(d["request_type"] == "expense_reimbursement" for d in response.json()["data"])
