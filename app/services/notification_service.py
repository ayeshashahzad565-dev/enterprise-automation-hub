"""Application service coordinating notification creation and delivery.

Per the ADD's Notification Service description and the Workflow Engine
Design Document (WEDD Section 15), every notification is persisted
in-app and, as part of the baseline, mirrored as an email — the two
effects are independent: a failure to send the email never prevents or
reverses the in-app notification's creation.

This module defines no SMTP implementation. ``EmailSender`` is a
``typing.Protocol`` — an interface only — that a future infrastructure
module is expected to implement using Python's standard ``smtplib`` (per
the ADD's fixed technology stack, which introduces no third-party email
library). This service accepts an optional ``EmailSender`` via
dependency injection and degrades gracefully (skipping email dispatch
entirely, logging that it did so) when none is supplied.

"Scheduler hooks" refers to the methods on this service the Scheduler's
Reminder Dispatch and Escalation Check jobs call into directly — this
service exposes no dependency on ``app.workflow`` or any scheduling
library itself; it is simply invoked by that job the same way any other
caller invokes it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.auth.authentication import AuthenticatedIdentity
from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.notification_preference_repository import (
    NotificationPreferenceRepository,
)
from app.database.repositories.notification_repository import (
    NotificationRecord,
    NotificationRepository,
)
from app.models import Notification, NotificationPreference
from app.models.enums import NotificationType
from app.services.exceptions import PermissionDeniedError, translate_database_error
from app.utils.decorators import log_calls

__all__ = [
    "EmailDispatchExecutor",
    "EmailSender",
    "ThreadPoolEmailDispatchExecutor",
    "map_notification_record_to_domain",
    "NotificationService",
]

#: The effective preference for a ``NotificationType`` no user has ever
#: explicitly configured — reproduces this service's original,
#: unconditional "always in-app, always email" behavior exactly, so a
#: user who never visits the preferences page sees no change at all.
_DEFAULT_PREFERENCE = (True, True)

logger = logging.getLogger(__name__)


@runtime_checkable
class EmailSender(Protocol):
    """Structural interface for dispatching a single notification email.

    A future infrastructure module is expected to implement this
    protocol using Python's standard ``smtplib``, configured via
    ``app.config.settings.SmtpSettings`` — no such implementation is
    provided in this package, per this service's "interfaces only"
    design brief.
    """

    def send(self, *, to_address: str, subject: str, body: str) -> bool:
        """Send a single email.

        Args:
            to_address: The recipient's email address.
            subject: The email subject line.
            body: The email body.

        Returns:
            ``True`` if the email was sent successfully, ``False``
            otherwise. Implementations are expected never to raise for an
            ordinary delivery failure; a raised exception is treated by
            ``NotificationService`` as an implementation defect, still
            caught and logged, never allowed to propagate.
        """
        ...


@runtime_checkable
class EmailDispatchExecutor(Protocol):
    """Schedules a zero-argument task for execution.

    ``NotificationService`` depends on this narrow interface — rather
    than on ``concurrent.futures.Executor`` directly — so a synchronous,
    same-thread implementation (the default, matching this service's
    original behavior and keeping unit tests deterministic with no real
    threading involved) and a background thread-pool implementation
    (``ThreadPoolEmailDispatchExecutor``, wired in ``app.bootstrap`` for
    the real SMTP path) are interchangeable without ``NotificationService``
    itself knowing which one it was given.
    """

    def submit(self, task: Callable[[], None]) -> None:
        """Schedule ``task`` to run, without blocking the caller."""
        ...


class _ImmediateExecutor:
    """Runs a submitted task synchronously, in the calling thread.

    The default ``EmailDispatchExecutor`` when none is supplied —
    preserves ``NotificationService``'s original blocking-but-simple
    dispatch behavior, so existing callers and tests that never opted
    into background dispatch see no change.
    """

    def submit(self, task: Callable[[], None]) -> None:
        task()


class ThreadPoolEmailDispatchExecutor:
    """Runs each submitted task on a small, shared background thread pool.

    Wired in ``app.bootstrap`` so a real SMTP send — which retries with
    exponential backoff on failure, per ``SmtpEmailProvider`` — never
    blocks the request thread handling an approval, rejection, or other
    action that triggers a notification.
    """

    def __init__(self, *, max_workers: int = 4) -> None:
        """Initialize the pool.

        Args:
            max_workers: The maximum number of concurrent email sends.
        """
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="notification-email"
        )

    def submit(self, task: Callable[[], None]) -> None:
        self._pool.submit(task)

    def close(self, *, wait: bool = False) -> None:
        """Stop accepting new tasks.

        Args:
            wait: If ``True``, block until every already-submitted task
                finishes. Defaults to ``False`` so application shutdown
                never hangs on a slow mail server — a dropped in-flight
                email on shutdown is acceptable per this service's
                existing best-effort, never-blocking email-dispatch
                contract (see ``_attempt_email_dispatch``).
        """
        self._pool.shutdown(wait=wait, cancel_futures=False)


def map_notification_record_to_domain(record: NotificationRecord) -> Notification:
    """Map a persistence-level ``NotificationRecord`` into its Domain
    Layer ``Notification`` representation.

    Args:
        record: The record returned by ``NotificationRepository``.

    Returns:
        The corresponding ``Notification`` domain model.
    """
    return Notification(
        id=record.id,
        recipient_id=record.recipient_id,
        request_id=record.request_id,
        notification_type=record.notification_type,
        message=record.message,
        is_read=record.is_read,
        read_at=record.read_at,
        email_sent=record.email_sent,
        email_sent_at=record.email_sent_at,
        archived_at=record.archived_at,
        created_at=record.created_at,
    )


class NotificationService:
    """Orchestrates notification creation, email dispatch, and read access."""

    def __init__(
        self,
        *,
        notification_repo: NotificationRepository,
        preference_repo: NotificationPreferenceRepository,
        email_sender: EmailSender | None = None,
        default_email_subject_prefix: str = "[Enterprise Automation Hub]",
        email_executor: EmailDispatchExecutor | None = None,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            notification_repo: Persistence for ``notifications``.
            preference_repo: Persistence for ``notification_preferences``,
                consulted by ``_create_and_dispatch`` before every
                notification is created.
            email_sender: An implementation of ``EmailSender``, or
                ``None`` to disable email dispatch entirely (matching
                the Deployment Guide's allowance for Development/Testing
                environments to disable email, DG Section 8.1).
            default_email_subject_prefix: A fixed prefix applied to every
                dispatched email's subject line.
            email_executor: Where ``email_sender.send(...)`` actually
                runs. Defaults to an in-thread, synchronous executor
                (this service's original behavior). ``app.bootstrap``
                wires a ``ThreadPoolEmailDispatchExecutor`` here for the
                real SMTP path, so approval/rejection/etc. requests are
                never blocked by mail-server latency or retries.
        """
        self._notification_repo = notification_repo
        self._preference_repo = preference_repo
        self._email_sender = email_sender
        self._subject_prefix = default_email_subject_prefix
        self._email_executor: EmailDispatchExecutor = email_executor or _ImmediateExecutor()
        self._logger = logging.getLogger(f"{__name__}.NotificationService")

    @log_calls()
    def notify_assignment(
        self, *, recipient_id: UUID, request_id: UUID, message: str
    ) -> Notification | None:
        """Create and dispatch an ``assignment`` notification.

        Args:
            recipient_id: The user newly assigned to a stage.
            request_id: The related request.
            message: The notification body.

        Returns:
            The created ``Notification``, or ``None`` if the recipient
            has disabled in-app delivery for this notification type (see
            ``_create_and_dispatch``).
        """
        return self._create_and_dispatch(
            recipient_id=recipient_id,
            request_id=request_id,
            notification_type=NotificationType.ASSIGNMENT,
            message=message,
        )

    @log_calls()
    def notify_reminder(
        self, *, recipient_id: UUID, request_id: UUID, message: str
    ) -> Notification | None:
        """Create and dispatch a ``reminder`` notification.

        Invoked by the Scheduler's Reminder Dispatch job (WEDD Section
        8.3) for stages nearing, but not yet past, their escalation
        threshold.

        Args:
            recipient_id: The current assignee.
            request_id: The related request.
            message: The notification body.

        Returns:
            The created ``Notification``, or ``None`` if the recipient
            has disabled in-app delivery for this notification type (see
            ``_create_and_dispatch``).
        """
        return self._create_and_dispatch(
            recipient_id=recipient_id,
            request_id=request_id,
            notification_type=NotificationType.REMINDER,
            message=message,
        )

    @log_calls()
    def notify_escalation(
        self, *, recipient_id: UUID, request_id: UUID, message: str
    ) -> Notification | None:
        """Create and dispatch an ``escalation`` notification.

        Invoked by ``ApprovalService.escalate_stage`` following the
        Scheduler's Escalation Check job (WEDD Section 8.4).

        Args:
            recipient_id: The newly (re)assigned user.
            request_id: The related request.
            message: The notification body.

        Returns:
            The created ``Notification``, or ``None`` if the recipient
            has disabled in-app delivery for this notification type (see
            ``_create_and_dispatch``).
        """
        return self._create_and_dispatch(
            recipient_id=recipient_id,
            request_id=request_id,
            notification_type=NotificationType.ESCALATION,
            message=message,
        )

    @log_calls()
    def notify_decision(
        self, *, recipient_id: UUID, request_id: UUID, message: str
    ) -> Notification | None:
        """Create and dispatch a ``decision`` notification.

        Per WEDD Section 15.1, used for a stage rejection, notifying the
        requester.

        Args:
            recipient_id: The requester.
            request_id: The related request.
            message: The notification body.

        Returns:
            The created ``Notification``, or ``None`` if the recipient
            has disabled in-app delivery for this notification type (see
            ``_create_and_dispatch``).
        """
        return self._create_and_dispatch(
            recipient_id=recipient_id,
            request_id=request_id,
            notification_type=NotificationType.DECISION,
            message=message,
        )

    @log_calls()
    def notify_completion(
        self, *, recipient_id: UUID, request_id: UUID, message: str
    ) -> Notification | None:
        """Create and dispatch a ``completion`` notification.

        Args:
            recipient_id: The requester.
            request_id: The related request.
            message: The notification body.

        Returns:
            The created ``Notification``, or ``None`` if the recipient
            has disabled in-app delivery for this notification type (see
            ``_create_and_dispatch``).
        """
        return self._create_and_dispatch(
            recipient_id=recipient_id,
            request_id=request_id,
            notification_type=NotificationType.COMPLETION,
            message=message,
        )

    @log_calls()
    def notify_system(self, *, recipient_id: UUID, message: str) -> Notification | None:
        """Create and dispatch a ``system`` notification, unrelated to any request.

        Args:
            recipient_id: The recipient.
            message: The notification body.

        Returns:
            The created ``Notification``, or ``None`` if the recipient
            has disabled in-app delivery for this notification type (see
            ``_create_and_dispatch``).
        """
        return self._create_and_dispatch(
            recipient_id=recipient_id,
            request_id=None,
            notification_type=NotificationType.SYSTEM,
            message=message,
        )

    @log_calls()
    def list_notifications(
        self,
        identity: AuthenticatedIdentity,
        *,
        is_read: bool | None = None,
        notification_type: NotificationType | None = None,
        is_archived: bool | None = False,
        search: str | None = None,
        page: Page = Page(),
    ) -> PagedResult[Notification]:
        """List the caller's own notifications.

        Args:
            identity: The authenticated caller.
            is_read: Restrict to read or unread notifications, if
                provided.
            notification_type: Restrict to a single notification category,
                if provided.
            is_archived: Restrict to archived (``True``) or active
                (``False``) notifications. Defaults to ``False``; pass
                ``None`` to include both.
            search: Free-text search over the notification message, if
                provided.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of the caller's own ``Notification`` instances.
        """
        try:
            result = self._notification_repo.list_for_recipient(
                identity.user_id,
                is_read=is_read,
                notification_type=notification_type,
                is_archived=is_archived,
                search=search,
                page=page,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return PagedResult(
            items=[map_notification_record_to_domain(r) for r in result.items],
            page=result.page,
            page_size=result.page_size,
            total_records=result.total_records,
        )

    @log_calls()
    def mark_all_read(self, identity: AuthenticatedIdentity) -> int:
        """Mark every currently unread notification of the caller's as read.

        Args:
            identity: The authenticated caller.

        Returns:
            The number of notifications that were updated.
        """
        try:
            return self._notification_repo.mark_all_read(identity.user_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

    @log_calls()
    def archive_notification(
        self, identity: AuthenticatedIdentity, notification_id: UUID
    ) -> Notification:
        """Archive a notification, removing it from the caller's default view.

        Per the same rule as ``mark_read`` (API-ADD Section 19.8.2), only
        the notification's own recipient may archive it — not even an
        administrator may archive another user's notification.

        Args:
            identity: The authenticated caller.
            notification_id: The notification's id.

        Returns:
            The updated ``Notification``.

        Raises:
            NotFoundError: If no notification with this id exists.
            PermissionDeniedError: If the caller is not the recipient.
        """
        existing = self._get_owned_notification(identity, notification_id, action="archive")
        try:
            updated = self._notification_repo.archive(existing.id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        return map_notification_record_to_domain(updated)

    @log_calls()
    def unarchive_notification(
        self, identity: AuthenticatedIdentity, notification_id: UUID
    ) -> Notification:
        """Restore an archived notification to the caller's default view.

        Args:
            identity: The authenticated caller.
            notification_id: The notification's id.

        Returns:
            The updated ``Notification``.

        Raises:
            NotFoundError: If no notification with this id exists.
            PermissionDeniedError: If the caller is not the recipient.
        """
        existing = self._get_owned_notification(identity, notification_id, action="unarchive")
        try:
            updated = self._notification_repo.unarchive(existing.id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        return map_notification_record_to_domain(updated)

    def _get_owned_notification(
        self, identity: AuthenticatedIdentity, notification_id: UUID, *, action: str
    ) -> NotificationRecord:
        """Fetch a notification and verify the caller is its recipient.

        Args:
            identity: The authenticated caller.
            notification_id: The notification's id.
            action: A short, human-readable description of the attempted
                action, used only in the denial message (e.g. ``"archive"``).

        Returns:
            The existing ``NotificationRecord``.

        Raises:
            NotFoundError: If no notification with this id exists.
            PermissionDeniedError: If the caller is not the recipient.
        """
        try:
            existing = self._notification_repo.get_by_id(notification_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc

        if existing.recipient_id != identity.user_id:
            raise PermissionDeniedError(f"Only a notification's own recipient may {action} it.")
        return existing

    @log_calls()
    def mark_read(self, identity: AuthenticatedIdentity, notification_id: UUID) -> Notification:
        """Mark a notification as read.

        Per API-ADD Section 19.8.2, only the notification's own recipient
        may mark it read — not even an administrator may alter another
        user's read status.

        Args:
            identity: The authenticated caller.
            notification_id: The notification's id.

        Returns:
            The updated ``Notification``.

        Raises:
            NotFoundError: If no notification with this id exists.
            PermissionDeniedError: If the caller is not the recipient.
        """
        existing = self._get_owned_notification(identity, notification_id, action="mark it as read")
        try:
            updated = self._notification_repo.mark_read(existing.id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return map_notification_record_to_domain(updated)

    @log_calls()
    def get_unread_count(self, identity: AuthenticatedIdentity) -> int:
        """Return the number of unread notifications for the caller.

        Args:
            identity: The authenticated caller.

        Returns:
            The unread notification count.
        """
        try:
            return self._notification_repo.get_unread_count(identity.user_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

    @log_calls()
    def list_preferences(self, identity: AuthenticatedIdentity) -> list[NotificationPreference]:
        """List the caller's effective preference for every notification type.

        Always returns exactly one entry per ``NotificationType``, in
        enum-declaration order, regardless of how many the caller has
        actually configured — a type with no stored row is synthesized
        as the default (``in_app_enabled=True``, ``email_enabled=True``,
        ``updated_at=None``).

        Args:
            identity: The authenticated caller.

        Returns:
            One ``NotificationPreference`` per ``NotificationType``.
        """
        try:
            configured = self._preference_repo.get_for_user(identity.user_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        by_type = {record.notification_type: record for record in configured}
        return [
            NotificationPreference(
                notification_type=notification_type,
                in_app_enabled=by_type[notification_type].in_app_enabled,
                email_enabled=by_type[notification_type].email_enabled,
                updated_at=by_type[notification_type].updated_at,
            )
            if notification_type in by_type
            else NotificationPreference(
                notification_type=notification_type,
                in_app_enabled=_DEFAULT_PREFERENCE[0],
                email_enabled=_DEFAULT_PREFERENCE[1],
                updated_at=None,
            )
            for notification_type in NotificationType
        ]

    @log_calls()
    def update_preference(
        self,
        identity: AuthenticatedIdentity,
        notification_type: NotificationType,
        *,
        in_app_enabled: bool | None = None,
        email_enabled: bool | None = None,
    ) -> NotificationPreference:
        """Set the caller's preference for one notification type.

        Partial-patch semantics, matching ``PartialUpdateModel``'s
        convention elsewhere: a field left as ``None`` keeps its current
        effective value (the caller's existing preference, or the
        default if never configured) rather than being reset.

        Args:
            identity: The authenticated caller.
            notification_type: The notification category being configured.
            in_app_enabled: Whether this event should be recorded in-app
                (and therefore, transitively, ever emailed) going
                forward, or ``None`` to leave unchanged.
            email_enabled: Whether this event should also be emailed,
                when ``in_app_enabled`` is ``True``, or ``None`` to leave
                unchanged.

        Returns:
            The resulting ``NotificationPreference``.
        """
        current_in_app, current_email = self._effective_preference(
            identity.user_id, notification_type
        )
        try:
            record = self._preference_repo.upsert(
                identity.user_id,
                notification_type,
                in_app_enabled=in_app_enabled if in_app_enabled is not None else current_in_app,
                email_enabled=email_enabled if email_enabled is not None else current_email,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return NotificationPreference(
            notification_type=record.notification_type,
            in_app_enabled=record.in_app_enabled,
            email_enabled=record.email_enabled,
            updated_at=record.updated_at,
        )

    def _effective_preference(
        self, recipient_id: UUID, notification_type: NotificationType
    ) -> tuple[bool, bool]:
        """Return ``(in_app_enabled, email_enabled)`` for a recipient/type pair.

        Args:
            recipient_id: The notification's recipient.
            notification_type: The notification's category.

        Returns:
            The recipient's stored preference, or ``_DEFAULT_PREFERENCE``
            (both ``True``) if they have never configured this type —
            reproducing this service's original, unconditional behavior.
        """
        try:
            configured = self._preference_repo.get_for_user(recipient_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        for record in configured:
            if record.notification_type is notification_type:
                return (record.in_app_enabled, record.email_enabled)
        return _DEFAULT_PREFERENCE

    def _create_and_dispatch(
        self,
        *,
        recipient_id: UUID,
        request_id: UUID | None,
        notification_type: NotificationType,
        message: str,
    ) -> Notification | None:
        """Create a notification and attempt email dispatch, independently.

        Args:
            recipient_id: The notification's recipient.
            request_id: The related request, if any.
            notification_type: The notification's category.
            message: The notification body.

        Returns:
            The created ``Notification``, or ``None`` if the recipient
            has disabled in-app delivery for this notification type (in
            which case no row is created at all, and no email is sent
            either — there is nothing to attach delivery metadata to).
        """
        in_app_enabled, email_enabled = self._effective_preference(recipient_id, notification_type)
        if not in_app_enabled:
            self._logger.debug(
                "Notification suppressed for recipient %s: in-app delivery disabled for %s.",
                recipient_id,
                notification_type.value,
            )
            return None

        try:
            created = self._notification_repo.create_notification(
                recipient_id=recipient_id,
                notification_type=notification_type,
                message=message,
                request_id=request_id,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        if not email_enabled:
            return map_notification_record_to_domain(created)

        # Dispatch runs through `self._email_executor`: synchronously, in
        # this call stack, with the default `_ImmediateExecutor` (so
        # `outcome[0]` is already updated by the time `submit()` returns
        # below, and this method's return value reflects the dispatch
        # outcome exactly as it always has); or on a background thread
        # with `ThreadPoolEmailDispatchExecutor` (so `submit()` returns
        # immediately, `outcome[0]` is still the just-created,
        # `email_sent=False` record, and the notification row is updated
        # asynchronously once the background send completes). Either way,
        # `created` itself is never mutated in place, since every
        # repository record is an immutable dataclass.
        outcome = [created]

        def _dispatch() -> None:
            outcome[0] = self._attempt_email_dispatch(created)

        self._email_executor.submit(_dispatch)
        return map_notification_record_to_domain(outcome[0])

    def _attempt_email_dispatch(self, notification: NotificationRecord) -> NotificationRecord:
        """Attempt to dispatch a notification's corresponding email.

        Per WEDD Section 15.2, email dispatch is independent of the
        notification's own creation: a failure here is logged and
        suppressed, never propagated, and never reverses the
        already-committed in-app notification.

        Args:
            notification: The notification to dispatch an email for.

        Returns:
            The notification record with ``email_sent``/``email_sent_at``
            populated if dispatch succeeded; the original, unchanged
            record if dispatch was skipped, reported failure, or raised.
        """
        if self._email_sender is None:
            self._logger.debug(
                "Email dispatch skipped for notification %s: no EmailSender configured.",
                notification.id,
            )
            return notification

        try:
            sent = self._email_sender.send(
                to_address=str(notification.recipient_id),
                subject=f"{self._subject_prefix} {notification.notification_type.value.title()}",
                body=notification.message,
            )
        except Exception as exc:  # noqa: BLE001 - a sender failure must never propagate
            self._logger.warning(
                "Email dispatch raised for notification %s: %s", notification.id, exc, exc_info=exc
            )
            return notification

        if sent:
            return self._notification_repo.mark_email_sent(notification.id)
        self._logger.warning("Email dispatch reported failure for notification %s", notification.id)
        return notification
