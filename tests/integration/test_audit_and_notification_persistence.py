"""Real-database tests for audit log and notification persistence."""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import AuditAction, NotificationType, UserRole

pytestmark = pytest.mark.integration


class TestAuditLogPersistence:
    def test_record_event_persists_action_actor_request_and_metadata(
        self, real_repos, make_test_profile
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type, version=1, definition={"stages": []}, created_by=admin.id
        )
        request = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Audit persistence test",
        )

        entry = real_repos.audit.record_event(
            action=AuditAction.REQUEST_CREATED,
            actor_id=employee.id,
            request_id=request.id,
            metadata={"note": "created via integration test"},
        )

        reloaded = real_repos.audit.get_by_id(entry.id)
        assert reloaded.action == "REQUEST_CREATED"
        assert reloaded.actor_id == employee.id
        assert reloaded.request_id == request.id
        assert reloaded.metadata == {"note": "created via integration test"}

    def test_list_for_request_returns_entries_chronologically(self, real_repos, make_test_profile):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type, version=1, definition={"stages": []}, created_by=admin.id
        )
        request = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Chronological audit test",
        )
        real_repos.audit.record_event(
            action=AuditAction.REQUEST_CREATED, actor_id=employee.id, request_id=request.id
        )
        real_repos.audit.record_event(
            action=AuditAction.STAGE_APPROVED, actor_id=employee.id, request_id=request.id
        )

        entries = real_repos.audit.list_for_request(request.id).items

        assert [e.action for e in entries] == ["REQUEST_CREATED", "STAGE_APPROVED"]

    def test_list_for_actor_returns_only_that_actors_entries(self, real_repos, make_test_profile):
        actor_a = make_test_profile(role=UserRole.EMPLOYEE)
        actor_b = make_test_profile(role=UserRole.EMPLOYEE)
        real_repos.audit.record_event(action=AuditAction.PROFILE_UPDATED, actor_id=actor_a.id)
        real_repos.audit.record_event(action=AuditAction.PROFILE_UPDATED, actor_id=actor_b.id)

        entries_for_a = real_repos.audit.list_for_actor(actor_a.id).items

        assert all(e.actor_id == actor_a.id for e in entries_for_a)
        assert len(entries_for_a) == 1

    def test_search_matches_action_substring_and_respects_request_ids_scope(
        self, real_repos, make_test_profile
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type, version=1, definition={"stages": []}, created_by=admin.id
        )
        in_scope = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="In scope request",
        )
        out_of_scope = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Out of scope request",
        )
        real_repos.audit.record_event(
            action=AuditAction.REQUEST_CREATED, actor_id=employee.id, request_id=in_scope.id
        )
        real_repos.audit.record_event(
            action=AuditAction.REQUEST_CREATED, actor_id=employee.id, request_id=out_of_scope.id
        )

        scoped = real_repos.audit.search("CREATED", request_ids=[in_scope.id]).items

        assert all(e.request_id == in_scope.id for e in scoped)
        assert any(e.request_id == in_scope.id for e in scoped)


class TestNotificationPersistence:
    def test_create_notification_and_mark_read_round_trip(self, real_repos, make_test_profile):
        recipient = make_test_profile(role=UserRole.EMPLOYEE)

        created = real_repos.notification.create_notification(
            recipient_id=recipient.id,
            notification_type=NotificationType.SYSTEM,
            message="Integration test notification.",
        )
        assert created.is_read is False

        reloaded = real_repos.notification.get_by_id(created.id)
        assert reloaded.message == "Integration test notification."

        marked = real_repos.notification.mark_read(created.id)
        assert marked.is_read is True
        assert marked.read_at is not None

    def test_mark_email_sent_persists_the_dispatch_timestamp(self, real_repos, make_test_profile):
        recipient = make_test_profile(role=UserRole.EMPLOYEE)
        created = real_repos.notification.create_notification(
            recipient_id=recipient.id,
            notification_type=NotificationType.SYSTEM,
            message="Email test.",
        )

        updated = real_repos.notification.mark_email_sent(created.id)

        assert updated.email_sent is True
        assert updated.email_sent_at is not None

    def test_get_unread_count_and_list_for_recipient(self, real_repos, make_test_profile):
        recipient = make_test_profile(role=UserRole.EMPLOYEE)
        first = real_repos.notification.create_notification(
            recipient_id=recipient.id, notification_type=NotificationType.SYSTEM, message="One"
        )
        real_repos.notification.create_notification(
            recipient_id=recipient.id, notification_type=NotificationType.SYSTEM, message="Two"
        )
        real_repos.notification.mark_read(first.id)

        assert real_repos.notification.get_unread_count(recipient.id) == 1

        unread_only = real_repos.notification.list_for_recipient(recipient.id, is_read=False).items
        assert len(unread_only) == 1
        assert unread_only[0].message == "Two"

    def test_list_for_recipient_filters_by_notification_type(self, real_repos, make_test_profile):
        recipient = make_test_profile(role=UserRole.EMPLOYEE)
        real_repos.notification.create_notification(
            recipient_id=recipient.id,
            notification_type=NotificationType.SYSTEM,
            message="System one.",
        )
        real_repos.notification.create_notification(
            recipient_id=recipient.id,
            notification_type=NotificationType.REMINDER,
            message="Reminder one.",
        )

        reminders = real_repos.notification.list_for_recipient(
            recipient.id, notification_type=NotificationType.REMINDER
        ).items

        assert len(reminders) == 1
        assert reminders[0].message == "Reminder one."

    def test_mark_all_read_updates_every_unread_row_and_returns_the_count(
        self, real_repos, make_test_profile
    ):
        recipient = make_test_profile(role=UserRole.EMPLOYEE)
        real_repos.notification.create_notification(
            recipient_id=recipient.id, notification_type=NotificationType.SYSTEM, message="One"
        )
        real_repos.notification.create_notification(
            recipient_id=recipient.id, notification_type=NotificationType.SYSTEM, message="Two"
        )

        updated_count = real_repos.notification.mark_all_read(recipient.id)

        assert updated_count == 2
        assert real_repos.notification.get_unread_count(recipient.id) == 0

    def test_archive_and_unarchive_round_trip(self, real_repos, make_test_profile):
        recipient = make_test_profile(role=UserRole.EMPLOYEE)
        created = real_repos.notification.create_notification(
            recipient_id=recipient.id,
            notification_type=NotificationType.SYSTEM,
            message="Archive me.",
        )

        archived = real_repos.notification.archive(created.id)
        assert archived.archived_at is not None

        active_only = real_repos.notification.list_for_recipient(recipient.id).items
        assert created.id not in [n.id for n in active_only]

        archived_only = real_repos.notification.list_for_recipient(
            recipient.id, is_archived=True
        ).items
        assert [n.id for n in archived_only] == [created.id]

        restored = real_repos.notification.unarchive(created.id)
        assert restored.archived_at is None
        active_again = real_repos.notification.list_for_recipient(recipient.id).items
        assert created.id in [n.id for n in active_again]

    def test_archived_unread_notifications_are_excluded_from_the_unread_count(
        self, real_repos, make_test_profile
    ):
        recipient = make_test_profile(role=UserRole.EMPLOYEE)
        created = real_repos.notification.create_notification(
            recipient_id=recipient.id,
            notification_type=NotificationType.SYSTEM,
            message="Unread but archived.",
        )

        real_repos.notification.archive(created.id)

        assert real_repos.notification.get_unread_count(recipient.id) == 0
