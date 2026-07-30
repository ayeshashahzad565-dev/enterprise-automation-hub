"""Tests for the ``/api/v1/admin/dashboard`` route: a composition over
several already-tested services/repositories, exercised here end-to-end
against the real ``env`` fixture's fakes.
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
            profile_repo=env.profile_repo,
            audit_repo=env.audit_repo,
            approval_service=env.approval_service,
            workflow_definition_service=env.workflow_definition_service,
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


def test_admin_sees_composed_dashboard(env, admin, employee, approver):
    _, admin_identity = admin
    client = _build_client(env, admin_identity)

    response = client.get("/api/v1/admin/dashboard")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_users"] == 3
    assert data["department_count"] >= 1
    assert data["pending_approvals_count"] == 0
    assert data["workflow_definition_counts"]["expense_reimbursement"] == 0
    assert data["recent_activity"] == []


def test_employee_is_forbidden(env, employee):
    _, employee_identity = employee
    client = _build_client(env, employee_identity)

    response = client.get("/api/v1/admin/dashboard")

    assert response.status_code == 403
