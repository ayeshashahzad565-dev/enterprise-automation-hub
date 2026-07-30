"""Tests for the public, unauthenticated ``/api/v1/invitations/*`` routes
(Milestone 6).

Every route is a thin wrapper over a real, unmodified ``InvitationService``
— constructed here exactly the same way
``tests/unit/test_api_admin_invitations.py`` builds ``invitation_env``,
minus the ``Authorization`` header these two routes never require. See
``app.api.routers.public_invitations``'s module docstring for the
security rationale this file's ``TestIdenticalErrorResponses`` class
exists to verify.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
from app.services.invitation_service import InvitationService, hash_invitation_token
from app.utils.datetime_utils import utc_now
from app.utils.rate_limiter import InMemoryRateLimiter
from tests.fixtures.fakes import (
    FakeInvitationEmailSender,
    FakeInvitationRepository,
    FakeSupabaseAuthAdminClient,
)

pytestmark = pytest.mark.unit


class _FakeTokenVerifier:
    """Never actually called by these tests (no route here takes an
    ``Authorization`` header), but ``ApplicationResources`` requires a
    ``token_verifier`` attribute to exist for the app's lifespan to build
    cleanly, matching ``test_api_admin_invitations.py``'s identical stub.
    """

    def resolve_claims(self, token: str) -> Mapping[str, Any]:
        raise InvalidTokenError("No public-invitation test ever presents a bearer token.")


@dataclasses.dataclass
class PublicInvitationApiEnv:
    service: InvitationService
    invitation_repo: FakeInvitationRepository
    email_sender: FakeInvitationEmailSender
    auth_admin_client: FakeSupabaseAuthAdminClient


@pytest.fixture
def public_invitation_env(env) -> PublicInvitationApiEnv:
    invitation_repo = FakeInvitationRepository()
    email_sender = FakeInvitationEmailSender()
    auth_admin_client = FakeSupabaseAuthAdminClient(profile_repo=env.profile_repo)
    service = InvitationService(
        invitation_repo=invitation_repo,
        profile_repo=env.profile_repo,
        audit_repo=env.audit_repo,
        auth_admin_client=auth_admin_client,
        email_sender=email_sender,
    )
    return PublicInvitationApiEnv(
        service=service,
        invitation_repo=invitation_repo,
        email_sender=email_sender,
        auth_admin_client=auth_admin_client,
    )


def _build_client(
    env,
    invitation_service: InvitationService,
    *,
    invitation_rate_limiter: InMemoryRateLimiter | None = None,
) -> TestClient:
    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            profile_repo=env.profile_repo,
            audit_repo=env.audit_repo,
            invitation_service=invitation_service,
            token_verifier=_FakeTokenVerifier(),
            scheduler_stats=None,
            # A very high default limit so ordinary tests (a handful of
            # requests each) never trip it; TestRateLimiting below passes
            # its own tightly-configured limiter explicitly.
            invitation_rate_limiter=invitation_rate_limiter
            or InMemoryRateLimiter(limit=10_000, window_seconds=300.0),
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()  # runs the lifespan startup, so app.state.resources is populated
    return client


def _create_pending_invitation(pub_env: PublicInvitationApiEnv, admin_identity) -> tuple[str, Any]:
    """Create a fresh, acceptable invitation and return ``(raw_token, invitation)``."""
    invitation = pub_env.service.create_invitation(
        admin_identity, email="invitee@example.com", full_name="Ivy Invitee", department="sales"
    )
    raw_token = pub_env.email_sender.sent[-1].token
    return raw_token, invitation


def _create_invitation_with_hash(
    pub_env: PublicInvitationApiEnv, admin_identity, *, raw_token: str, **overrides: Any
) -> Any:
    """Insert an invitation directly via the fake repository, so a test
    can control its ``expires_at``/``status`` precisely (bypassing
    ``create_invitation``'s own "expiry hours from now" default) while
    still being resolvable via the public routes, which only ever look up
    by ``hash_invitation_token(raw_token)``.
    """
    kwargs: dict[str, Any] = {
        "email": "invitee@example.com",
        "full_name": "Ivy Invitee",
        "token_hash": hash_invitation_token(raw_token),
        "expires_at": utc_now() + timedelta(hours=1),
        "invited_by": admin_identity.user_id,
    }
    kwargs.update(overrides)
    return pub_env.invitation_repo.create_invitation(**kwargs)


class TestValidate:
    def test_valid_invitation_returns_the_expected_minimal_fields(
        self, env, admin, public_invitation_env
    ):
        _, admin_identity = admin
        raw_token, invitation = _create_pending_invitation(public_invitation_env, admin_identity)
        client = _build_client(env, public_invitation_env.service)

        response = client.get("/api/v1/invitations/validate", params={"token": raw_token})

        assert response.status_code == 200
        data = response.json()["data"]
        assert data == {
            "email": invitation.email,
            "full_name": invitation.full_name,
            "role": invitation.role.value,
            "department": invitation.department,
            "expires_at": data["expires_at"],
        }
        assert set(data.keys()) == {"email", "full_name", "role", "department", "expires_at"}

    def test_unknown_token_returns_the_generic_error(self, env, public_invitation_env):
        client = _build_client(env, public_invitation_env.service)

        response = client.get(
            "/api/v1/invitations/validate", params={"token": "no-such-token-exists"}
        )

        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "RESOURCE_NOT_FOUND"
        assert body["error"]["message"] == "This invitation link is invalid or has expired."

    def test_malformed_token_returns_the_generic_error(self, env, public_invitation_env):
        client = _build_client(env, public_invitation_env.service)

        response = client.get(
            "/api/v1/invitations/validate", params={"token": "!!! not a real token !!!"}
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_expired_token_returns_the_generic_error(self, env, admin, public_invitation_env):
        _, admin_identity = admin
        raw_token = "expired-raw-token"
        _create_invitation_with_hash(
            public_invitation_env,
            admin_identity,
            raw_token=raw_token,
            expires_at=utc_now() - timedelta(hours=1),
        )
        client = _build_client(env, public_invitation_env.service)

        response = client.get("/api/v1/invitations/validate", params={"token": raw_token})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_revoked_token_returns_the_generic_error(self, env, admin, public_invitation_env):
        _, admin_identity = admin
        raw_token, invitation = _create_pending_invitation(public_invitation_env, admin_identity)
        public_invitation_env.service.revoke_invitation(admin_identity, invitation.id)
        client = _build_client(env, public_invitation_env.service)

        response = client.get("/api/v1/invitations/validate", params={"token": raw_token})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_accepted_token_returns_the_generic_error(self, env, admin, public_invitation_env):
        _, admin_identity = admin
        raw_token, _ = _create_pending_invitation(public_invitation_env, admin_identity)
        public_invitation_env.service.accept_invitation(raw_token, password="Correct-Horse-2")
        client = _build_client(env, public_invitation_env.service)

        response = client.get("/api/v1/invitations/validate", params={"token": raw_token})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_missing_token_query_param_is_a_standard_validation_error(
        self, env, public_invitation_env
    ):
        client = _build_client(env, public_invitation_env.service)

        response = client.get("/api/v1/invitations/validate")

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestAccept:
    def test_successful_acceptance(self, env, admin, public_invitation_env):
        _, admin_identity = admin
        raw_token, invitation = _create_pending_invitation(public_invitation_env, admin_identity)
        client = _build_client(env, public_invitation_env.service)

        response = client.post(
            "/api/v1/invitations/accept", json={"token": raw_token, "password": "Correct-Horse-2"}
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data == {"email": invitation.email, "full_name": invitation.full_name}
        # The Supabase Admin API was actually called with the submitted password.
        created = public_invitation_env.auth_admin_client.created_users[0]
        assert created.email == invitation.email
        assert created.password == "Correct-Horse-2"
        # The invitation itself is now accepted.
        stored = public_invitation_env.invitation_repo.get_by_id(invitation.id)
        assert stored.status.value == "accepted"
        assert stored.accepted_profile_id == created.user_id

    def test_duplicate_acceptance_returns_the_generic_error(
        self, env, admin, public_invitation_env
    ):
        _, admin_identity = admin
        raw_token, _ = _create_pending_invitation(public_invitation_env, admin_identity)
        client = _build_client(env, public_invitation_env.service)
        first = client.post(
            "/api/v1/invitations/accept", json={"token": raw_token, "password": "Correct-Horse-2"}
        )
        assert first.status_code == 200

        second = client.post(
            "/api/v1/invitations/accept", json={"token": raw_token, "password": "Different-2"}
        )

        assert second.status_code == 404
        assert second.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_revoked_invitation_returns_the_generic_error(self, env, admin, public_invitation_env):
        _, admin_identity = admin
        raw_token, invitation = _create_pending_invitation(public_invitation_env, admin_identity)
        public_invitation_env.service.revoke_invitation(admin_identity, invitation.id)
        client = _build_client(env, public_invitation_env.service)

        response = client.post(
            "/api/v1/invitations/accept", json={"token": raw_token, "password": "Correct-Horse-2"}
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_expired_invitation_returns_the_generic_error(self, env, admin, public_invitation_env):
        _, admin_identity = admin
        raw_token = "expired-accept-token"
        _create_invitation_with_hash(
            public_invitation_env,
            admin_identity,
            raw_token=raw_token,
            expires_at=utc_now() - timedelta(hours=1),
        )
        client = _build_client(env, public_invitation_env.service)

        response = client.post(
            "/api/v1/invitations/accept", json={"token": raw_token, "password": "Correct-Horse-2"}
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_unknown_token_returns_the_generic_error(self, env, public_invitation_env):
        client = _build_client(env, public_invitation_env.service)

        response = client.post(
            "/api/v1/invitations/accept",
            json={"token": "no-such-token", "password": "Correct-Horse-2"},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_malformed_token_returns_the_generic_error(self, env, public_invitation_env):
        client = _build_client(env, public_invitation_env.service)

        response = client.post(
            "/api/v1/invitations/accept",
            json={"token": "!!! garbage !!!", "password": "Correct-Horse-2"},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_empty_password_is_a_standard_validation_error(self, env, admin, public_invitation_env):
        _, admin_identity = admin
        raw_token, _ = _create_pending_invitation(public_invitation_env, admin_identity)
        client = _build_client(env, public_invitation_env.service)

        response = client.post(
            "/api/v1/invitations/accept", json={"token": raw_token, "password": ""}
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        # Never forwarded to Supabase.
        assert public_invitation_env.auth_admin_client.created_users == []

    def test_missing_password_is_a_standard_validation_error(
        self, env, admin, public_invitation_env
    ):
        _, admin_identity = admin
        raw_token, _ = _create_pending_invitation(public_invitation_env, admin_identity)
        client = _build_client(env, public_invitation_env.service)

        response = client.post("/api/v1/invitations/accept", json={"token": raw_token})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_empty_token_is_a_standard_validation_error(self, env, public_invitation_env):
        client = _build_client(env, public_invitation_env.service)

        response = client.post(
            "/api/v1/invitations/accept", json={"token": "", "password": "Correct-Horse-2"}
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_supabase_failure_propagates_as_a_normal_server_error(
        self, env, admin, public_invitation_env
    ):
        _, admin_identity = admin
        raw_token, _ = _create_pending_invitation(public_invitation_env, admin_identity)
        failing_client = FakeSupabaseAuthAdminClient(raise_generic_error=True)
        service = InvitationService(
            invitation_repo=public_invitation_env.invitation_repo,
            profile_repo=env.profile_repo,
            audit_repo=env.audit_repo,
            auth_admin_client=failing_client,
            email_sender=public_invitation_env.email_sender,
        )
        client = _build_client(env, service)

        response = client.post(
            "/api/v1/invitations/accept", json={"token": raw_token, "password": "Correct-Horse-2"}
        )

        # Not the generic invitation-invalid response: a real infrastructure
        # failure gets a real server-error status, distinct from "bad token".
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"

    def test_optimistic_locking_race_returns_409_not_the_generic_error(
        self, env, admin, public_invitation_env, monkeypatch
    ):
        _, admin_identity = admin
        raw_token, invitation = _create_pending_invitation(public_invitation_env, admin_identity)
        real_record = public_invitation_env.invitation_repo.find_by_token_hash(
            hash_invitation_token(raw_token)
        )
        stale_record = dataclasses.replace(real_record, version=real_record.version + 1)
        monkeypatch.setattr(
            public_invitation_env.invitation_repo,
            "find_by_token_hash",
            lambda token_hash: stale_record,
        )
        client = _build_client(env, public_invitation_env.service)

        response = client.post(
            "/api/v1/invitations/accept", json={"token": raw_token, "password": "Correct-Horse-2"}
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONCURRENT_UPDATE"


class TestIdenticalErrorResponses:
    """Direct, side-by-side assertions that every invalid-token scenario
    produces byte-identical status/code/message — the core security
    requirement this milestone exists to satisfy.
    """

    def test_validate_error_bodies_are_identical_across_every_invalid_state(
        self, env, admin, public_invitation_env
    ):
        _, admin_identity = admin
        client = _build_client(env, public_invitation_env.service)

        unknown = client.get("/api/v1/invitations/validate", params={"token": "totally-unknown"})

        raw_expired = "expired-identical-token"
        _create_invitation_with_hash(
            public_invitation_env,
            admin_identity,
            raw_token=raw_expired,
            email="expired@example.com",
            expires_at=utc_now() - timedelta(hours=1),
        )
        expired = client.get("/api/v1/invitations/validate", params={"token": raw_expired})

        raw_revoked, revoked_invitation = _create_pending_invitation(
            public_invitation_env, admin_identity
        )
        public_invitation_env.service.revoke_invitation(admin_identity, revoked_invitation.id)
        revoked = client.get("/api/v1/invitations/validate", params={"token": raw_revoked})

        raw_accepted, _ = _create_pending_invitation(public_invitation_env, admin_identity)
        public_invitation_env.service.accept_invitation(raw_accepted, password="Correct-Horse-2")
        accepted = client.get("/api/v1/invitations/validate", params={"token": raw_accepted})

        malformed = client.get(
            "/api/v1/invitations/validate", params={"token": "!!! malformed !!!"}
        )

        responses = [unknown, expired, revoked, accepted, malformed]
        for response in responses:
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
            assert (
                response.json()["error"]["message"]
                == "This invitation link is invalid or has expired."
            )

    def test_accept_error_bodies_are_identical_across_every_invalid_state(
        self, env, admin, public_invitation_env
    ):
        _, admin_identity = admin
        client = _build_client(env, public_invitation_env.service)

        def _accept(token: str):
            return client.post(
                "/api/v1/invitations/accept",
                json={"token": token, "password": "Correct-Horse-2"},
            )

        unknown = _accept("totally-unknown")

        raw_expired = "expired-identical-accept-token"
        _create_invitation_with_hash(
            public_invitation_env,
            admin_identity,
            raw_token=raw_expired,
            email="expired2@example.com",
            expires_at=utc_now() - timedelta(hours=1),
        )
        expired = _accept(raw_expired)

        raw_revoked, revoked_invitation = _create_pending_invitation(
            public_invitation_env, admin_identity
        )
        public_invitation_env.service.revoke_invitation(admin_identity, revoked_invitation.id)
        revoked = _accept(raw_revoked)

        raw_accepted, _ = _create_pending_invitation(public_invitation_env, admin_identity)
        public_invitation_env.service.accept_invitation(raw_accepted, password="Correct-Horse-2")
        already_accepted = _accept(raw_accepted)

        malformed = _accept("!!! malformed !!!")

        responses = [unknown, expired, revoked, already_accepted, malformed]
        for response in responses:
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
            assert (
                response.json()["error"]["message"]
                == "This invitation link is invalid or has expired."
            )


class TestRateLimiting:
    """Milestone 9: the first rate limit actually enforced anywhere in
    this codebase, scoped to exactly these two public routes."""

    def test_exceeding_the_limit_returns_429_with_the_standard_envelope(
        self, env, public_invitation_env
    ):
        limiter = InMemoryRateLimiter(limit=2, window_seconds=300.0)
        client = _build_client(env, public_invitation_env.service, invitation_rate_limiter=limiter)

        first = client.get("/api/v1/invitations/validate", params={"token": "x"})
        second = client.get("/api/v1/invitations/validate", params={"token": "x"})
        third = client.get("/api/v1/invitations/validate", params={"token": "x"})

        assert first.status_code == 404  # unknown token - consumed one slot, not itself limited
        assert second.status_code == 404
        assert third.status_code == 429
        body = third.json()
        assert body["error"]["code"] == "RATE_LIMITED"
        assert "meta" in body
        assert "Retry-After" in third.headers
        assert int(third.headers["Retry-After"]) >= 1

    def test_the_budget_is_shared_across_validate_and_accept(self, env, public_invitation_env):
        limiter = InMemoryRateLimiter(limit=1, window_seconds=300.0)
        client = _build_client(env, public_invitation_env.service, invitation_rate_limiter=limiter)

        first = client.get("/api/v1/invitations/validate", params={"token": "x"})
        second = client.post(
            "/api/v1/invitations/accept", json={"token": "x", "password": "Correct-Horse-2"}
        )

        assert first.status_code == 404
        assert second.status_code == 429

    def test_requests_under_the_limit_are_unaffected(self, env, admin, public_invitation_env):
        _, admin_identity = admin
        limiter = InMemoryRateLimiter(limit=5, window_seconds=300.0)
        raw_token, invitation = _create_pending_invitation(public_invitation_env, admin_identity)
        client = _build_client(env, public_invitation_env.service, invitation_rate_limiter=limiter)

        response = client.get("/api/v1/invitations/validate", params={"token": raw_token})

        assert response.status_code == 200
        assert response.json()["data"]["email"] == invitation.email
