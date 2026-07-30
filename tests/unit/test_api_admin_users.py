"""Tests for the ``/api/v1/admin/users*`` routes.

Every route is a thin wrapper over the real, unmodified
``ProfileRepository``/``AuditRepository`` (already wired on
``tests/conftest.py``'s ``env`` fixture) — no new fake repository was
needed.
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
            user_service=env.user_service,
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()  # runs the lifespan startup, so app.state.resources is populated
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


class TestList:
    def test_admin_can_list_by_role(self, env, admin, employee):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/admin/users", params={"role": "employee"})

        assert response.status_code == 200
        names = [u["full_name"] for u in response.json()["data"]]
        assert "Eve Employee" in names

    def test_admin_can_search_by_name(self, env, admin, employee):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/admin/users", params={"query": "Eve"})

        assert response.status_code == 200
        names = [u["full_name"] for u in response.json()["data"]]
        assert "Eve Employee" in names

    def test_requires_role_or_query(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/admin/users")

        assert response.status_code == 422

    def test_employee_is_forbidden(self, env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.get("/api/v1/admin/users", params={"role": "employee"})

        assert response.status_code == 403


class TestGet:
    def test_admin_can_get_user(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.get(f"/api/v1/admin/users/{employee_profile.id}")

        assert response.status_code == 200
        assert response.json()["data"]["full_name"] == "Eve Employee"

    def test_unknown_user_is_404(self, env, admin):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)
        from uuid import uuid4

        response = client.get(f"/api/v1/admin/users/{uuid4()}")

        assert response.status_code == 404


class TestUpdate:
    def test_admin_can_change_role_and_department(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.patch(
            f"/api/v1/admin/users/{employee_profile.id}",
            json={
                "expected_version": employee_profile.version,
                "role": "approver",
                "department": "engineering",
            },
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["role"] == "approver"
        assert data["department"] == "engineering"

    def test_stale_version_conflicts(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.patch(
            f"/api/v1/admin/users/{employee_profile.id}",
            json={"expected_version": employee_profile.version + 1, "role": "approver"},
        )

        assert response.status_code == 409

    def test_employee_is_forbidden(self, env, employee):
        employee_profile, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.patch(
            f"/api/v1/admin/users/{employee_profile.id}",
            json={"expected_version": employee_profile.version, "role": "admin"},
        )

        assert response.status_code == 403


class TestDeactivateReactivate:
    def test_admin_can_deactivate_a_user(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.patch(
            f"/api/v1/admin/users/{employee_profile.id}",
            json={"expected_version": employee_profile.version, "is_active": False},
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["is_active"] is False
        events = [e for e in env.audit_repo.list_for_actor(admin[0].id).items]
        assert any(e.action == "PROFILE_DEACTIVATED" for e in events)

    def test_admin_can_reactivate_a_user(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin
        client = _build_client(env, admin_identity)
        deactivated = client.patch(
            f"/api/v1/admin/users/{employee_profile.id}",
            json={"expected_version": employee_profile.version, "is_active": False},
        ).json()["data"]

        response = client.patch(
            f"/api/v1/admin/users/{employee_profile.id}",
            json={"expected_version": deactivated["version"], "is_active": True},
        )

        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is True

    def test_admin_cannot_deactivate_their_own_account(self, env, admin):
        admin_profile, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.patch(
            f"/api/v1/admin/users/{admin_profile.id}",
            json={"expected_version": admin_profile.version, "is_active": False},
        )

        assert response.status_code == 422

    def test_employee_is_forbidden(self, env, employee):
        employee_profile, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.patch(
            f"/api/v1/admin/users/{employee_profile.id}",
            json={"expected_version": employee_profile.version, "is_active": False},
        )

        assert response.status_code == 403


class TestErase:
    def test_admin_can_erase_a_user(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.delete(
            f"/api/v1/admin/users/{employee_profile.id}",
            params={"expected_version": employee_profile.version},
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["is_active"] is False
        assert data["deleted_at"] is not None
        assert data["deleted_by"] == str(admin[0].id)
        assert data["full_name"] != "Eve Employee"
        assert data["department"] is None
        assert len(env.auth_admin_client.anonymized_users) == 1
        assert env.auth_admin_client.anonymized_users[0].user_id == employee_profile.id

    def test_erasure_is_idempotent(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin
        client = _build_client(env, admin_identity)
        first = client.delete(
            f"/api/v1/admin/users/{employee_profile.id}",
            params={"expected_version": employee_profile.version},
        ).json()["data"]

        response = client.delete(
            f"/api/v1/admin/users/{employee_profile.id}",
            params={"expected_version": first["version"]},
        )

        assert response.status_code == 200
        assert len(env.auth_admin_client.anonymized_users) == 1, (
            "a replay must not scrub the auth email a second time"
        )

    def test_admin_cannot_erase_their_own_account(self, env, admin):
        admin_profile, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.delete(
            f"/api/v1/admin/users/{admin_profile.id}",
            params={"expected_version": admin_profile.version},
        )

        assert response.status_code == 422

    def test_employee_is_forbidden(self, env, employee):
        employee_profile, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.delete(
            f"/api/v1/admin/users/{employee_profile.id}",
            params={"expected_version": employee_profile.version},
        )

        assert response.status_code == 403

    def test_stale_version_conflicts(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.delete(
            f"/api/v1/admin/users/{employee_profile.id}",
            params={"expected_version": employee_profile.version + 1},
        )

        assert response.status_code == 409


class TestActivity:
    def test_admin_can_view_user_activity(self, env, admin, employee):
        employee_profile, employee_identity = employee
        _, admin_identity = admin
        env.audit_repo.record_event(action="REQUEST_CREATED", actor_id=employee_profile.id)
        client = _build_client(env, admin_identity)

        response = client.get(f"/api/v1/admin/users/{employee_profile.id}/activity")

        assert response.status_code == 200
        items = response.json()["data"]
        assert len(items) == 1
        assert items[0]["actor_name"] == "Eve Employee"

    def test_employee_is_forbidden(self, env, employee):
        employee_profile, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.get(f"/api/v1/admin/users/{employee_profile.id}/activity")

        assert response.status_code == 403
