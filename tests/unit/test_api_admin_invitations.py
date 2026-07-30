"""Tests for the ``/api/v1/admin/invitations*`` routes (Milestone 5).

Every route is a thin wrapper over a real, unmodified ``InvitationService``
— constructed here against the same in-memory fake repositories/collaborators
``tests/unit/test_invitation_service.py`` already uses, plus the shared
``env``/``admin``/``employee`` fixtures from ``tests/conftest.py`` for
identity and cross-service consistency (``profile_repo``/``audit_repo``),
following ``test_api_admin_users.py``'s exact
``MagicMock(spec=ApplicationResources, ...)`` + ``create_app(resources_factory=...)``
convention.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
from app.services.invitation_service import InvitationService
from app.utils.datetime_utils import utc_now
from app.utils.rate_limiter import InMemoryRateLimiter
from tests.fixtures.fakes import (
    FakeInvitationEmailSender,
    FakeInvitationRepository,
    FakeSupabaseAuthAdminClient,
)

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


@dataclasses.dataclass
class InvitationApiEnv:
    """The invitation-specific collaborators this test module needs,
    layered on top of the shared ``env`` fixture's ``profile_repo``/
    ``audit_repo`` — mirrors ``tests/unit/test_invitation_service.py``'s
    own local ``InvitationEnv``, kept local to this file rather than
    added to the shared ``tests/conftest.py`` fixture, since no other
    test module needs it.
    """

    service: InvitationService
    invitation_repo: FakeInvitationRepository
    email_sender: FakeInvitationEmailSender


@pytest.fixture
def invitation_env(env) -> InvitationApiEnv:
    invitation_repo = FakeInvitationRepository()
    email_sender = FakeInvitationEmailSender()
    service = InvitationService(
        invitation_repo=invitation_repo,
        profile_repo=env.profile_repo,
        audit_repo=env.audit_repo,
        auth_admin_client=FakeSupabaseAuthAdminClient(profile_repo=env.profile_repo),
        email_sender=email_sender,
    )
    return InvitationApiEnv(
        service=service, invitation_repo=invitation_repo, email_sender=email_sender
    )


def _build_client(
    env,
    identity: AuthenticatedIdentity,
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
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
            invitation_rate_limiter=invitation_rate_limiter
            or InMemoryRateLimiter(limit=10_000, window_seconds=300.0),
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()  # runs the lifespan startup, so app.state.resources is populated
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


class TestCreate:
    def test_admin_can_create_an_invitation(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(
            "/api/v1/admin/invitations",
            json={"email": "new.hire@example.com", "full_name": "New Hire", "role": "employee"},
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["email"] == "new.hire@example.com"
        assert data["full_name"] == "New Hire"
        assert data["effective_status"] == "pending"
        assert data["resend_count"] == 0
        assert data["invited_by"] == str(admin_identity.user_id)

    def test_response_never_exposes_version_or_token_hash(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(
            "/api/v1/admin/invitations", json={"email": "a@example.com", "full_name": "Ada"}
        )

        data = response.json()["data"]
        assert "version" not in data
        assert "token_hash" not in data
        assert "token" not in data

    def test_duplicate_pending_invitation_is_rejected(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)
        body = {"email": "dup@example.com", "full_name": "Dup Person"}
        first = client.post("/api/v1/admin/invitations", json=body)
        assert first.status_code == 201

        second = client.post("/api/v1/admin/invitations", json=body)

        assert second.status_code == 422
        assert second.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_malformed_email_is_rejected_before_reaching_the_service(
        self, env, admin, invitation_env
    ):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(
            "/api/v1/admin/invitations",
            json={"email": "not-an-email", "full_name": "Someone"},
        )

        assert response.status_code == 422
        # Never created: the fake repository stays empty.
        assert invitation_env.invitation_repo.list_invitations().total_records == 0

    def test_empty_full_name_is_rejected(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(
            "/api/v1/admin/invitations", json={"email": "a@example.com", "full_name": ""}
        )

        assert response.status_code == 422

    def test_overlong_full_name_is_rejected(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(
            "/api/v1/admin/invitations",
            json={"email": "a@example.com", "full_name": "x" * 201},
        )

        assert response.status_code == 422

    def test_invalid_role_is_rejected(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(
            "/api/v1/admin/invitations",
            json={"email": "a@example.com", "full_name": "Ada", "role": "superuser"},
        )

        assert response.status_code == 422

    def test_employee_is_forbidden(self, env, employee, invitation_env):
        _, employee_identity = employee
        client = _build_client(env, employee_identity, invitation_env.service)

        response = client.post(
            "/api/v1/admin/invitations", json={"email": "a@example.com", "full_name": "Ada"}
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    def test_unauthenticated_request_is_rejected(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)
        del client.headers["Authorization"]

        response = client.post(
            "/api/v1/admin/invitations", json={"email": "a@example.com", "full_name": "Ada"}
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


class TestList:
    def test_admin_can_list_invitations(self, env, admin, invitation_env):
        _, admin_identity = admin
        invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="Ada"
        )
        invitation_env.service.create_invitation(
            admin_identity, email="b@example.com", full_name="Bea"
        )
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.get("/api/v1/admin/invitations")

        assert response.status_code == 200
        emails = [item["email"] for item in response.json()["data"]]
        assert {"a@example.com", "b@example.com"} == set(emails)

    def test_pagination(self, env, admin, invitation_env):
        _, admin_identity = admin
        for i in range(3):
            invitation_env.service.create_invitation(
                admin_identity, email=f"user{i}@example.com", full_name=f"User {i}"
            )
        client = _build_client(env, admin_identity, invitation_env.service)

        first_page = client.get("/api/v1/admin/invitations", params={"page": 1, "page_size": 2})
        second_page = client.get("/api/v1/admin/invitations", params={"page": 2, "page_size": 2})

        assert len(first_page.json()["data"]) == 2
        assert len(second_page.json()["data"]) == 1
        pagination = first_page.json()["pagination"]
        assert pagination["total_records"] == 3
        assert pagination["total_pages"] == 2

    def test_pagination_is_correct_when_filtering_by_expired_status(
        self, env, admin, invitation_env
    ):
        _, admin_identity = admin
        invitation_env.service.create_invitation(
            admin_identity, email="fresh@example.com", full_name="Fresh"
        )
        for i in range(3):
            invitation_env.invitation_repo.create_invitation(
                email=f"stale{i}@example.com",
                full_name=f"Stale {i}",
                token_hash=f"stale-hash-{i}",
                expires_at=utc_now() - timedelta(hours=1),
                invited_by=admin_identity.user_id,
            )
        client = _build_client(env, admin_identity, invitation_env.service)

        first_page = client.get(
            "/api/v1/admin/invitations", params={"status": "expired", "page": 1, "page_size": 2}
        )
        second_page = client.get(
            "/api/v1/admin/invitations", params={"status": "expired", "page": 2, "page_size": 2}
        )

        assert first_page.json()["pagination"]["total_records"] == 3
        assert len(first_page.json()["data"]) == 2
        assert len(second_page.json()["data"]) == 1

    def test_search_by_full_name_or_email(self, env, admin, invitation_env):
        _, admin_identity = admin
        invitation_env.service.create_invitation(
            admin_identity, email="grace.hopper@example.com", full_name="Grace Hopper"
        )
        invitation_env.service.create_invitation(
            admin_identity, email="ada.lovelace@example.com", full_name="Ada Lovelace"
        )
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.get("/api/v1/admin/invitations", params={"query": "hopper"})

        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["full_name"] == "Grace Hopper"

    def test_status_filter(self, env, admin, invitation_env):
        _, admin_identity = admin
        keep = invitation_env.service.create_invitation(
            admin_identity, email="keep@example.com", full_name="Keep Pending"
        )
        to_revoke = invitation_env.service.create_invitation(
            admin_identity, email="revoke@example.com", full_name="Revoke Me"
        )
        invitation_env.service.revoke_invitation(admin_identity, to_revoke.id)
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.get("/api/v1/admin/invitations", params={"status": "revoked"})

        data = response.json()["data"]
        emails = [item["email"] for item in data]
        assert emails == ["revoke@example.com"]
        assert keep.email not in emails

    def test_invalid_status_filter_is_rejected(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.get("/api/v1/admin/invitations", params={"status": "not-a-status"})

        assert response.status_code == 422

    def test_invalid_page_size_is_rejected(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.get("/api/v1/admin/invitations", params={"page_size": 0})

        assert response.status_code == 422

    def test_employee_is_forbidden(self, env, employee, invitation_env):
        _, employee_identity = employee
        client = _build_client(env, employee_identity, invitation_env.service)

        response = client.get("/api/v1/admin/invitations")

        assert response.status_code == 403


class TestGet:
    def test_admin_can_get_an_invitation(self, env, admin, invitation_env):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="Ada"
        )
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.get(f"/api/v1/admin/invitations/{created.id}")

        assert response.status_code == 200
        assert response.json()["data"]["email"] == "a@example.com"

    def test_unknown_invitation_is_404(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.get(f"/api/v1/admin/invitations/{uuid4()}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_employee_is_forbidden(self, env, admin, employee, invitation_env):
        _, admin_identity = admin
        _, employee_identity = employee
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="Ada"
        )
        client = _build_client(env, employee_identity, invitation_env.service)

        response = client.get(f"/api/v1/admin/invitations/{created.id}")

        assert response.status_code == 403


class TestResend:
    def test_admin_can_resend_an_invitation(self, env, admin, invitation_env):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="Ada"
        )
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(f"/api/v1/admin/invitations/{created.id}/resend")

        assert response.status_code == 200
        assert response.json()["data"]["resend_count"] == 1
        assert len(invitation_env.email_sender.sent) == 2  # initial create + resend

    def test_resend_on_accepted_invitation_is_rejected(self, env, admin, invitation_env):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="Ada"
        )
        raw_token = invitation_env.email_sender.sent[-1].token
        invitation_env.service.accept_invitation(raw_token, password="Correct-Horse-Battery-2")
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(f"/api/v1/admin/invitations/{created.id}/resend")

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_resend_unknown_invitation_is_404(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(f"/api/v1/admin/invitations/{uuid4()}/resend")

        assert response.status_code == 404

    def test_employee_is_forbidden(self, env, admin, employee, invitation_env):
        _, admin_identity = admin
        _, employee_identity = employee
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="Ada"
        )
        client = _build_client(env, employee_identity, invitation_env.service)

        response = client.post(f"/api/v1/admin/invitations/{created.id}/resend")

        assert response.status_code == 403

    def test_concurrent_resend_conflict_returns_409(self, env, admin, invitation_env, monkeypatch):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="race@example.com", full_name="Race Condition"
        )
        real_record = invitation_env.invitation_repo.get_by_id(created.id)
        stale_record = dataclasses.replace(real_record, version=real_record.version + 1)
        monkeypatch.setattr(
            invitation_env.invitation_repo, "get_by_id", lambda invitation_id: stale_record
        )
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(f"/api/v1/admin/invitations/{created.id}/resend")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONCURRENT_UPDATE"


class TestRevoke:
    def test_admin_can_revoke_an_invitation(self, env, admin, invitation_env):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="Ada"
        )
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(f"/api/v1/admin/invitations/{created.id}/revoke")

        assert response.status_code == 200
        assert response.json()["data"]["effective_status"] == "revoked"
        assert response.json()["data"]["revoked_at"] is not None

    def test_revoke_an_already_revoked_invitation_is_rejected(self, env, admin, invitation_env):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="Ada"
        )
        invitation_env.service.revoke_invitation(admin_identity, created.id)
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(f"/api/v1/admin/invitations/{created.id}/revoke")

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_revoke_unknown_invitation_is_404(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(f"/api/v1/admin/invitations/{uuid4()}/revoke")

        assert response.status_code == 404

    def test_employee_is_forbidden(self, env, admin, employee, invitation_env):
        _, admin_identity = admin
        _, employee_identity = employee
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="Ada"
        )
        client = _build_client(env, employee_identity, invitation_env.service)

        response = client.post(f"/api/v1/admin/invitations/{created.id}/revoke")

        assert response.status_code == 403

    def test_concurrent_revoke_conflict_returns_409(self, env, admin, invitation_env, monkeypatch):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="race2@example.com", full_name="Race Two"
        )
        real_record = invitation_env.invitation_repo.get_by_id(created.id)
        stale_record = dataclasses.replace(real_record, version=real_record.version + 1)
        monkeypatch.setattr(
            invitation_env.invitation_repo, "get_by_id", lambda invitation_id: stale_record
        )
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(f"/api/v1/admin/invitations/{created.id}/revoke")

        assert response.status_code == 409


class TestExceptionMapping:
    """Explicit, dedicated assertions that every ``InvitationService``
    exception this milestone's endpoints can raise maps to the expected
    HTTP status and ``error.code`` — the scenarios above already exercise
    each of these; this class asserts on the mapping itself in one place.
    """

    def test_not_found_maps_to_404_resource_not_found(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.get(f"/api/v1/admin/invitations/{uuid4()}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_permission_denied_maps_to_403(self, env, employee, invitation_env):
        _, employee_identity = employee
        client = _build_client(env, employee_identity, invitation_env.service)

        response = client.get("/api/v1/admin/invitations")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    def test_invitation_conflict_maps_to_422_validation_error(self, env, admin, invitation_env):
        _, admin_identity = admin
        client = _build_client(env, admin_identity, invitation_env.service)
        body = {"email": "conflict@example.com", "full_name": "Conflict"}
        client.post("/api/v1/admin/invitations", json=body)

        response = client.post("/api/v1/admin/invitations", json=body)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_invalid_state_transition_maps_to_422_validation_error(
        self, env, admin, invitation_env
    ):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="Ada"
        )
        invitation_env.service.revoke_invitation(admin_identity, created.id)
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(f"/api/v1/admin/invitations/{created.id}/resend")

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_concurrency_conflict_maps_to_409(self, env, admin, invitation_env, monkeypatch):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="conflict2@example.com", full_name="Conflict Two"
        )
        real_record = invitation_env.invitation_repo.get_by_id(created.id)
        stale_record = dataclasses.replace(real_record, version=real_record.version + 1)
        monkeypatch.setattr(
            invitation_env.invitation_repo, "get_by_id", lambda invitation_id: stale_record
        )
        client = _build_client(env, admin_identity, invitation_env.service)

        response = client.post(f"/api/v1/admin/invitations/{created.id}/revoke")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONCURRENT_UPDATE"


class TestAdminEndpointsAreNeverRateLimited:
    """Milestone 9's rate limiter (``app.api.rate_limiting``) is attached
    only to the public invitation router — never to this admin router.
    Proven here with the strictest possible limiter (``limit=0``, which
    blocks every request on any route it actually guards): every admin
    invitation request still succeeds, which is only possible if this
    router never calls ``enforce_invitation_rate_limit`` at all.
    """

    def test_create_is_unaffected_by_a_zero_limit(self, env, admin, invitation_env):
        _, admin_identity = admin
        blocking_limiter = InMemoryRateLimiter(limit=0, window_seconds=300.0)
        client = _build_client(
            env, admin_identity, invitation_env.service, invitation_rate_limiter=blocking_limiter
        )

        response = client.post(
            "/api/v1/admin/invitations", json={"email": "a@example.com", "full_name": "Ada"}
        )

        assert response.status_code == 201

    def test_list_is_unaffected_by_a_zero_limit(self, env, admin, invitation_env):
        _, admin_identity = admin
        blocking_limiter = InMemoryRateLimiter(limit=0, window_seconds=300.0)
        client = _build_client(
            env, admin_identity, invitation_env.service, invitation_rate_limiter=blocking_limiter
        )

        response = client.get("/api/v1/admin/invitations")

        assert response.status_code == 200
