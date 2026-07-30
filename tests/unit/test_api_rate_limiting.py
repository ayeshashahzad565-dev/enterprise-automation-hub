"""Tests for ``app.api.rate_limiting``'s per-authenticated-user limiters
(Milestone 13, High finding 3): ``enforce_rate_limit`` (method-aware
read/write split, applied router-wide in ``app.api.main``),
``enforce_upload_rate_limit``, and ``enforce_notification_poll_rate_limit``
(the two narrower, route-specific budgets).

``enforce_invitation_rate_limit`` (the pre-existing, per-IP limiter for
the two public invitation endpoints) already has its own coverage
elsewhere and is unaffected by this milestone's changes.
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
from app.api.rate_limiting import (
    enforce_notification_poll_rate_limit,
    enforce_rate_limit,
    enforce_upload_rate_limit,
)
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
from app.models.enums import UserRole
from app.utils.rate_limiter import InMemoryRateLimiter, RateLimitExceededError
from tests.fixtures.fakes import DEFAULT_TEST_COMPANY_ID, FakeProfileRepository

pytestmark = pytest.mark.unit


def _identity(user_id=None) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        user_id=user_id or uuid4(),
        email=None,
        role=UserRole.EMPLOYEE,
        company_id=DEFAULT_TEST_COMPANY_ID,
        is_platform_admin=False,
        expires_at=None,
        raw_claims={},
    )


def _resources(**limiters: InMemoryRateLimiter) -> ApplicationResources:
    return MagicMock(spec=ApplicationResources, **limiters)


class _FakeRequest:
    """A minimal stand-in for ``fastapi.Request`` — ``enforce_rate_limit``
    only ever reads ``.method``."""

    def __init__(self, method: str) -> None:
        self.method = method


class TestEnforceRateLimitDependency:
    def test_read_requests_consume_the_read_bucket(self):
        read_limiter = InMemoryRateLimiter(limit=1, window_seconds=60.0)
        write_limiter = InMemoryRateLimiter(limit=100, window_seconds=60.0)
        resources = _resources(read_rate_limiter=read_limiter, write_rate_limiter=write_limiter)
        identity = _identity()

        enforce_rate_limit(_FakeRequest("GET"), identity, resources)  # first hit: ok

        with pytest.raises(RateLimitExceededError):
            enforce_rate_limit(_FakeRequest("GET"), identity, resources)

    def test_write_requests_consume_a_separate_bucket_from_reads(self):
        read_limiter = InMemoryRateLimiter(limit=0, window_seconds=60.0)
        write_limiter = InMemoryRateLimiter(limit=1, window_seconds=60.0)
        resources = _resources(read_rate_limiter=read_limiter, write_rate_limiter=write_limiter)
        identity = _identity()

        # The read bucket is already exhausted (limit=0) but a POST must
        # not be affected by it — proving the method-aware split actually
        # routes to independent limiters, not a single shared one.
        enforce_rate_limit(_FakeRequest("POST"), identity, resources)

        with pytest.raises(RateLimitExceededError):
            enforce_rate_limit(_FakeRequest("POST"), identity, resources)

    @pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
    def test_every_non_get_method_uses_the_write_bucket(self, method):
        write_limiter = InMemoryRateLimiter(limit=1, window_seconds=60.0)
        resources = _resources(
            read_rate_limiter=InMemoryRateLimiter(limit=100, window_seconds=60.0),
            write_rate_limiter=write_limiter,
        )
        identity = _identity()

        enforce_rate_limit(_FakeRequest(method), identity, resources)

        with pytest.raises(RateLimitExceededError):
            enforce_rate_limit(_FakeRequest(method), identity, resources)

    def test_different_users_have_independent_buckets(self):
        read_limiter = InMemoryRateLimiter(limit=1, window_seconds=60.0)
        resources = _resources(
            read_rate_limiter=read_limiter,
            write_rate_limiter=InMemoryRateLimiter(limit=100, window_seconds=60.0),
        )
        first_user, second_user = _identity(), _identity()

        enforce_rate_limit(_FakeRequest("GET"), first_user, resources)

        # The second user's own first hit must still succeed — the bucket
        # is keyed per user, not shared globally.
        enforce_rate_limit(_FakeRequest("GET"), second_user, resources)


class TestRouteSpecificDependencies:
    def test_enforce_upload_rate_limit_is_independent_of_the_write_bucket(self):
        upload_limiter = InMemoryRateLimiter(limit=1, window_seconds=60.0)
        resources = _resources(upload_rate_limiter=upload_limiter)
        identity = _identity()

        enforce_upload_rate_limit(identity, resources)

        with pytest.raises(RateLimitExceededError):
            enforce_upload_rate_limit(identity, resources)

    def test_enforce_notification_poll_rate_limit_is_independent_of_the_read_bucket(self):
        poll_limiter = InMemoryRateLimiter(limit=1, window_seconds=60.0)
        resources = _resources(notification_poll_rate_limiter=poll_limiter)
        identity = _identity()

        enforce_notification_poll_rate_limit(identity, resources)

        with pytest.raises(RateLimitExceededError):
            enforce_notification_poll_rate_limit(identity, resources)


class _FakeTokenVerifier:
    def __init__(self, claims_by_token: Mapping[str, Mapping[str, Any]]) -> None:
        self._claims_by_token = claims_by_token

    def resolve_claims(self, token: str) -> Mapping[str, Any]:
        try:
            return self._claims_by_token[token]
        except KeyError:
            raise InvalidTokenError("Unknown test token.") from None


class TestEndToEndWiring:
    """Proves the dependency is actually attached to a real route — not
    just unit-testable in isolation — via ``GET /api/v1/auth/me``."""

    def test_a_read_route_returns_429_once_the_caller_s_read_budget_is_exhausted(self):
        profile_repo = FakeProfileRepository()
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

        def _factory() -> ApplicationResources:
            return MagicMock(
                spec=ApplicationResources,
                profile_repo=profile_repo,
                token_verifier=verifier,
                scheduler_stats=None,
                read_rate_limiter=InMemoryRateLimiter(limit=1, window_seconds=60.0),
                write_rate_limiter=InMemoryRateLimiter(limit=100, window_seconds=60.0),
            )

        app: FastAPI = create_app(resources_factory=_factory)

        with TestClient(app) as client:
            client.headers.update({"Authorization": "Bearer valid-token"})
            first = client.get("/api/v1/auth/me")
            second = client.get("/api/v1/auth/me")

        assert first.status_code == 200
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "RATE_LIMITED"
        assert "Retry-After" in second.headers
