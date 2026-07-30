"""Tests for the ``/api/v1/notifications*`` routes.

Every route is a thin wrapper over the real, unmodified
``NotificationService`` (already wired on ``tests/conftest.py``'s ``env``
fixture) — no new fake repository was needed, since
``FakeNotificationRepository`` already existed. Notifications are seeded
directly via ``env.notification_service``'s internal ``notify_*`` methods
(the same way request/approval lifecycle events create them in
production), since notification creation is never a client-facing
endpoint.
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
            notification_service=env.notification_service,
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()  # runs the lifespan startup, so app.state.resources is populated
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


class TestListNotifications:
    def test_employee_sees_own_notifications(self, env, employee):
        employee_profile, employee_identity = employee
        env.notification_service.notify_system(recipient_id=employee_profile.id, message="Hello")

        client = _build_client(env, employee_identity)
        response = client.get("/api/v1/notifications")

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["message"] == "Hello"
        assert body["pagination"]["total_records"] == 1

    def test_scoped_to_caller_only(self, env, employee, approver):
        employee_profile, employee_identity = employee
        approver_profile, approver_identity = approver
        env.notification_service.notify_system(
            recipient_id=employee_profile.id, message="For employee"
        )
        env.notification_service.notify_system(
            recipient_id=approver_profile.id, message="For approver"
        )

        client = _build_client(env, employee_identity)
        response = client.get("/api/v1/notifications")

        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["message"] == "For employee"

    def test_is_read_filter(self, env, employee):
        employee_profile, employee_identity = employee
        env.notification_service.notify_system(
            recipient_id=employee_profile.id, message="Unread one"
        )
        client = _build_client(env, employee_identity)

        response = client.get("/api/v1/notifications", params={"is_read": True})

        assert response.status_code == 200
        assert response.json()["data"] == []


class TestUnreadCount:
    def test_counts_unread_only(self, env, employee):
        employee_profile, employee_identity = employee
        env.notification_service.notify_system(recipient_id=employee_profile.id, message="One")
        env.notification_service.notify_system(recipient_id=employee_profile.id, message="Two")
        client = _build_client(env, employee_identity)

        response = client.get("/api/v1/notifications/unread-count")

        assert response.status_code == 200
        assert response.json()["data"]["unread_count"] == 2


class TestMarkRead:
    def test_happy_path(self, env, employee):
        employee_profile, employee_identity = employee
        notification = env.notification_service.notify_system(
            recipient_id=employee_profile.id, message="Mark me"
        )
        client = _build_client(env, employee_identity)

        response = client.post(f"/api/v1/notifications/{notification.id}/read")

        assert response.status_code == 200
        assert response.json()["data"]["is_read"] is True

    def test_other_users_notification_is_forbidden(self, env, employee, approver):
        employee_profile, _ = employee
        _, approver_identity = approver
        notification = env.notification_service.notify_system(
            recipient_id=employee_profile.id, message="Not yours"
        )
        client = _build_client(env, approver_identity)

        response = client.post(f"/api/v1/notifications/{notification.id}/read")

        assert response.status_code == 403


class TestMarkAllRead:
    def test_returns_updated_count(self, env, employee):
        employee_profile, employee_identity = employee
        env.notification_service.notify_system(recipient_id=employee_profile.id, message="One")
        env.notification_service.notify_system(recipient_id=employee_profile.id, message="Two")
        client = _build_client(env, employee_identity)

        response = client.post("/api/v1/notifications/read-all")

        assert response.status_code == 200
        assert response.json()["data"]["updated"] == 2

        unread = client.get("/api/v1/notifications/unread-count")
        assert unread.json()["data"]["unread_count"] == 0


class TestArchive:
    def test_archive_and_unarchive_round_trip(self, env, employee):
        employee_profile, employee_identity = employee
        notification = env.notification_service.notify_system(
            recipient_id=employee_profile.id, message="Archive me"
        )
        client = _build_client(env, employee_identity)

        archived = client.post(f"/api/v1/notifications/{notification.id}/archive")
        assert archived.status_code == 200
        assert archived.json()["data"]["is_archived"] is True

        active_list = client.get("/api/v1/notifications")
        assert active_list.json()["data"] == []

        restored = client.post(f"/api/v1/notifications/{notification.id}/unarchive")
        assert restored.status_code == 200
        assert restored.json()["data"]["is_archived"] is False

    def test_other_users_notification_is_forbidden(self, env, employee, approver):
        employee_profile, _ = employee
        _, approver_identity = approver
        notification = env.notification_service.notify_system(
            recipient_id=employee_profile.id, message="Not yours"
        )
        client = _build_client(env, approver_identity)

        response = client.post(f"/api/v1/notifications/{notification.id}/archive")

        assert response.status_code == 403


class TestSearch:
    def test_search_filters_by_message_text(self, env, employee):
        employee_profile, employee_identity = employee
        env.notification_service.notify_system(
            recipient_id=employee_profile.id, message="Quarterly budget approved."
        )
        env.notification_service.notify_system(
            recipient_id=employee_profile.id, message="Unrelated notice."
        )
        client = _build_client(env, employee_identity)

        response = client.get("/api/v1/notifications", params={"search": "budget"})

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert "budget" in data[0]["message"].lower()


class TestPreferences:
    def test_list_preferences_returns_every_notification_type(self, env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.get("/api/v1/notifications/preferences")

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 6
        assert all(item["in_app_enabled"] and item["email_enabled"] for item in data)

    def test_update_preference_happy_path(self, env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.patch(
            "/api/v1/notifications/preferences/reminder", json={"in_app_enabled": False}
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["notification_type"] == "reminder"
        assert body["in_app_enabled"] is False
        assert body["email_enabled"] is True

    def test_update_preference_rejects_an_empty_payload(self, env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.patch("/api/v1/notifications/preferences/reminder", json={})

        assert response.status_code == 422

    def test_update_preference_rejects_an_unknown_notification_type(self, env, employee):
        _, employee_identity = employee
        client = _build_client(env, employee_identity)

        response = client.patch(
            "/api/v1/notifications/preferences/not-a-real-type", json={"in_app_enabled": False}
        )

        assert response.status_code == 422

    def test_disabled_preference_is_reflected_in_subsequent_notifications(self, env, employee):
        employee_profile, employee_identity = employee
        client = _build_client(env, employee_identity)
        client.patch(
            "/api/v1/notifications/preferences/system", json={"in_app_enabled": False}
        )

        env.notification_service.notify_system(recipient_id=employee_profile.id, message="Hidden")

        response = client.get("/api/v1/notifications")
        assert response.json()["data"] == []
