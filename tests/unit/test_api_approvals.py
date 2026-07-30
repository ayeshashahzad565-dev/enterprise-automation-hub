"""Tests for the ``/api/v1/approvals*`` routes and the
``/api/v1/requests/{id}/approval-eligibility`` slice.

Follows ``test_api_requests.py``'s established convention: the real
``ApprovalService``/``RequestService`` wired to the same in-memory fake
repositories the service-layer unit tests use (``tests/conftest.py``'s
``env`` fixture), exercised end-to-end through a real ``TestClient``.
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
            approval_service=env.approval_service,
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
        "/api/v1/requests", json={"request_type": "expense_reimbursement", "title": title}
    )
    assert response.status_code == 201
    return response.json()["data"]


class TestInbox:
    def test_list_inbox_returns_enriched_pending_stage(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        created = _create_request(employee_client, title="Client dinner")

        approver_client = _build_client(env, approver_identity)
        response = approver_client.get("/api/v1/approvals/inbox")

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1
        item = body["data"][0]
        assert item["request_id"] == created["id"]
        assert item["request_title"] == "Client dinner"
        assert item["stage_name"] == "Manager Review"
        assert item["stage_status"] == "pending"
        assert item["requester_id"] == created["requester_id"]

    def test_list_inbox_returns_403_for_employee(self, env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.get("/api/v1/approvals/inbox")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    def test_list_inbox_is_empty_for_unrelated_approver(
        self, env, employee, approver, second_approver, admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, second_approver_identity = second_approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        other_client = _build_client(env, second_approver_identity)
        response = other_client.get("/api/v1/approvals/inbox")

        assert response.status_code == 200
        assert response.json()["data"] == []


class TestDecisions:
    def test_approve_stage_completes_a_single_stage_request(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        approver_client = _build_client(env, approver_identity)
        inbox_item = approver_client.get("/api/v1/approvals/inbox").json()["data"][0]

        response = approver_client.post(
            f"/api/v1/approvals/{inbox_item['stage_id']}/approve",
            json={"expected_version": inbox_item["stage_version"]},
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["stage"]["status"] == "approved"
        assert data["request_status"] == "completed"
        assert data["current_stage_id"] is None

    def test_reject_stage_without_note_returns_422(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        approver_client = _build_client(env, approver_identity)
        inbox_item = approver_client.get("/api/v1/approvals/inbox").json()["data"][0]

        response = approver_client.post(
            f"/api/v1/approvals/{inbox_item['stage_id']}/reject",
            json={"expected_version": inbox_item["stage_version"]},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_reject_stage_with_note_terminates_the_request(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        approver_client = _build_client(env, approver_identity)
        inbox_item = approver_client.get("/api/v1/approvals/inbox").json()["data"][0]

        response = approver_client.post(
            f"/api/v1/approvals/{inbox_item['stage_id']}/reject",
            json={
                "expected_version": inbox_item["stage_version"],
                "decision_note": "Missing receipt.",
            },
        )

        assert response.status_code == 200
        assert response.json()["data"]["request_status"] == "rejected"

    def test_approve_stage_with_stale_version_returns_409(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        approver_client = _build_client(env, approver_identity)
        inbox_item = approver_client.get("/api/v1/approvals/inbox").json()["data"][0]

        response = approver_client.post(
            f"/api/v1/approvals/{inbox_item['stage_id']}/approve",
            json={"expected_version": inbox_item["stage_version"] + 5},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONCURRENT_UPDATE"

    def test_approve_stage_not_assigned_to_caller_returns_403(
        self, env, employee, approver, second_approver, admin
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, second_approver_identity = second_approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        owner_client = _build_client(env, approver_identity)
        inbox_item = owner_client.get("/api/v1/approvals/inbox").json()["data"][0]

        stranger_client = _build_client(env, second_approver_identity)
        response = stranger_client.post(
            f"/api/v1/approvals/{inbox_item['stage_id']}/approve",
            json={"expected_version": inbox_item["stage_version"]},
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"


class TestBulkDecisions:
    def test_bulk_approve_reports_per_item_success_and_failure(
        self, env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client, title="First")
        _create_request(employee_client, title="Second")

        approver_client = _build_client(env, approver_identity)
        inbox = approver_client.get("/api/v1/approvals/inbox").json()["data"]
        assert len(inbox) == 2

        response = approver_client.post(
            "/api/v1/approvals/bulk-approve",
            json={
                "items": [
                    {
                        "stage_id": inbox[0]["stage_id"],
                        "expected_version": inbox[0]["stage_version"],
                    },
                    {
                        "stage_id": inbox[1]["stage_id"],
                        "expected_version": inbox[1]["stage_version"] + 5,
                    },
                ]
            },
        )

        assert response.status_code == 200
        results = response.json()["data"]["results"]
        assert results[0]["success"] is True
        assert results[1]["success"] is False
        assert results[1]["error_code"] == "CONCURRENT_UPDATE"

    def test_bulk_reject_missing_note_reports_item_failure(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        _create_request(employee_client)

        approver_client = _build_client(env, approver_identity)
        inbox_item = approver_client.get("/api/v1/approvals/inbox").json()["data"][0]

        response = approver_client.post(
            "/api/v1/approvals/bulk-reject",
            json={
                "items": [
                    {
                        "stage_id": inbox_item["stage_id"],
                        "expected_version": inbox_item["stage_version"],
                    }
                ]
            },
        )

        assert response.status_code == 200
        results = response.json()["data"]["results"]
        assert results[0]["success"] is False
        assert results[0]["error_code"] == "VALIDATION_ERROR"


class TestEligibility:
    def test_eligible_true_for_assigned_approver(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        created = _create_request(employee_client)

        approver_client = _build_client(env, approver_identity)
        response = approver_client.get(f"/api/v1/requests/{created['id']}/approval-eligibility")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["eligible"] is True
        assert data["stage_id"] is not None

    def test_eligible_false_for_unrelated_approver(
        self, env, employee, approver, second_approver, admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, second_approver_identity = second_approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        created = _create_request(employee_client)

        other_client = _build_client(env, second_approver_identity)
        response = other_client.get(f"/api/v1/requests/{created['id']}/approval-eligibility")

        assert response.status_code == 200
        assert response.json()["data"]["eligible"] is False

    def test_eligible_false_for_employee(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        _make_single_stage_definition(env, admin_identity, approver_profile.id)
        employee_client = _build_client(env, employee_identity)
        created = _create_request(employee_client)

        response = employee_client.get(f"/api/v1/requests/{created['id']}/approval-eligibility")

        assert response.status_code == 200
        assert response.json()["data"]["eligible"] is False
