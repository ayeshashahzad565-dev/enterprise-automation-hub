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
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.auth.authentication import AuthenticatedIdentity
from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.notification_repository import (
    NotificationRecord,
    NotificationRepository,
)
from app.models import Notification
from app.models.enums import NotificationType
from app.services.exceptions import PermissionDeniedError, translate_database_error
from app.utils.decorators import log_calls, suppress_and_log

__all__ = ["EmailSender", "map_notification_record_to_domain", "NotificationService"]

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
        created_at=record.created_at,
    )


class NotificationService:
    """Orchestrates notification creation, email dispatch, and read access."""

    def __init__(
        self,
        *,
        notification_repo: NotificationRepository,
        email_sender: EmailSender | None = None,
        default_email_subject_prefix: str = "[Enterprise Automation Hub]",
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            notification_repo: Persistence for ``notifications``.
            email_sender: An implementation of ``EmailSender``, or
                ``None`` to disable email dispatch entirely (matching
                the Deployment Guide's allowance for Development/Testing
                environments to disable email, DG Section 8.1).
            default_email_subject_prefix: A fixed prefix applied to every
                dispatched email's subject line.
        """
        self._notification_repo = notification_repo
        self._email_sender = email_sender
        self._subject_prefix = default_email_subject_prefix
        self._logger = logging.getLogger(f"{__name__}.NotificationService")

    @log_calls()
    def notify_assignment(self, *, recipient_id: UUID, request_id: UUID, message: str) -> Notification:
        """Create and dispatch an ``assignment`` notification.

        Args:
            recipient_id: The user newly assigned to a stage.
            request_id: The related request.
            message: The notification body.

        Returns:
            The created ``Notification``.
        """
        return self._create_and_dispatch(
            recipient_id=recipient_id,
            request_id=request_id,
            notification_type=NotificationType.ASSIGNMENT,
            message=message,
        )

    @log_calls()
    def notify_reminder(self, *, recipient_id: UUID, request_id: UUID, message: str) -> Notification:
        """Create and dispatch a ``reminder`` notification.

        Invoked by the Scheduler's Reminder Dispatch job (WEDD Section
        8.3) for stages nearing, but not yet past, their escalation
        threshold.

        Args:
            recipient_id: The current assignee.
            request_id: The related request.
            message: The notification body.

        Returns:
            The created ``Notification``.
        """
        return self._create_and_dispatch(
            recipient_id=recipient_id,
            request_id=request_id,
            notification_type=NotificationType.REMINDER,
            message=message,
        )

    @log_calls()
    def notify_escalation(self, *, recipient_id: UUID, request_id: UUID, message: str) -> Notification:
        """Create and dispatch an ``escalation`` notification.

        Invoked by ``ApprovalService.escalate_stage`` following the
        Scheduler's Escalation Check job (WEDD Section 8.4).

        Args:
            recipient_id: The newly (re)assigned user.
            request_id: The related request.
            message: The notification body.

        Returns:
            The created ``Notification``.
        """
        return self._create_and_dispatch(
            recipient_id=recipient_id,
            request_id=request_id,
            notification_type=NotificationType.ESCALATION,
            message=message,
        )

    @log_calls()
    def notify_decision(self, *, recipient_id: UUID, request_id: UUID, message: str) -> Notification:
        """Create and dispatch a ``decision`` notification.

        Per WEDD Section 15.1, used for a stage rejection, notifying the
        requester.

        Args:
            recipient_id: The requester.
            request_id: The related request.
            message: The notification body.

        Returns:
            The created ``Notification``.
        """
        return self._create_and_dispatch(
            recipient_id=recipient_id,
            request_id=request_id,
            notification_type=NotificationType.DECISION,
            message=message,
        )

    @log_calls()
    def notify_completion(self, *, recipient_id: UUID, request_id: UUID, message: str) -> Notification:
        """Create and dispatch a ``completion`` notification.

        Args:
            recipient_id: The requester.
            request_id: The related request.
            message: The notification body.

        Returns:
            The created ``Notification``.
        """
        return self._create_and_dispatch(
            recipient_id=recipient_id,
            request_id=request_id,
            notification_type=NotificationType.COMPLETION,
            message=message,
        )

    @log_calls()
    def notify_system(self, *, recipient_id: UUID, message: str) -> Notification:
        """Create and dispatch a ``system`` notification, unrelated to any request.

        Args:
            recipient_id: The recipient.
            message: The notification body.

        Returns:
            The created ``Notification``.
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
        page: Page = Page(),
    ) -> PagedResult[Notification]:
        """List the caller's own notifications.

        Args:
            identity: The authenticated caller.
            is_read: Restrict to read or unread notifications, if
                provided.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of the caller's own ``Notification`` instances.
        """
        try:
            result = self._notification_repo.list_for_recipient(
                identity.user_id, is_read=is_read, page=page
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
        try:
            existing = self._notification_repo.get_by_id(notification_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc

        if existing.recipient_id != identity.user_id:
            raise PermissionDeniedError(
                "Only a notification's own recipient may mark it as read."
            )

        try:
            updated = self._notification_repo.mark_read(notification_id)
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

    def _create_and_dispatch(
        self,
        *,
        recipient_id: UUID,
        request_id: UUID | None,
        notification_type: NotificationType,
        message: str,
    ) -> Notification:
        """Create a notification and attempt email dispatch, independently.

        Args:
            recipient_id: The notification's recipient.
            request_id: The related request, if any.
            notification_type: The notification's category.
            message: The notification body.

        Returns:
            The created ``Notification``.
        """
        try:
            created = self._notification_repo.create_notification(
                recipient_id=recipient_id,
                notification_type=notification_type,
                message=message,
                request_id=request_id,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._attempt_email_dispatch(created)
        return map_notification_record_to_domain(created)

    @suppress_and_log(Exception, default=None)
    def _attempt_email_dispatch(self, notification: NotificationRecord) -> None:
        """Attempt to dispatch a notification's corresponding email.

        Per WEDD Section 15.2, email dispatch is independent of the
        notification's own creation: a failure here is logged (via
        ``suppress_and_log``) and never propagates, and never reverses
        the already-committed in-app notification.

        Args:
            notification: The notification to dispatch an email for.
        """
        if self._email_sender is None:
            self._logger.debug(
                "Email dispatch skipped for notification %s: no EmailSender configured.",
                notification.id,
            )
            return

        sent = self._email_sender.send(
            to_address=str(notification.recipient_id),
            subject=f"{self._subject_prefix} {notification.notification_type.value.title()}",
            body=notification.message,
        )
        if sent:
            self._notification_repo.mark_email_sent(notification.id)
        else:
            self._logger.warning(
                "Email dispatch reported failure for notification %s", notification.id
            )