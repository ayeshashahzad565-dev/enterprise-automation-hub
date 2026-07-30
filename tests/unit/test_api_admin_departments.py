"""Tests for the ``/api/v1/admin/departments*`` routes.

Both routes are compositions over ``ProfileRepository.list_by_role``
(``app.api.routers.admin_shared``) plus, for workload,
``AnalyticsProvider.get_department_metrics`` — the fake analytics
provider stubs the latter so this test focuses on the department
grouping/member-count logic specifically.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.dto import DepartmentMetrics
from app.api.main import create_app
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
from app.models import StatusBreakdown

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


class _FakeAnalyticsProvider:
    def get_department_metrics(self, department: str, **_kwargs: Any) -> DepartmentMetrics:
        return DepartmentMetrics(
            department=department,
            status_breakdown=StatusBreakdown(counts={}, total=0),
            approval_metrics=None,  # type: ignore[arg-type]
            workload=3,
        )


def _build_client(env, identity: AuthenticatedIdentity) -> TestClient:
    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            profile_repo=env.profile_repo,
            analytics_provider=_FakeAnalyticsProvider(),
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


class TestList:
    def test_admin_sees_composed_department_counts(self, env, admin, employee, approver):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/admin/departments")

        assert response.status_code == 200
        by_department = {row["department"]: row for row in response.json()["data"]}
        assert "sales" in by_department
        assert by_department["sales"]["roles"]["employee"] == 1
        assert by_department["sales"]["roles"]["approver"] == 1
        assert by_department["sales"]["member_count"] == 2

    def test_employee_is_forbidden(self, env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.get("/api/v1/admin/departments")

        assert response.status_code == 403


class TestWorkload:
    def test_admin_sees_members_and_workload(self, env, admin, employee, approver):
        _, admin_identity = admin
        client = _build_client(env, admin_identity)

        response = client.get("/api/v1/admin/departments/sales/workload")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["member_count"] == 2
        assert data["workload"] == 3
        names = {m["full_name"] for m in data["members"]}
        assert names == {"Eve Employee", "Alan Approver"}

    def test_employee_is_forbidden(self, env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.get("/api/v1/admin/departments/sales/workload")

        assert response.status_code == 403
