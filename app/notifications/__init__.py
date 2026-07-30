"""A low-level SMTP toolkit, reused by three real call sites.

This package used to also contain a higher-level notification-event
orchestration stack (``NotificationManager``/``NotificationFactory``/
``InAppNotifier``/``templates``) that was constructed at startup but never
wired to any consumer — ``app.services.notification_service.
NotificationService`` was, and remains, the sole production notification
implementation. That dead stack was removed; what remains is the SMTP
plumbing genuinely shared across the codebase:

- ``exceptions``: ``NotificationError`` (base; also registered directly
  as a defensive FastAPI exception handler), ``EmailDeliveryError``, and
  ``NotificationConfigurationError``.
- ``interfaces``: ``EmailProvider``, the structural, SMTP-only protocol
  both this package's own implementation and
  ``app.services.invitation_email.SmtpInvitationEmailSender`` depend on.
- ``email_sender``: ``SmtpEmailProvider``, the one concrete
  ``EmailProvider`` implementation in this codebase — reused by
  ``app.bootstrap`` (wrapped for ``NotificationService``),
  ``app.services.invitation_email``, and ``app.jobs.handlers``.
"""

from __future__ import annotations

from app.notifications.email_sender import SmtpEmailProvider
from app.notifications.exceptions import (
    EmailDeliveryError,
    NotificationConfigurationError,
    NotificationError,
)
from app.notifications.interfaces import EmailProvider

__all__ = [
    "SmtpEmailProvider",
    "EmailDeliveryError",
    "NotificationConfigurationError",
    "NotificationError",
    "EmailProvider",
]
