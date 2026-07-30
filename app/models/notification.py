"""Domain models for the ``notifications`` table.

Per DSD Section 3.7 and WEDD Section 15, this table stores every
notification generated for a user, whether triggered synchronously by a
request-lifecycle event or asynchronously by the Scheduler. Corresponds
to the persistence layer's
``app.database.repositories.notification_repository.NotificationRepository``.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.models.base import EAHBaseModel, IdentifiedModel, TimestampedModel, UTCDatetime
from app.models.enums import NotificationType

__all__ = ["Notification", "NotificationCreate"]


class Notification(IdentifiedModel, TimestampedModel):
    """A fully validated, persisted representation of a ``notifications``
    row.

    Mirrors DSD Section 3.7's column list exactly and corresponds
    directly to
    ``app.database.repositories.notification_repository.NotificationRecord``.

    Attributes:
        recipient_id: The user this notification is directed at.
        request_id: The related request, if any.
        notification_type: The notification's category (WEDD Section
            15.1).
        message: The notification body.
        is_read: Whether the recipient has viewed the notification.
        read_at: The timestamp the notification was marked read, if any.
        email_sent: Whether the corresponding email was dispatched
            successfully.
        email_sent_at: The timestamp of successful email dispatch, if
            any.
        archived_at: The timestamp the recipient archived this
            notification, if any. Archiving only removes a notification
            from the recipient's default, active view — unlike the
            soft-deletable tables (DSD Section 3.10), an archived
            notification is not hidden from every view, only from the
            default one, and it is fully reversible.
    """

    recipient_id: UUID
    request_id: UUID | None = None
    notification_type: NotificationType
    message: str = Field(min_length=1)
    is_read: bool
    read_at: UTCDatetime | None = None
    email_sent: bool
    email_sent_at: UTCDatetime | None = None
    archived_at: UTCDatetime | None = None

    @property
    def is_archived(self) -> bool:
        """Whether the recipient has archived this notification."""
        return self.archived_at is not None


class NotificationCreate(EAHBaseModel):
    """Input model for creating a new notification.

    Constructed internally by ``NotificationService`` (per the ADD's
    Notification Service description and WEDD Section 15.1) at each of
    the notification-generation points enumerated there — this is not a
    client-facing API request body, since notifications are always
    system-generated, never submitted directly by a user.

    Attributes:
        recipient_id: The user this notification is directed at.
        notification_type: The notification's category.
        message: The notification body.
        request_id: The related request, if any (``None`` for
            system-level notifications, per DSD Section 3.7).
    """

    recipient_id: UUID
    notification_type: NotificationType
    message: str = Field(min_length=1)
    request_id: UUID | None = None
