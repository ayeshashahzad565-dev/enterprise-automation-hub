"""Tests for the ``/api/v1/requests/{id}/comments`` and
``/api/v1/comments/{id}`` routes.

See ``test_api_requests.py``'s module docstring — same real-service,
fake-repository wiring via the ``env`` fixture.
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


def _create_request(env: Env, employee_identity, approver_id, admin_identity) -> dict[str, Any]:
    created = env.workflow_definition_service.create_definition(
        admin_identity,
        request_type="expense_reimbursement",
        definition={"stages": [specific_user_stage(1, "Manager Review", user_id=approver_id)]},
    )
    env.workflow_definition_service.activate_version(admin_identity, created.id)
    client = _build_client(env, employee_identity)
    return client.post(
        "/api/v1/requests", json={"request_type": "expense_reimbursement", "title": "Team lunch"}
    ).json()["data"]


class TestComments:
    def test_add_and_list_comments(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        request = _create_request(env, employee_identity, approver_profile.id, admin_identity)
        client = _build_client(env, employee_identity)

        create_response = client.post(
            f"/api/v1/requests/{request['id']}/comments", json={"body": "Please see attached."}
        )
        assert create_response.status_code == 201
        assert create_response.json()["data"]["body"] == "Please see attached."

        list_response = client.get(f"/api/v1/requests/{request['id']}/comments")
        assert list_response.status_code == 200
        assert len(list_response.json()["data"]) == 1

    def test_reply_to_unknown_parent_returns_parent_comment_not_found(
        self, env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        request = _create_request(env, employee_identity, approver_profile.id, admin_identity)
        client = _build_client(env, employee_identity)

        response = client.post(
            f"/api/v1/requests/{request['id']}/comments",
            json={"body": "A reply", "parent_comment_id": "00000000-0000-0000-0000-000000000000"},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "PARENT_COMMENT_NOT_FOUND"

    def test_remove_comment_requires_admin(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        request = _create_request(env, employee_identity, approver_profile.id, admin_identity)
        employee_client = _build_client(env, employee_identity)
        comment = employee_client.post(
            f"/api/v1/requests/{request['id']}/comments", json={"body": "Hello"}
        ).json()["data"]

        forbidden_response = employee_client.delete(f"/api/v1/comments/{comment['id']}")
        assert forbidden_response.status_code == 403

        admin_client = _build_client(env, admin_identity)
        ok_response = admin_client.delete(f"/api/v1/comments/{comment['id']}")
        assert ok_response.status_code == 204
