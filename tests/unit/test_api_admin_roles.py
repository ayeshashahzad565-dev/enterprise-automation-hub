"""Tests for the ``/api/v1/admin/roles`` route: a read-only rendering of
``app.auth.permissions.ROLE_PERMISSIONS``.
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


def _build_client(identity: AuthenticatedIdentity) -> TestClient:
    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


def test_admin_sees_all_three_roles(admin):
    _, admin_identity = admin
    client = _build_client(admin_identity)

    response = client.get("/api/v1/admin/roles")

    assert response.status_code == 200
    roles = {row["role"] for row in response.json()["data"]}
    assert roles == {"employee", "approver", "admin"}


def test_admin_permissions_superset_of_employee(admin):
    _, admin_identity = admin
    client = _build_client(admin_identity)

    response = client.get("/api/v1/admin/roles")

    data = {row["role"]: set(row["permissions"]) for row in response.json()["data"]}
    assert data["employee"].issubset(data["admin"])
    assert "manage_user_roles" in data["admin"]
    assert "manage_user_roles" not in data["employee"]


def test_employee_is_forbidden(employee):
    _, employee_identity = employee
    client = _build_client(employee_identity)

    response = client.get("/api/v1/admin/roles")

    assert response.status_code == 403
