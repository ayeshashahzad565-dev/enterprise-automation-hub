"""In-app notification persistence.

Per this package's design brief, ``InAppNotifier`` creates notification
records through the Repository Layer — nothing more. It contains no UI
logic and no read/unread management beyond the one follow-up field
(``email_sent``) that is a natural extension of "recording what happened
to this notification," not a read/unread concern.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.repositories.notification_repository import (
    NotificationRecord,
    NotificationRepository,
)
from app.notifications.exceptions import NotificationPersistenceError
from app.notifications.notification_factory import NotificationPayload

__all__ = ["InAppNotifier"]

logger = logging.getLogger(__name__)


class InAppNotifier:
    """Persists notification payloads as ``notifications`` rows.

    Depends on an injected ``NotificationRepository`` — this class issues
    no SQL of its own and constructs no Supabase client.
    """

    def __init__(self, *, notification_repo: NotificationRepository) -> None:
        """Initialize the notifier with an injected repository.

        Args:
            notification_repo: Persistence for the ``notifications``
                table.
        """
        self._notification_repo = notification_repo
        self._logger = logging.getLogger(f"{__name__}.InAppNotifier")

    def create(self, payload: NotificationPayload) -> NotificationRecord:
        """Create a new, unread notification record from a payload.

        Args:
            payload: The fully assembled notification payload to persist.

        Returns:
            The newly created ``NotificationRecord``.

        Raises:
            NotificationPersistenceError: If the underlying repository
                call fails for any reason (a missing recipient/request
                foreign key, a connectivity failure, or any other
                database-level error).
        """
        try:
            record = self._notification_repo.create_notification(
                recipient_id=payload.recipient_id,
                notification_type=payload.notification_type,
                message=payload.message,
                request_id=payload.request_id,
            )
        except DatabaseError as exc:
            self._logger.error(
                "Failed to persist notification for recipient %s: %s",
                payload.recipient_id,
                exc,
                exc_info=exc,
                extra={"recipient_id": str(payload.recipient_id)},
            )
            raise NotificationPersistenceError(
                f"Failed to persist notification for recipient {payload.recipient_id}: {exc}"
            ) from exc

        self._logger.info(
            "Persisted notification %s (type=%s) for recipient %s",
            record.id,
            payload.notification_type.value,
            payload.recipient_id,
            extra={"notification_id": str(record.id), "recipient_id": str(payload.recipient_id)},
        )
        return record

    def mark_email_sent(self, notification_id: UUID) -> NotificationRecord:
        """Record that a notification's corresponding email was dispatched.

        This is not a read/unread operation — it is the persistence-level
        record of a delivery-channel outcome, which
        ``NotificationManager`` calls after a successful email channel
        delivery.

        Args:
            notification_id: The notification's id.

        Returns:
            The updated ``NotificationRecord``.

        Raises:
            NotificationPersistenceError: If no notification with this id
                exists, or the update fails for any other reason.
        """
        try:
            return self._notification_repo.mark_email_sent(notification_id)
        except RecordNotFoundError as exc:
            raise NotificationPersistenceError(
                f"Cannot mark email sent: no notification {notification_id} exists."
            ) from exc
        except DatabaseError as exc:
            raise NotificationPersistenceError(
                f"Failed to mark notification {notification_id} as email-sent: {exc}"
            ) from exc