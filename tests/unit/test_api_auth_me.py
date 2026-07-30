"""Tests for ``GET /api/v1/auth/me``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
from app.models.enums import UserRole
from tests.fixtures.fakes import FakeProfileRepository


class _FakeTokenVerifier:
    """A stand-in ``ClaimsResolver``: no real Supabase network call.

    Maps a small set of known test tokens to claims, and raises
    ``InvalidTokenError`` for anything else — exactly what
    ``app.auth.supabase_verifier.SupabaseTokenVerifier`` does for a
    token the real Supabase project rejects.
    """

    def __init__(self, claims_by_token: Mapping[str, Mapping[str, Any]]) -> None:
        self._claims_by_token = claims_by_token

    def resolve_claims(self, token: str) -> Mapping[str, Any]:
        try:
            return self._claims_by_token[token]
        except KeyError:
            raise InvalidTokenError("Unknown test token.") from None


def _build_app(profile_repo: FakeProfileRepository, token_verifier: _FakeTokenVerifier) -> FastAPI:
    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            profile_repo=profile_repo,
            token_verifier=token_verifier,
            scheduler_stats=None,
        )

    return create_app(resources_factory=_factory)


@pytest.fixture
def profile_repo() -> FakeProfileRepository:
    return FakeProfileRepository()


def test_auth_me_returns_the_profile_for_a_valid_token(profile_repo: FakeProfileRepository) -> None:
    profile = profile_repo.create_profile(
        profile_id=uuid4(), full_name="Jane Doe", role=UserRole.EMPLOYEE, department="Finance"
    )
    verifier = _FakeTokenVerifier(
        {
            "valid-token": {
                "sub": str(profile.id),
                "email": "jane@example.com",
                "role": profile.role.value,
                "company_id": str(profile.company_id),
                "is_platform_admin": profile.is_platform_admin,
            }
        }
    )
    app = _build_app(profile_repo, verifier)

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer valid-token"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["id"] == str(profile.id)
    assert body["data"]["full_name"] == "Jane Doe"
    assert body["data"]["role"] == "employee"
    assert body["data"]["department"] == "Finance"
    assert "request_id" in body["meta"]


def test_auth_me_without_a_token_is_rejected(profile_repo: FakeProfileRepository) -> None:
    app = _build_app(profile_repo, _FakeTokenVerifier({}))

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_auth_me_with_an_invalid_or_expired_token_is_rejected(
    profile_repo: FakeProfileRepository,
) -> None:
    app = _build_app(profile_repo, _FakeTokenVerifier({}))

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_auth_me_with_a_malformed_header_is_rejected(profile_repo: FakeProfileRepository) -> None:
    app = _build_app(profile_repo, _FakeTokenVerifier({}))

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me", headers={"Authorization": "not-bearer-shaped"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
