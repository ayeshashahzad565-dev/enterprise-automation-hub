"""HTTP-only schema for the ``notifications`` resource.

``app.models.Notification`` is already a fully validated Pydantic domain
model with exactly the fields the client needs — this wrapper exists for
exactly one reason: ``Notification.is_archived`` is a plain ``@property``,
not a Pydantic ``@computed_field``, so it is silently dropped by
``model_dump()``/``app.utils.serialization.serialize`` unless re-declared
as an explicit field here. Every other field is a straight passthrough,
validated via ``from_attributes=True`` (the same "read via getattr,
duplicate no logic" technique this API layer already uses for wrapping
plain dataclasses in ``app.api.schemas.analytics``).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ConfigDict

from app.models.base import EAHBaseModel, UTCDatetime
from app.models.enums import NotificationType

__all__ = ["NotificationOut"]


class NotificationOut(EAHBaseModel):
    """Wraps ``app.models.Notification``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    id: UUID
    recipient_id: UUID
    request_id: UUID | None
    notification_type: NotificationType
    message: str
    is_read: bool
    read_at: UTCDatetime | None
    email_sent: bool
    email_sent_at: UTCDatetime | None
    archived_at: UTCDatetime | None
    is_archived: bool
    created_at: UTCDatetime
