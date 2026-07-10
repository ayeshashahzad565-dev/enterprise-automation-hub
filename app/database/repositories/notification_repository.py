"""Repository for the ``notifications`` table.

Per DSD Section 3.7 and WEDD Section 15, this table stores every
notification generated for a user, whether triggered synchronously by a
request-lifecycle event or asynchronously by the Scheduler. This module
defines the ``NotificationType`` enum and the ``NotificationRepository``
class.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.repositories.base_repository import (
    BaseRepository,
    Page,
    PagedResult,
    parse_datetime,
    parse_uuid,
)

logger = logging.getLogger(__name__)


class NotificationType(str, Enum):
    """The six values fixed by DSD Section 1.5's ``notification_type`` enum."""

    ASSIGNMENT = "assignment"
    REMINDER = "reminder"
    ESCALATION = "escalation"
    DECISION = "decision"
    COMPLETION = "completion"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class NotificationRecord:
    """An immutable, persistence-level representation of one
    ``notifications`` row (DSD Section 3.7).

    Attributes:
        id: Primary key.
        recipient_id: The user this notification is directed at.
        request_id: The related request, if any.
        notification_type: The notification's category.
        message: The notification body.
        is_read: Whether the recipient has viewed the notification.
        read_at: The timestamp the notification was marked read, if any.
        email_sent: Whether the corresponding email was dispatched
            successfully.
        email_sent_at: The timestamp of successful email dispatch, if any.
        created_at: Notification creation timestamp.
    """

    id: UUID
    recipient_id: UUID
    request_id: UUID | None
    notification_type: NotificationType
    message: str
    is_read: bool
    read_at: datetime | None
    email_sent: bool
    email_sent_at: datetime | None
    created_at: datetime


def _map_notification_row(row: dict[str, Any]) -> NotificationRecord:
    """Map a raw Supabase row dict into a ``NotificationRecord``."""
    return NotificationRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        recipient_id=parse_uuid(row["recipient_id"]),  # type: ignore[arg-type]
        request_id=parse_uuid(row.get("request_id")),
        notification_type=NotificationType(row["notification_type"]),
        message=row["message"],
        is_read=row["is_read"],
        read_at=parse_datetime(row.get("read_at")),
        email_sent=row["email_sent"],
        email_sent_at=parse_datetime(row.get("email_sent_at")),
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


class NotificationRepository(BaseRepository[NotificationRecord]):
    """Persistence operations for the ``notifications`` table.

    Corresponds to ``NotificationService``'s persistence needs described
    in the ADD and WEDD Section 15.
    """

    table_name = "notifications"

    def __init__(self, client: DatabaseClient) -> None:
        super().__init__(client)

    def get_by_id(self, notification_id: UUID) -> NotificationRecord:  # type: ignore[override]
        """Fetch a notification by its id.

        Args:
            notification_id: The notification's ``id``.

        Returns:
            The matching ``NotificationRecord``.

        Raises:
            RecordNotFoundError: If no notification with this id exists or
                is visible under the current client's RLS context.
        """
        return super().get_by_id(notification_id, mapper=_map_notification_row)

    def create_notification(
        self,
        *,
        recipient_id: UUID,
        notification_type: NotificationType,
        message: str,
        request_id: UUID | None = None,
    ) -> NotificationRecord:
        """Insert a new, unread notification row.

        Per WEDD Section 15.2 and the ADD's Notification Service
        description, this insert is independent of any corresponding
        email dispatch — a failed email send never prevents or reverses
        this insert, and the caller marks ``email_sent`` via
        ``mark_email_sent`` as a separate, subsequent call.

        Args:
            recipient_id: The user this notification is directed at.
            notification_type: The notification's category.
            message: The notification body.
            request_id: The related request, if any (DSD Section 3.7
                permits ``None`` for system-level notifications).

        Returns:
            The newly created ``NotificationRecord``, with
            ``is_read = False`` and ``email_sent = False``.

        Raises:
            ConstraintViolationError: If ``recipient_id`` or
                ``request_id`` does not resolve to an existing row.
        """
        values: dict[str, Any] = {
            "recipient_id": str(recipient_id),
            "request_id": str(request_id) if request_id else None,
            "notification_type": notification_type.value,
            "message": message,
            "is_read": False,
            "email_sent": False,
        }
        return self.insert(values, mapper=_map_notification_row)

    def mark_read(self, notification_id: UUID) -> NotificationRecord:
        """Mark a notification as read.

        Corresponds to ``PATCH /api/v1/notifications/{id}/read`` (API-ADD
        Section 19.8.2), which is documented as idempotent: this method
        applies the same update regardless of whether the notification
        was already read, and does not raise if it was — a plain,
        unconditional update is used here rather than optimistic locking,
        since a notification's read status has no meaningful concurrent-
        writer conflict to guard against (only the recipient themselves
        ever changes it).

        Args:
            notification_id: The notification's ``id``.

        Returns:
            The updated ``NotificationRecord``, with ``is_read = True``.

        Raises:
            RecordNotFoundError: If no notification with this id exists or
                is visible under the current client's RLS context.
        """
        response = self._execute(
            self._query()
            .update(
                {
                    "is_read": True,
                    "read_at": datetime.now().astimezone().isoformat(),
                }
            )
            .eq("id", str(notification_id)),
            operation="mark_read",
        )
        row = self._single_row(response, identifier=notification_id)
        return _map_notification_row(row)

    def mark_email_sent(self, notification_id: UUID) -> NotificationRecord:
        """Record that a notification's corresponding email was dispatched.

        Args:
            notification_id: The notification's ``id``.

        Returns:
            The updated ``NotificationRecord``, with ``email_sent =
            True``.

        Raises:
            RecordNotFoundError: If no notification with this id exists.
        """
        response = self._execute(
            self._query()
            .update(
                {
                    "email_sent": True,
                    "email_sent_at": datetime.now().astimezone().isoformat(),
                }
            )
            .eq("id", str(notification_id)),
            operation="mark_email_sent",
        )
        row = self._single_row(response, identifier=notification_id)
        return _map_notification_row(row)

    def list_for_recipient(
        self,
        recipient_id: UUID,
        *,
        is_read: bool | None = None,
        page: Page = Page(),
    ) -> PagedResult[NotificationRecord]:
        """List notifications for a specific recipient.

        Corresponds to ``GET /api/v1/notifications`` (API-ADD Section
        19.8.1), backed by the composite index on ``(recipient_id,
        is_read)`` (DSD Section 10.2).

        Args:
            recipient_id: The recipient's user id.
            is_read: Restrict to read or unread notifications, if
                provided.
            page: The page to retrieve, newest first.

        Returns:
            A ``PagedResult`` of matching notifications.
        """
        builder = self._query().eq("recipient_id", str(recipient_id))
        if is_read is not None:
            builder = builder.eq("is_read", is_read)
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_notification_row)

    def get_unread_count(self, recipient_id: UUID) -> int:
        """Return the number of unread notifications for a recipient.

        Corresponds to ``GET /api/v1/notifications/unread-count`` (API-ADD
        Section 19.8.3), issuing a count-only query rather than fetching
        full notification rows.

        Args:
            recipient_id: The recipient's user id.

        Returns:
            The number of unread notifications.
        """
        builder = (
            self._query()
            .eq("recipient_id", str(recipient_id))
            .eq("is_read", False)
        )
        return self.count(builder)