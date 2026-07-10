"""The Notification Layer for the Enterprise Automation Hub.

This package generates and delivers notifications after workflow events.
It is not responsible for deciding *when* a notification should occur —
per this package's design brief, that orchestration belongs to
``app.services``. This package contains:

- ``exceptions``: the typed exception hierarchy for template rendering,
  email delivery, in-app persistence, and configuration failures.
- ``interfaces``: the four protocols/ABCs this package's components
  satisfy — ``TemplateRenderer``, ``EmailProvider``,
  ``NotificationSender``, and ``NotificationChannel`` — plus the small
  value objects (``RenderedNotificationContent``,
  ``ChannelDeliveryResult``) passed between them.
- ``templates``: the fixed template registry for six notification
  events (assignment, approval, rejection, completion, reminder,
  escalation) and the default renderer.
- ``notification_factory``: builds ``NotificationPayload`` instances;
  performs no persistence and no delivery.
- ``email_sender``: an SMTP-backed ``EmailProvider`` implementation and
  its ``NotificationChannel`` adapter.
- ``in_app_notifier``: persists notifications through the Repository
  Layer.
- ``notification_manager``: coordinates the four components above into
  a single entry point for Application Services.

This module re-exports the public surface of every submodule so that
calling code (in particular, a future revision of
``app.services.notification_service``) can import from
``app.notifications`` directly.
"""

from __future__ import annotations

from app.notifications.email_sender import EmailNotificationChannel, SmtpEmailProvider
from app.notifications.exceptions import (
    EmailDeliveryError,
    NotificationConfigurationError,
    NotificationError,
    NotificationPersistenceError,
    TemplateRenderingError,
)
from app.notifications.in_app_notifier import InAppNotifier
from app.notifications.interfaces import (
    ChannelDeliveryResult,
    EmailProvider,
    NotificationChannel,
    NotificationSender,
    RenderedNotificationContent,
    TemplateRenderer,
)
from app.notifications.notification_factory import NotificationFactory, NotificationPayload
from app.notifications.notification_manager import DeliveryReport, NotificationManager
from app.notifications.templates import (
    EVENT_TO_NOTIFICATION_TYPE,
    TEMPLATE_REGISTRY,
    DefaultTemplateRenderer,
    NotificationEvent,
    NotificationTemplate,
)

__all__ = [
    # email_sender
    "EmailNotificationChannel",
    "SmtpEmailProvider",
    # exceptions
    "EmailDeliveryError",
    "NotificationConfigurationError",
    "NotificationError",
    "NotificationPersistenceError",
    "TemplateRenderingError",
    # in_app_notifier
    "InAppNotifier",
    # interfaces
    "ChannelDeliveryResult",
    "EmailProvider",
    "NotificationChannel",
    "NotificationSender",
    "RenderedNotificationContent",
    "TemplateRenderer",
    # notification_factory
    "NotificationFactory",
    "NotificationPayload",
    # notification_manager
    "DeliveryReport",
    "NotificationManager",
    # templates
    "EVENT_TO_NOTIFICATION_TYPE",
    "TEMPLATE_REGISTRY",
    "DefaultTemplateRenderer",
    "NotificationEvent",
    "NotificationTemplate",
]