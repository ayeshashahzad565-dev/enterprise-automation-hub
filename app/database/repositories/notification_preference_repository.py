"""Repository for the ``notification_preferences`` table.

Per-user, per-``notification_type`` delivery overrides. ``NotificationType``
is re-exported here from ``app.models.enums``, matching
``notification_repository.py``'s own re-export convention, purely so a
call site importing from this module never needs a second import from
``app.models.enums`` just for the same enum.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.repositories.base_repository import BaseRepository, parse_datetime, parse_uuid
from app.models.enums import NotificationType

logger = logging.getLogger(__name__)

__all__ = ["NotificationType", "NotificationPreferenceRecord", "NotificationPreferenceRepository"]


@dataclass(frozen=True, slots=True)
class NotificationPreferenceRecord:
    """An immutable, persistence-level representation of one
    ``notification_preferences`` row.

    Attributes:
        id: Primary key.
        user_id: The user this preference belongs to.
        notification_type: The notification category this preference
            applies to.
        in_app_enabled: Whether this event is recorded in-app at all.
        email_enabled: Whether this event is also emailed.
        created_at: Row creation timestamp.
        updated_at: Last modification timestamp.
    """

    id: UUID
    user_id: UUID
    notification_type: NotificationType
    in_app_enabled: bool
    email_enabled: bool
    created_at: datetime
    updated_at: datetime


def _map_preference_row(row: dict[str, Any]) -> NotificationPreferenceRecord:
    """Map a raw Supabase row dict into a ``NotificationPreferenceRecord``."""
    return NotificationPreferenceRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        user_id=parse_uuid(row["user_id"]),  # type: ignore[arg-type]
        notification_type=NotificationType(row["notification_type"]),
        in_app_enabled=row["in_app_enabled"],
        email_enabled=row["email_enabled"],
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
        updated_at=parse_datetime(row["updated_at"]),  # type: ignore[arg-type]
    )


class NotificationPreferenceRepository(BaseRepository[NotificationPreferenceRecord]):
    """Persistence operations for the ``notification_preferences`` table."""

    table_name = "notification_preferences"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def get_for_user(self, user_id: UUID) -> list[NotificationPreferenceRecord]:
        """Fetch every explicitly configured preference for a user.

        A ``NotificationType`` with no row here means "use the default"
        (both flags ``True``) — this method returns only rows that
        actually exist; synthesizing the full fixed set of types with
        their defaults is the Application Layer's responsibility
        (``NotificationService.list_preferences``), not this repository's.

        Args:
            user_id: The user's id.

        Returns:
            The user's explicitly configured preference rows, in no
            particular order. At most one row per ``NotificationType``,
            per the table's unique constraint.
        """
        response = self._execute(
            self._select("*").eq("user_id", str(user_id)),
            operation="get_for_user",
        )
        return [_map_preference_row(row) for row in self._rows(response)]

    def upsert(
        self,
        user_id: UUID,
        notification_type: NotificationType,
        *,
        in_app_enabled: bool,
        email_enabled: bool,
    ) -> NotificationPreferenceRecord:
        """Create or replace a user's preference for one notification type.

        A single ``INSERT ... ON CONFLICT (user_id, notification_type) DO
        UPDATE`` round trip rather than a read-then-insert-or-update
        sequence, avoiding a race between two concurrent writes for the
        same ``(user_id, notification_type)`` pair.

        Args:
            user_id: The user's id.
            notification_type: The notification category being configured.
            in_app_enabled: Whether this event should be recorded in-app.
            email_enabled: Whether this event should also be emailed.

        Returns:
            The resulting ``NotificationPreferenceRecord``.
        """
        values: dict[str, Any] = {
            "user_id": str(user_id),
            "notification_type": notification_type.value,
            "in_app_enabled": in_app_enabled,
            "email_enabled": email_enabled,
        }
        response = self._execute(
            self._query().upsert(values, on_conflict="user_id,notification_type"),
            operation="upsert",
        )
        row = self._single_row(response, identifier=(user_id, notification_type))
        return _map_preference_row(row)
