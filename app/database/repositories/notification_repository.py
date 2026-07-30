"""Repository for the ``notifications`` table.

Per DSD Section 3.7 and WEDD Section 15, this table stores every
notification generated for a user, whether triggered synchronously by a
request-lifecycle event or asynchronously by the Scheduler.
``NotificationType`` is re-exported here from ``app.models.enums`` (the
single canonical definition, per DSD Section 1.5) purely for backward
compatibility with existing call sites that import it from this module,
alongside the ``NotificationRepository`` class.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.repositories.base_repository import (
    BaseRepository,
    Page,
    PagedResult,
    escape_ilike_special_characters,
    parse_datetime,
    parse_uuid,
)
from app.models.enums import NotificationType

logger = logging.getLogger(__name__)

__all__ = ["NotificationType", "NotificationRecord", "NotificationRepository"]


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
        archived_at: The timestamp the recipient archived this
            notification, if any.
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
    archived_at: datetime | None
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
        archived_at=parse_datetime(row.get("archived_at")),
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


class NotificationRepository(BaseRepository[NotificationRecord]):
    """Persistence operations for the ``notifications`` table.

    Corresponds to ``NotificationService``'s persistence needs described
    in the ADD and WEDD Section 15.
    """

    table_name = "notifications"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

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

    def mark_all_read(self, recipient_id: UUID) -> int:
        """Mark every currently unread notification for a recipient as read.

        A single bulk update rather than one call per row, so "mark all
        read" is one round trip regardless of how many notifications are
        unread.

        Args:
            recipient_id: The recipient's user id.

        Returns:
            The number of notifications that were updated (``0`` if none
            were unread).
        """
        response = self._execute(
            self._query()
            .update(
                {
                    "is_read": True,
                    "read_at": datetime.now().astimezone().isoformat(),
                }
            )
            .eq("recipient_id", str(recipient_id))
            .eq("is_read", False),
            operation="mark_all_read",
        )
        return len(self._rows(response))

    def archive(self, notification_id: UUID) -> NotificationRecord:
        """Archive a notification, removing it from the recipient's default view.

        A plain, unconditional update, mirroring ``mark_read``'s own
        rationale: only the recipient themselves ever archives their own
        notification, so there is no concurrent-writer conflict to guard
        against with optimistic locking.

        Args:
            notification_id: The notification's ``id``.

        Returns:
            The updated ``NotificationRecord``, with ``archived_at`` set.

        Raises:
            RecordNotFoundError: If no notification with this id exists or
                is visible under the current client's RLS context.
        """
        response = self._execute(
            self._query()
            .update({"archived_at": datetime.now().astimezone().isoformat()})
            .eq("id", str(notification_id)),
            operation="archive",
        )
        row = self._single_row(response, identifier=notification_id)
        return _map_notification_row(row)

    def unarchive(self, notification_id: UUID) -> NotificationRecord:
        """Restore an archived notification to the recipient's default view.

        Args:
            notification_id: The notification's ``id``.

        Returns:
            The updated ``NotificationRecord``, with ``archived_at`` cleared.

        Raises:
            RecordNotFoundError: If no notification with this id exists or
                is visible under the current client's RLS context.
        """
        response = self._execute(
            self._query().update({"archived_at": None}).eq("id", str(notification_id)),
            operation="unarchive",
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
        notification_type: NotificationType | None = None,
        is_archived: bool | None = False,
        search: str | None = None,
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
            notification_type: Restrict to a single notification category,
                if provided.
            is_archived: Restrict to archived (``True``) or active
                (``False``) notifications. Defaults to ``False`` (the
                recipient's ordinary, active view); pass ``None`` to
                include both.
            search: Free-text search matched case-insensitively against
                ``message``, if provided. Escaped via
                ``escape_ilike_special_characters`` before being handed
                to ``.ilike()``, matching ``CommentRepository.search``'s
                own free-text-search shape.
            page: The page to retrieve, newest first.

        Returns:
            A ``PagedResult`` of matching notifications.
        """
        builder = self._select("*", count="exact").eq("recipient_id", str(recipient_id))
        if is_read is not None:
            builder = builder.eq("is_read", is_read)
        if notification_type is not None:
            builder = builder.eq("notification_type", notification_type.value)
        if is_archived is not None:
            builder = (
                builder.not_.is_("archived_at", "null")
                if is_archived
                else builder.is_("archived_at", "null")
            )
        if search:
            pattern = f"%{escape_ilike_special_characters(search.strip())}%"
            builder = builder.ilike("message", pattern)
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_notification_row)

    def search_for_recipient(
        self, query_text: str, recipient_id: UUID, *, page: Page = Page()
    ) -> PagedResult[NotificationRecord]:
        """Free-text search across one recipient's own notification messages.

        A dedicated entry point for ``GlobalSearchService`` over
        ``list_for_recipient``'s existing ``search`` parameter — every
        other cross-entity search method in this codebase (``search_requests``,
        ``CommentRepository.search``, ``AuditRepository.search``) has its
        own top-level method rather than being reached only through a
        broader listing method's optional filter, so this gives
        notifications the same shape. Includes both read and archived
        notifications (``is_archived=None``), unlike a recipient's
        ordinary notification list, since a global search should not
        silently hide an archived match.

        Args:
            query_text: The search term, matched against ``message`` via
                the ``notifications_message_trgm_idx`` trigram index
                (``0018_search_indexes``).
            recipient_id: Restricts results to this recipient only.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching notifications, newest first.
        """
        return self.list_for_recipient(
            recipient_id, is_archived=None, search=query_text, page=page
        )

    def get_unread_count(self, recipient_id: UUID) -> int:
        """Return the number of unread, active (non-archived) notifications
        for a recipient.

        Corresponds to ``GET /api/v1/notifications/unread-count`` (API-ADD
        Section 19.8.3), issuing a count-only query rather than fetching
        full notification rows. An archived notification never contributes
        to this count, since archiving is how a recipient signals a
        notification no longer needs their attention.

        Args:
            recipient_id: The recipient's user id.

        Returns:
            The number of unread, active notifications.
        """
        builder = (
            self._select("id", count="exact")
            .eq("recipient_id", str(recipient_id))
            .eq("is_read", False)
            .is_("archived_at", "null")
        )
        return self.count(builder)
