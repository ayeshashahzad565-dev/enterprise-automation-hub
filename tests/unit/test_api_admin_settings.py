"""Tests for the ``/api/v1/admin/settings`` route.

Confirms the route is admin-only, read-only (no other verb registered),
and — most importantly — never serializes SMTP credentials or other
secret-shaped configuration, even though ``resources.settings`` (a real
``AppSettings``) carries them internally.
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

pytestmark = pytest.mark.unit

_TOKEN = "test-token"

_SECRET_SMTP_PASSWORD = "super-secret-smtp-password"

_TEST_ENV = {
    "APP_ENVIRONMENT": "development",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_ANON_KEY": "anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USERNAME": "smtp-user",
    "SMTP_PASSWORD": _SECRET_SMTP_PASSWORD,
    "SMTP_FROM_ADDRESS": "noreply@example.com",
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


def _build_client(identity: AuthenticatedIdentity) -> TestClient:
    settings = load_settings(env=_TEST_ENV)

    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            settings=settings,
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


def test_admin_can_view_settings(admin):
    _, admin_identity = admin
    client = _build_client(admin_identity)

    response = client.get("/api/v1/admin/settings")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["environment"] == "development"
    assert data["smtp_enabled"] is True


def test_smtp_credentials_never_leak(admin):
    _, admin_identity = admin
    client = _build_client(admin_identity)

    response = client.get("/api/v1/admin/settings")

    assert _SECRET_SMTP_PASSWORD not in response.text
    assert "smtp-user" not in response.text
    assert "smtp.example.com" not in response.text
    assert "postgresql://" not in response.text


def test_employee_is_forbidden(employee):
    _, employee_identity = employee
    client = _build_client(employee_identity)

    response = client.get("/api/v1/admin/settings")

    assert response.status_code == 403
