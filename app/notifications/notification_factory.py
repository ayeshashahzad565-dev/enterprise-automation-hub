"""Notification payload construction.

Per this package's design brief, ``NotificationFactory`` builds
notification payloads — title, message, notification type, recipient,
and metadata — and performs no persistence and no delivery of any kind.
It depends on an injected ``TemplateRenderer`` to turn a
``NotificationEvent`` and a plain context mapping into rendered content.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import UUID

from app.models.enums import NotificationType
from app.notifications.interfaces import TemplateRenderer
from app.notifications.templates import EVENT_TO_NOTIFICATION_TYPE, NotificationEvent

__all__ = ["NotificationPayload", "NotificationFactory"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NotificationPayload:
    """A fully assembled, ready-to-deliver notification payload.

    Attributes:
        recipient_id: The user this notification is directed at.
        request_id: The related request, if any (``None`` for a
            system-level notification, per DSD Section 3.7).
        event: The rendering-level event this payload was built for.
        notification_type: The DSD-fixed persistence-level category this
            payload maps to (``EVENT_TO_NOTIFICATION_TYPE``).
        title: The rendered, short summary line.
        message: The rendered, plain-text body.
        html_message: The rendered HTML body, for channels that can
            display rich content.
        metadata: Arbitrary, caller-supplied structured data to retain
            alongside the notification (not persisted by the
            ``notifications`` table itself, per DSD Section 3.7, but
            available to delivery channels — for example, a channel
            that logs additional context).
        recipient_email: The recipient's email address, if the caller
            already resolved one. This package has no dependency capable
            of resolving a user id to an email address itself — per DSD
            Section 3.1, ``profiles`` carries no email column, and this
            package makes no Supabase Auth Admin API calls — so a
            caller wishing to receive an email notification must supply
            this value explicitly; if omitted, the email channel skips
            delivery gracefully rather than failing.
    """

    recipient_id: UUID
    request_id: UUID | None
    event: NotificationEvent
    notification_type: NotificationType
    title: str
    message: str
    html_message: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    recipient_email: str | None = None


class NotificationFactory:
    """Builds ``NotificationPayload`` instances from a rendered template.

    Performs no persistence and no delivery — see this module's
    docstring.
    """

    def __init__(self, *, template_renderer: TemplateRenderer) -> None:
        """Initialize the factory with an injected template renderer.

        Args:
            template_renderer: Any object satisfying the
                ``TemplateRenderer`` protocol.
        """
        self._template_renderer = template_renderer

    def build(
        self,
        event: NotificationEvent,
        *,
        recipient_id: UUID,
        request_id: UUID | None,
        context: Mapping[str, Any],
        recipient_email: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> NotificationPayload:
        """Build a notification payload for a given event.

        Args:
            event: The notification event to build a payload for.
            recipient_id: The user this notification is directed at.
            request_id: The related request, if any.
            context: The placeholder values used to render this event's
                template.
            recipient_email: The recipient's email address, if already
                known (see ``NotificationPayload.recipient_email``).
            metadata: Arbitrary additional structured data to attach.

        Returns:
            The fully assembled ``NotificationPayload``.

        Raises:
            TemplateRenderingError: If the event's template cannot be
                rendered against ``context``.
        """
        rendered = self._template_renderer.render(event, context)
        notification_type = EVENT_TO_NOTIFICATION_TYPE[event]

        logger.debug(
            "Built notification payload: event=%s, recipient_id=%s, request_id=%s",
            event.value,
            recipient_id,
            request_id,
            extra={"event": event.value, "recipient_id": str(recipient_id)},
        )

        return NotificationPayload(
            recipient_id=recipient_id,
            request_id=request_id,
            event=event,
            notification_type=notification_type,
            title=rendered.title,
            message=rendered.message,
            html_message=rendered.html_message,
            metadata=dict(metadata) if metadata else {},
            recipient_email=recipient_email,
        )