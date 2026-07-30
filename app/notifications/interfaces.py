"""Protocols for app.notifications.

This module defines a single abstraction: ``EmailProvider`` (Protocol) —
the SMTP-level abstraction a concrete email implementation satisfies.
Deliberately the lowest-level interface in this package, with no
knowledge of notification events, templates, or persistence, so that
``app.services.invitation_email.SmtpInvitationEmailSender`` and
``app.bootstrap``'s adapter for ``app.services.notification_service.
NotificationService`` can both depend on this structural type rather than
the concrete ``app.notifications.email_sender.SmtpEmailProvider`` class.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmailProvider(Protocol):
    """Structural interface for the SMTP-level email delivery capability.

    This is deliberately the lowest-level abstraction in this package: an
    implementation knows nothing about notification events, templates, or
    persistence — only how to send one email to one address.
    """

    def send_email(
        self,
        *,
        to_address: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
    ) -> None:
        """Send a single email, retrying transient failures internally.

        Args:
            to_address: The recipient's email address.
            subject: The email subject line.
            text_body: The plain-text email body.
            html_body: The HTML email body, if the message supports rich
                content. When provided, implementations are expected to
                send a multipart message offering both representations.

        Raises:
            EmailDeliveryError: If the email could not be delivered after
                every configured retry attempt was exhausted, or a
                non-retryable failure occurred.
        """
        ...
