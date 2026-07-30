"""Unit tests for ``app.services.notification_service.NotificationService``.

The email side effect is exercised entirely through ``FakeEmailSender``
(``tests/fixtures/fakes.py``), a test double for the ``EmailSender``
protocol — no real SMTP/network dependency is ever involved.
"""

from __future__ import annotations

import threading
import time
from uuid import uuid4

import pytest

from app.auth.authentication import AuthenticatedIdentity
from app.models.enums import NotificationType, UserRole
from app.services.exceptions import NotFoundError, PermissionDeniedError
from app.services.notification_service import NotificationService, ThreadPoolEmailDispatchExecutor
from tests.fixtures.fakes import (
    DEFAULT_TEST_COMPANY_ID,
    FakeEmailSender,
    FakeNotificationPreferenceRepository,
    FakeNotificationRepository,
)

pytestmark = pytest.mark.unit


class TestNotificationCreationAndEmailDispatch:
    def test_notify_assignment_creates_a_notification_and_sends_an_email(self):
        notification_repo = FakeNotificationRepository()
        email_sender = FakeEmailSender(always_succeed=True)
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=email_sender,
        )
        recipient_id = uuid4()
        request_id = uuid4()

        notification = service.notify_assignment(
            recipient_id=recipient_id, request_id=request_id, message="You're up."
        )

        assert notification.notification_type.value == "assignment"
        assert notification.email_sent is True
        assert len(email_sender.sent) == 1
        assert email_sender.sent[0].to_address == str(recipient_id)

    def test_a_failed_email_send_does_not_prevent_or_reverse_notification_creation(self):
        notification_repo = FakeNotificationRepository()
        email_sender = FakeEmailSender(always_succeed=False)
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=email_sender,
        )

        notification = service.notify_decision(
            recipient_id=uuid4(), request_id=uuid4(), message="Your request was rejected."
        )

        assert notification.email_sent is False
        stored = notification_repo.get_by_id(notification.id)
        assert stored is not None

    def test_an_email_sender_exception_is_suppressed_and_never_propagates(self):
        notification_repo = FakeNotificationRepository()
        email_sender = FakeEmailSender(raise_exception=True)
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=email_sender,
        )

        notification = service.notify_system(
            recipient_id=uuid4(), message="System maintenance tonight."
        )

        assert notification.email_sent is False

    def test_no_email_sender_configured_skips_dispatch_without_error(self):
        notification_repo = FakeNotificationRepository()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=None,
        )

        notification = service.notify_reminder(
            recipient_id=uuid4(), request_id=uuid4(), message="Reminder: stage nearing escalation."
        )

        assert notification.email_sent is False


class TestBackgroundEmailDispatch:
    """Covers ``ThreadPoolEmailDispatchExecutor`` — the production wiring
    that keeps a real SMTP send off the calling thread (Milestone 13,
    High finding 1). The default ``NotificationService`` behavior
    exercised by every other test in this module is deliberately left
    synchronous; this class is the only place the background executor
    itself is tested.
    """

    def test_dispatch_does_not_block_the_caller_on_a_slow_email_sender(self):
        release_send = threading.Event()
        started_send = threading.Event()

        class SlowEmailSender:
            def send(self, *, to_address: str, subject: str, body: str) -> bool:
                started_send.set()
                release_send.wait(timeout=5)
                return True

        notification_repo = FakeNotificationRepository()
        executor = ThreadPoolEmailDispatchExecutor()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=SlowEmailSender(),
            email_executor=executor,
        )

        try:
            started = time.monotonic()
            notification = service.notify_assignment(
                recipient_id=uuid4(), request_id=uuid4(), message="You're up."
            )
            elapsed = time.monotonic() - started

            # The call returns before the slow sender is even released,
            # let alone finished — proving dispatch happened off-thread.
            assert elapsed < 1.0
            assert notification.email_sent is False

            assert started_send.wait(timeout=5), "background send never started"
            release_send.set()

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if notification_repo.get_by_id(notification.id).email_sent:
                    break
                time.sleep(0.01)
            assert notification_repo.get_by_id(notification.id).email_sent is True
        finally:
            executor.close(wait=True)

    def test_close_stops_the_pool_without_raising(self):
        executor = ThreadPoolEmailDispatchExecutor()
        executor.submit(lambda: None)
        executor.close(wait=True)


