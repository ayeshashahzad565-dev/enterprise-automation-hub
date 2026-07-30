"""Tests for the ``/api/v1/platform/*`` routes: company management,
licenses, feature flags, platform stats, health, and the platform-wide
audit log.

Exercises the router against the real ``CompanyService``/
``FeatureFlagService`` (backed by ``tests/fixtures/fakes.py``, matching
``env``'s usual shape) for the service-backed endpoints, and a
``MagicMock(spec=ApplicationResources)`` for the router-direct endpoints
(stats/health/audit-log), mirroring ``test_api_admin_jobs.py``'s exact
pattern.
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
from tests.fixtures.fakes import FakePlatformStatsRepository

pytestmark = pytest.mark.unit

_TOKEN = "test-token"
_TEST_ENV = {
    "APP_ENVIRONMENT": "development",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_ANON_KEY": "anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
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


def _build_client(
    env,
    identity: AuthenticatedIdentity,
    *,
    platform_stats_repo: FakePlatformStatsRepository | None = None,
    job_repository: Any = None,
    database_client: Any = None,
) -> TestClient:
    settings = load_settings(env=_TEST_ENV)
    if job_repository is None:
        job_repository = MagicMock()
        job_repository.count_dead_letter_by_queue.return_value = {}
    if database_client is None:
        database_client = MagicMock()
        database_client.health_check.return_value = True

    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            settings=settings,
            token_verifier=_FakeTokenVerifier(identity),
            company_service=env.company_service,
            feature_flag_service=env.feature_flag_service,
            company_repo=env.company_repo,
            audit_repo=env.audit_repo,
            platform_stats_repo=platform_stats_repo or FakePlatformStatsRepository(),
            job_repository=job_repository,
            database_client=database_client,
            redis_client=None,
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


class TestPlatformAdminOnly:
    def test_a_non_platform_admin_is_forbidden_from_every_endpoint(self, env, employee):
        _, identity = employee
        client = _build_client(env, identity)

        assert client.get("/api/v1/platform/companies").status_code == 403
        assert client.post("/api/v1/platform/companies", json={"name": "Acme"}).status_code == 403
        assert client.get("/api/v1/platform/feature-flags").status_code == 403
        assert client.get("/api/v1/platform/stats").status_code == 403
        assert client.get("/api/v1/platform/health").status_code == 403
        assert client.get("/api/v1/platform/audit-log").status_code == 403


class TestCompanyCrud:
    def test_create_then_list_then_get(self, env, platform_admin):
        _, identity = platform_admin
        client = _build_client(env, identity)

        created = client.post("/api/v1/platform/companies", json={"name": "Acme Corp"})
        assert created.status_code == 201
        company_id = created.json()["data"]["id"]

        listed = client.get("/api/v1/platform/companies")
        assert listed.status_code == 200
        assert any(c["id"] == company_id for c in listed.json()["data"])

        detail = client.get(f"/api/v1/platform/companies/{company_id}")
        assert detail.status_code == 200
        assert detail.json()["data"]["name"] == "Acme Corp"

    def test_update_settings(self, env, platform_admin):
        _, identity = platform_admin
        client = _build_client(env, identity)
        created = client.post("/api/v1/platform/companies", json={"name": "Acme"}).json()["data"]

        response = client.patch(
            f"/api/v1/platform/companies/{created['id']}",
            json={"expected_version": created["version"], "contact_email": "ops@acme.test"},
        )

        assert response.status_code == 200
        assert response.json()["data"]["contact_email"] == "ops@acme.test"

    def test_suspend_then_reactivate(self, env, platform_admin):
        _, identity = platform_admin
        client = _build_client(env, identity)
        created = client.post("/api/v1/platform/companies", json={"name": "Acme"}).json()["data"]

        suspended = client.patch(
            f"/api/v1/platform/companies/{created['id']}",
            json={"expected_version": created["version"], "is_active": False},
        )
        assert suspended.status_code == 200
        assert suspended.json()["data"]["is_active"] is False

        reactivated = client.patch(
            f"/api/v1/platform/companies/{created['id']}",
            json={"expected_version": suspended.json()["data"]["version"], "is_active": True},
        )
        assert reactivated.status_code == 200
        assert reactivated.json()["data"]["is_active"] is True

    def test_delete_then_restore(self, env, platform_admin):
        _, identity = platform_admin
        client = _build_client(env, identity)
        created = client.post("/api/v1/platform/companies", json={"name": "Acme"}).json()["data"]

        deleted = client.delete(
            f"/api/v1/platform/companies/{created['id']}",
            params={"expected_version": created["version"]},
        )
        assert deleted.status_code == 200
        assert deleted.json()["data"]["is_deleted"] is True

        active_list = client.get("/api/v1/platform/companies")
        assert created["id"] not in [c["id"] for c in active_list.json()["data"]]

        restored = client.post(
            f"/api/v1/platform/companies/{created['id']}/restore",
            json={"expected_version": deleted.json()["data"]["version"]},
        )
        assert restored.status_code == 200
        assert restored.json()["data"]["is_deleted"] is False

    def test_platform_admin_cannot_suspend_their_own_company(self, env, platform_admin):
        _, identity = platform_admin
        own_company = env.company_repo.create_company(name="Own Co", slug="own-co")
        # Re-point the identity's own company to the freshly created one,
        # so the router's self-lockout guard has something to trip on.
        identity = AuthenticatedIdentity(
            user_id=identity.user_id,
            email=None,
            role=identity.role,
            company_id=own_company.id,
            is_platform_admin=True,
            expires_at=None,
            raw_claims={},
        )
        client = _build_client(env, identity)

        response = client.patch(
            f"/api/v1/platform/companies/{own_company.id}",
            json={"expected_version": own_company.version, "is_active": False},
        )

        assert response.status_code == 422


class TestLicense:
    def test_get_license_is_null_when_unconfigured(self, env, platform_admin):
        _, identity = platform_admin
        client = _build_client(env, identity)
        created = client.post("/api/v1/platform/companies", json={"name": "Acme"}).json()["data"]

        response = client.get(f"/api/v1/platform/companies/{created['id']}/license")

        assert response.status_code == 200
        assert response.json()["data"] is None

    def test_update_then_get_license(self, env, platform_admin):
        _, identity = platform_admin
        client = _build_client(env, identity)
        created = client.post("/api/v1/platform/companies", json={"name": "Acme"}).json()["data"]

        updated = client.patch(
            f"/api/v1/platform/companies/{created['id']}/license",
            json={"plan_tier": "pro", "seat_limit": 25},
        )

        assert updated.status_code == 200
        assert updated.json()["data"]["plan_tier"] == "pro"
        assert updated.json()["data"]["seat_limit"] == 25
        assert updated.json()["data"]["seats_used"] == 0

    def test_empty_patch_payload_is_rejected(self, env, platform_admin):
        _, identity = platform_admin
        client = _build_client(env, identity)
        created = client.post("/api/v1/platform/companies", json={"name": "Acme"}).json()["data"]

        response = client.patch(f"/api/v1/platform/companies/{created['id']}/license", json={})

        assert response.status_code == 422


class TestFeatureFlags:
    def test_create_list_update(self, env, platform_admin):
        _, identity = platform_admin
        client = _build_client(env, identity)

        created = client.post(
            "/api/v1/platform/feature-flags",
            json={"key": "new_dashboard", "description": "New dashboard layout"},
        )
        assert created.status_code == 201
        assert created.json()["data"]["enabled"] is False

        listed = client.get("/api/v1/platform/feature-flags")
        assert listed.status_code == 200
        assert any(f["key"] == "new_dashboard" for f in listed.json()["data"])

        updated = client.patch(
            "/api/v1/platform/feature-flags/new_dashboard", json={"enabled": True}
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["enabled"] is True


class TestPlatformStats:
    def test_reports_tenant_and_user_counts(self, env, platform_admin):
        _, identity = platform_admin
        stats_repo = FakePlatformStatsRepository()
        stats_repo.user_count = 42
        stats_repo.active_workflow_definition_count = 3
        stats_repo.storage_bytes = 1024
        client = _build_client(env, identity, platform_stats_repo=stats_repo)
        env.company_repo.create_company(name="Acme", slug="acme")

        response = client.get("/api/v1/platform/stats")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total_users"] == 42
        assert data["active_workflow_definitions"] == 3
        assert data["total_storage_bytes"] == 1024
        assert data["total_tenants"] >= 1


class TestPlatformHealth:
    def test_reports_database_reachability_and_dead_letter_backlog(self, env, platform_admin):
        _, identity = platform_admin
        job_repository = MagicMock()
        job_repository.count_dead_letter_by_queue.return_value = {"default": 2}
        client = _build_client(env, identity, job_repository=job_repository)

        response = client.get("/api/v1/platform/health")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "ok"
        assert data["database"] == "ok"
        assert data["dead_letter_by_queue"] == {"default": 2}


class TestPlatformAuditLog:
    def test_spans_multiple_companies_and_can_be_filtered_to_one(self, env, platform_admin):
        _, identity = platform_admin
        client = _build_client(env, identity)
        first = client.post("/api/v1/platform/companies", json={"name": "First"}).json()["data"]
        second = client.post("/api/v1/platform/companies", json={"name": "Second"}).json()["data"]
        # `COMPANY_CREATED` entries are platform-level (company_id=None,
        # per AuditLogRecord's own docstring) — a settings update is what
        # actually attributes an entry to its company, so use that to
        # produce company-scoped rows to filter on.
        client.patch(
            f"/api/v1/platform/companies/{first['id']}",
            json={"expected_version": first["version"], "notes": "note"},
        )
        client.patch(
            f"/api/v1/platform/companies/{second['id']}",
            json={"expected_version": second["version"], "notes": "note"},
        )

        everything = client.get("/api/v1/platform/audit-log")
        assert everything.status_code == 200
        company_ids = {e["company_id"] for e in everything.json()["data"]}
        assert first["id"] in company_ids
        assert second["id"] in company_ids

        scoped = client.get("/api/v1/platform/audit-log", params={"company_id": first["id"]})
        assert all(e["company_id"] == first["id"] for e in scoped.json()["data"])
        assert any(e["company_id"] == first["id"] for e in scoped.json()["data"])
