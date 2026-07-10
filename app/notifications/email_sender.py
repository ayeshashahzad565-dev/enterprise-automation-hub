"""SMTP-based email delivery.

Per this package's design brief, this module provides an SMTP
abstraction only — no notification-event or template knowledge lives
here beyond what is needed to send one email. Configuration is read
exclusively from ``app.config.settings.SmtpSettings`` (never
hardcoded), retry of transient failures uses
``app.utils.retry.RetryPolicy``/``retry_call``, and every send attempt is
bounded by a configurable connection timeout.

This module defines two classes:

- ``SmtpEmailProvider``: implements ``EmailProvider`` (the low-level SMTP
  capability).
- ``EmailNotificationChannel``: implements ``NotificationChannel``,
  adapting an injected ``EmailProvider`` to the channel interface
  ``NotificationManager`` invokes uniformly, including the graceful
  no-recipient-address skip described in ``notification_factory``'s
  docstring.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config.settings import SmtpSettings
from app.notifications.exceptions import EmailDeliveryError, NotificationConfigurationError
from app.notifications.interfaces import ChannelDeliveryResult, NotificationChannel
from app.notifications.notification_factory import NotificationPayload
from app.utils.retry import RetryPolicy, retry_call

__all__ = ["SmtpEmailProvider", "EmailNotificationChannel"]

logger = logging.getLogger(__name__)

#: The default connection/operation timeout, in seconds, applied to every
#: SMTP operation this module performs.
_DEFAULT_TIMEOUT_SECONDS = 10.0

#: The SMTP-layer exception types treated as transient and therefore
#: eligible for retry. Deliberately excludes authentication and
#: recipient-refusal failures (``smtplib.SMTPAuthenticationError``,
#: ``smtplib.SMTPRecipientsRefused``), which are permanent and should
#: fail immediately rather than being retried.
_RETRYABLE_SMTP_EXCEPTIONS: tuple[type[BaseException], ...] = (
    smtplib.SMTPConnectError,
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPHeloError,
    TimeoutError,
    ConnectionError,
    OSError,
)


class SmtpEmailProvider:
    """An ``EmailProvider`` implementation backed by Python's standard ``smtplib``.

    No third-party email library is introduced, consistent with the
    fixed technology stack.
    """

    def __init__(
        self,
        *,
        settings: SmtpSettings,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """Initialize the provider with injected SMTP configuration.

        Args:
            settings: The SMTP connection settings, sourced from
                ``app.config.settings.load_settings().smtp`` — never
                hardcoded.
            timeout_seconds: The connection/operation timeout applied to
                every SMTP call.
            retry_policy: The retry policy governing transient-failure
                retries. Defaults to a policy scoped specifically to the
                transient SMTP exception types this module recognizes,
                rather than ``app.utils.retry.DEFAULT_RETRY_POLICY``'s
                catch-all ``Exception``, so that a permanent failure
                (bad credentials) is never mistakenly retried.

        Raises:
            NotificationConfigurationError: If ``settings.is_enabled`` is
                ``False`` — constructing a provider from disabled
                settings would silently produce a provider that can
                never succeed, which is a configuration error, not a
                runtime condition to degrade from.
        """
        if not settings.is_enabled:
            raise NotificationConfigurationError(
                "Cannot construct an SmtpEmailProvider: SMTP is not configured "
                "(app.config.settings.SmtpSettings.is_enabled is False)."
            )
        self._settings = settings
        self._timeout_seconds = timeout_seconds
        self._retry_policy = retry_policy or RetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.5,
            backoff_multiplier=2.0,
            max_delay_seconds=5.0,
            jitter=True,
            retryable_exceptions=_RETRYABLE_SMTP_EXCEPTIONS,
        )
        self._logger = logging.getLogger(f"{__name__}.SmtpEmailProvider")

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
            html_body: The HTML email body, if provided. When present,
                the outgoing message is a ``multipart/alternative``
                offering both representations.

        Raises:
            EmailDeliveryError: If delivery fails after every configured
                retry attempt, or a non-retryable SMTP failure occurs
                (e.g. authentication failure, recipient refused).
        """
        message = self._build_message(
            to_address=to_address, subject=subject, text_body=text_body, html_body=html_body
        )

        try:
            retry_call(
                lambda: self._send_once(to_address=to_address, message=message),
                policy=self._retry_policy,
            )
        except _RETRYABLE_SMTP_EXCEPTIONS as exc:
            # Every retry attempt was exhausted; retry_call wraps this in
            # RetryExhaustedError, but we re-raise translated below via
            # the broader except clause instead, so catch nothing extra
            # here — this branch exists only for documentation clarity
            # and is unreachable given retry_call's own translation.
            raise EmailDeliveryError(to_address, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - translated into a typed error below
            self._logger.error(
                "Failed to send email to %s: %s", to_address, exc, exc_info=exc,
                extra={"to_address": to_address},
            )
            raise EmailDeliveryError(to_address, str(exc)) from exc

        self._logger.info(
            "Email sent to %s (subject=%r)", to_address, subject,
            extra={"to_address": to_address},
        )

    def _send_once(self, *, to_address: str, message: MIMEMultipart) -> None:
        """Perform a single SMTP send attempt.

        Args:
            to_address: The recipient's email address.
            message: The fully constructed MIME message.

        Raises:
            smtplib.SMTPException: On any SMTP-protocol-level failure.
            OSError: On a connection-level failure (including timeout).
        """
        with smtplib.SMTP(
            self._settings.host, self._settings.port, timeout=self._timeout_seconds
        ) as connection:
            connection.starttls()
            connection.login(self._settings.username, self._settings.password)
            connection.sendmail(self._settings.from_address, [to_address], message.as_string())

    def _build_message(
        self, *, to_address: str, subject: str, text_body: str, html_body: str | None
    ) -> MIMEMultipart:
        """Construct a MIME message, multipart if an HTML body is provided.

        Args:
            to_address: The recipient's email address.
            subject: The email subject line.
            text_body: The plain-text email body.
            html_body: The HTML email body, if any.

        Returns:
            The constructed ``MIMEMultipart`` message.
        """
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = self._settings.from_address
        message["To"] = to_address
        message.attach(MIMEText(text_body, "plain", "utf-8"))
        if html_body is not None:
            message.attach(MIMEText(html_body, "html", "utf-8"))
        return message


class EmailNotificationChannel(NotificationChannel):
    """Adapts an ``EmailProvider`` to the ``NotificationChannel`` interface.

    Contains no SMTP implementation details of its own — it delegates
    entirely to the injected ``EmailProvider`` and never raises for an
    ordinary delivery failure, reporting it via ``ChannelDeliveryResult``
    instead, per ``NotificationChannel``'s documented contract.
    """

    def __init__(self, *, email_provider: SmtpEmailProvider) -> None:
        """Initialize the channel with an injected email provider.

        Args:
            email_provider: Any object satisfying the ``EmailProvider``
                protocol.
        """
        self._email_provider = email_provider
        self._logger = logging.getLogger(f"{__name__}.EmailNotificationChannel")

    @property
    def channel_name(self) -> str:
        """This channel's stable identifier, ``"email"``."""
        return "email"

    def deliver(self, payload: NotificationPayload) -> ChannelDeliveryResult:
        """Attempt to deliver a notification payload via email.

        Args:
            payload: The notification payload to deliver.

        Returns:
            A ``ChannelDeliveryResult`` describing the outcome. If
            ``payload.recipient_email`` is ``None`` (see
            ``NotificationPayload``'s docstring for why this can happen),
            this method skips delivery and reports that outcome rather
            than treating it as a failure needing an exception.
        """
        if payload.recipient_email is None:
            self._logger.debug(
                "Skipping email delivery for notification to %s: no recipient email available.",
                payload.recipient_id,
                extra={"recipient_id": str(payload.recipient_id)},
            )
            return ChannelDeliveryResult(
                channel_name=self.channel_name,
                success=False,
                detail="no recipient email address was available",
            )

        try:
            self._email_provider.send_email(
                to_address=payload.recipient_email,
                subject=payload.title,
                text_body=payload.message,
                html_body=payload.html_message,
            )
        except EmailDeliveryError as exc:
            self._logger.warning(
                "Email channel delivery failed for recipient %s: %s",
                payload.recipient_id,
                exc,
                extra={"recipient_id": str(payload.recipient_id)},
            )
            return ChannelDeliveryResult(channel_name=self.channel_name, success=False, detail=str(exc))

        return ChannelDeliveryResult(channel_name=self.channel_name, success=True)