class TestReadAccess:
    def test_only_the_recipient_may_mark_their_own_notification_read(self):
        notification_repo = FakeNotificationRepository()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=None,
        )
        recipient_id = uuid4()
        notification = service.notify_system(recipient_id=recipient_id, message="Hello.")

        recipient_identity = AuthenticatedIdentity(
            user_id=recipient_id,
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )
        other_identity = AuthenticatedIdentity(
            user_id=uuid4(),
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )

        with pytest.raises(PermissionDeniedError):
            service.mark_read(other_identity, notification.id)

        marked = service.mark_read(recipient_identity, notification.id)
        assert marked.is_read is True

    def test_get_unread_count(self):
        notification_repo = FakeNotificationRepository()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=None,
        )
        recipient_id = uuid4()
        identity = AuthenticatedIdentity(
            user_id=recipient_id,
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )
        service.notify_system(recipient_id=recipient_id, message="One")
        service.notify_system(recipient_id=recipient_id, message="Two")

        assert service.get_unread_count(identity) == 2


class TestMarkAllRead:
    def test_marks_every_unread_notification_read_and_returns_the_count(self):
        notification_repo = FakeNotificationRepository()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=None,
        )
        recipient_id = uuid4()
        identity = AuthenticatedIdentity(
            user_id=recipient_id,
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )
        first = service.notify_system(recipient_id=recipient_id, message="One")
        second = service.notify_system(recipient_id=recipient_id, message="Two")

        updated_count = service.mark_all_read(identity)

        assert updated_count == 2
        assert notification_repo.get_by_id(first.id).is_read is True
        assert notification_repo.get_by_id(second.id).is_read is True
        assert service.get_unread_count(identity) == 0

    def test_mark_all_read_only_affects_the_caller_s_own_notifications(self):
        notification_repo = FakeNotificationRepository()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=None,
        )
        recipient_id = uuid4()
        other_id = uuid4()
        identity = AuthenticatedIdentity(
            user_id=recipient_id,
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )
        other_notification = service.notify_system(recipient_id=other_id, message="Not mine")

        service.mark_all_read(identity)

        assert notification_repo.get_by_id(other_notification.id).is_read is False

    def test_mark_all_read_is_a_no_op_when_nothing_is_unread(self):
        notification_repo = FakeNotificationRepository()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=None,
        )
        recipient_id = uuid4()
        identity = AuthenticatedIdentity(
            user_id=recipient_id,
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )

        assert service.mark_all_read(identity) == 0


class TestArchiving:
    def test_only_the_recipient_may_archive_their_own_notification(self):
        notification_repo = FakeNotificationRepository()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=None,
        )
        recipient_id = uuid4()
        notification = service.notify_system(recipient_id=recipient_id, message="Hello.")

        recipient_identity = AuthenticatedIdentity(
            user_id=recipient_id,
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )
        other_identity = AuthenticatedIdentity(
            user_id=uuid4(),
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )

        with pytest.raises(PermissionDeniedError):
            service.archive_notification(other_identity, notification.id)

        archived = service.archive_notification(recipient_identity, notification.id)
        assert archived.is_archived is True
        assert archived.archived_at is not None

    def test_unarchive_restores_the_notification_to_the_active_view(self):
        notification_repo = FakeNotificationRepository()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=None,
        )
        recipient_id = uuid4()
        identity = AuthenticatedIdentity(
            user_id=recipient_id,
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )
        notification = service.notify_system(recipient_id=recipient_id, message="Hello.")
        service.archive_notification(identity, notification.id)

        restored = service.unarchive_notification(identity, notification.id)

        assert restored.is_archived is False
        assert restored.archived_at is None

    def test_archived_notifications_are_excluded_from_the_default_list_and_unread_count(self):
        notification_repo = FakeNotificationRepository()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=None,
        )
        recipient_id = uuid4()
        identity = AuthenticatedIdentity(
            user_id=recipient_id,
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )
        kept = service.notify_system(recipient_id=recipient_id, message="Stays active.")
        archived = service.notify_system(recipient_id=recipient_id, message="Gets archived.")
        service.archive_notification(identity, archived.id)

        active = service.list_notifications(identity)
        assert [n.id for n in active.items] == [kept.id]

        everything = service.list_notifications(identity, is_archived=None)
        assert {n.id for n in everything.items} == {kept.id, archived.id}

        only_archived = service.list_notifications(identity, is_archived=True)
        assert [n.id for n in only_archived.items] == [archived.id]

        assert service.get_unread_count(identity) == 1

    def test_archiving_an_unknown_notification_raises_not_found(self):
        notification_repo = FakeNotificationRepository()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=None,
        )
        identity = AuthenticatedIdentity(
            user_id=uuid4(),
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )

        with pytest.raises(NotFoundError):
            service.archive_notification(identity, uuid4())


class TestFilteringByType:
    def test_list_notifications_can_be_restricted_to_a_single_type(self):
        notification_repo = FakeNotificationRepository()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=None,
        )
        recipient_id = uuid4()
        identity = AuthenticatedIdentity(
            user_id=recipient_id,
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )
        service.notify_system(recipient_id=recipient_id, message="System event.")
        assignment = service.notify_assignment(
            recipient_id=recipient_id, request_id=uuid4(), message="You're up."
        )

        result = service.list_notifications(identity, notification_type=NotificationType.ASSIGNMENT)

        assert [n.id for n in result.items] == [assignment.id]


class TestSearch:
    def test_list_notifications_can_be_restricted_by_free_text_search(self):
        notification_repo = FakeNotificationRepository()
        service = NotificationService(
            notification_repo=notification_repo,
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=None,
        )
        recipient_id = uuid4()
        identity = AuthenticatedIdentity(
            user_id=recipient_id,
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )
        target = service.notify_system(recipient_id=recipient_id, message="Quarterly budget approved.")
        service.notify_system(recipient_id=recipient_id, message="Unrelated notice.")

        result = service.list_notifications(identity, search="budget")

        assert [n.id for n in result.items] == [target.id]


class TestPreferences:
    def _service(self) -> tuple[NotificationService, FakeEmailSender]:
        email_sender = FakeEmailSender(always_succeed=True)
        service = NotificationService(
            notification_repo=FakeNotificationRepository(),
            preference_repo=FakeNotificationPreferenceRepository(),
            email_sender=email_sender,
        )
        return service, email_sender

    def _identity(self, user_id) -> AuthenticatedIdentity:
        return AuthenticatedIdentity(
            user_id=user_id,
            email=None,
            role=UserRole.EMPLOYEE,
            company_id=DEFAULT_TEST_COMPANY_ID,
            is_platform_admin=False,
            expires_at=None,
            raw_claims={},
        )

    def test_list_preferences_returns_every_type_with_synthesized_defaults(self):
        service, _ = self._service()
        identity = self._identity(uuid4())

        preferences = service.list_preferences(identity)

        assert {p.notification_type for p in preferences} == set(NotificationType)
        assert all(p.in_app_enabled and p.email_enabled and p.updated_at is None for p in preferences)

    def test_default_behavior_is_unchanged_until_a_preference_is_explicitly_set(self):
        service, email_sender = self._service()
        recipient_id = uuid4()

        notification = service.notify_assignment(
            recipient_id=recipient_id, request_id=uuid4(), message="You're up."
        )

        assert notification is not None
        assert notification.email_sent is True
        assert len(email_sender.sent) == 1

    def test_disabling_in_app_delivery_suppresses_the_notification_and_its_email(self):
        service, email_sender = self._service()
        recipient_id = uuid4()
        identity = self._identity(recipient_id)
        service.update_preference(
            identity, NotificationType.ASSIGNMENT, in_app_enabled=False, email_enabled=True
        )

        notification = service.notify_assignment(
            recipient_id=recipient_id, request_id=uuid4(), message="You're up."
        )

        assert notification is None
        assert len(email_sender.sent) == 0
        assert service.get_unread_count(identity) == 0

    def test_disabling_email_only_still_creates_the_in_app_notification(self):
        service, email_sender = self._service()
        recipient_id = uuid4()
        identity = self._identity(recipient_id)
        service.update_preference(
            identity, NotificationType.ASSIGNMENT, in_app_enabled=True, email_enabled=False
        )

        notification = service.notify_assignment(
            recipient_id=recipient_id, request_id=uuid4(), message="You're up."
        )

        assert notification is not None
        assert notification.email_sent is False
        assert len(email_sender.sent) == 0
        assert service.get_unread_count(identity) == 1

    def test_preference_is_scoped_to_a_single_notification_type(self):
        service, email_sender = self._service()
        recipient_id = uuid4()
        identity = self._identity(recipient_id)
        service.update_preference(
            identity, NotificationType.ASSIGNMENT, in_app_enabled=False, email_enabled=False
        )

        suppressed = service.notify_assignment(
            recipient_id=recipient_id, request_id=uuid4(), message="You're up."
        )
        unaffected = service.notify_system(recipient_id=recipient_id, message="System event.")

        assert suppressed is None
        assert unaffected is not None

    def test_update_preference_partial_patch_leaves_the_other_field_unchanged(self):
        service, _ = self._service()
        recipient_id = uuid4()
        identity = self._identity(recipient_id)
        service.update_preference(
            identity, NotificationType.REMINDER, in_app_enabled=True, email_enabled=False
        )

        updated = service.update_preference(
            identity, NotificationType.REMINDER, in_app_enabled=False
        )

        assert updated.in_app_enabled is False
        assert updated.email_enabled is False

    def test_update_preference_round_trips_through_list_preferences(self):
        service, _ = self._service()
        identity = self._identity(uuid4())
        service.update_preference(
            identity, NotificationType.ESCALATION, in_app_enabled=False, email_enabled=True
        )

        preferences = service.list_preferences(identity)

        escalation = next(p for p in preferences if p.notification_type is NotificationType.ESCALATION)
        assert escalation.in_app_enabled is False
        assert escalation.email_enabled is True
        assert escalation.updated_at is not None
