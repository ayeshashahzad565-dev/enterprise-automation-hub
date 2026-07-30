"""SMTP-based email delivery.

Per this package's design brief, this module provides an SMTP
abstraction only — no notification-event or template knowledge lives
here beyond what is needed to send one email. Configuration is read
exclusively from ``app.config.settings.SmtpSettings`` (never
hardcoded), retry of transient failures uses
``app.utils.retry.RetryPolicy``/``retry_call``, and every send attempt is
bounded by a configurable connection timeout.

This module defines one class, ``SmtpEmailProvider``, which implements
``EmailProvider`` (the low-level SMTP capability) — the SMTP mechanism
reused by ``app.services.notification_service.NotificationService`` (via
``app.bootstrap``'s ``_EmailSenderAdapter``), ``app.services.
invitation_email.SmtpInvitationEmailSender``, and ``app.jobs.handlers``'s
queued-email job handlers, so no second SMTP implementation exists
anywhere in this codebase.
"""

from __future__ import annotations

import logging
import smtplib
import socket
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid

from app.config.settings import SmtpSettings
from app.notifications.exceptions import EmailDeliveryError, NotificationConfigurationError
from app.utils.retry import RetryPolicy, retry_call

__all__ = ["SmtpEmailProvider"]

logger = logging.getLogger(__name__)

#: The default connection/operation timeout, in seconds, applied to every
#: SMTP operation this module performs.
_DEFAULT_TIMEOUT_SECONDS = 10.0

#: The SMTP-layer exception types treated as transient and therefore
#: eligible for retry. Deliberately excludes authentication and
#: recipient-refusal failures (``smtplib.SMTPAuthenticationError``,
#: ``smtplib.SMTPRecipientsRefused``), which are permanent and should
#: fail immediately rather than being retried.
#:
#: Per Milestone 9's Email Delivery Resilience audit: this tuple
#: previously included a bare ``OSError`` (intended to additionally catch
#: raw socket-level failures, e.g. DNS resolution errors, not already
#: covered by the more specific entries below) — but Python's
#: ``smtplib.SMTPException`` itself subclasses ``OSError`` (confirmed:
#: ``smtplib.SMTPException.__mro__`` includes ``OSError``), so that bare
#: entry silently caught *every* smtplib exception, including
#: ``SMTPAuthenticationError``/``SMTPRecipientsRefused`` — directly
#: contradicting this comment's own stated intent, and this class's
#: ``send_email`` docstring, which both already documented "excluded,
#: fails immediately" as the intended behavior. ``socket.gaierror``
#: (DNS resolution failure) replaces the bare ``OSError`` entry: it is
#: the specific, genuinely transient, non-smtplib case the blanket entry
#: was reasonably trying to cover, without also matching every smtplib
#: protocol-level exception. ``ConnectionRefusedError``/
#: ``ConnectionResetError``/``ConnectionAbortedError``/``BrokenPipeError``
#: remain covered via ``ConnectionError`` below (all four are its
#: subclasses); ``socket.timeout`` is an alias of ``TimeoutError`` as of
#: Python 3.10, already covered too.
_RETRYABLE_SMTP_EXCEPTIONS: tuple[type[BaseException], ...] = (
    smtplib.SMTPConnectError,
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPHeloError,
    TimeoutError,
    ConnectionError,
    socket.gaierror,
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
                ``False``, or any individual field is unset despite
                ``host`` being present — constructing a provider from
                disabled or incomplete settings would silently produce a
                provider that can never succeed, which is a
                configuration error, not a runtime condition to degrade
                from.
        """
        if not settings.is_enabled:
            raise NotificationConfigurationError(
                "Cannot construct an SmtpEmailProvider: SMTP is not configured "
                "(app.config.settings.SmtpSettings.is_enabled is False)."
            )
        if (
            settings.host is None
            or settings.port is None
            or settings.username is None
            or settings.password is None
            or settings.from_address is None
        ):
            raise NotificationConfigurationError(
                "Cannot construct an SmtpEmailProvider: SMTP_HOST is set but "
                "SMTP_PORT/SMTP_USERNAME/SMTP_PASSWORD/SMTP_FROM_ADDRESS are "
                "not all set."
            )
        # Narrowed, non-Optional copies of the settings validated above —
        # SmtpSettings itself keeps every field Optional (host alone
        # gates is_enabled), so these are what _send_once/_build_message
        # actually use.
        self._host: str = settings.host
        self._port: int = settings.port
        self._username: str = settings.username
        self._password: str = settings.password
        self._from_address: str = settings.from_address
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
                "Failed to send email to %s: %s",
                to_address,
                exc,
                exc_info=exc,
                extra={"to_address": to_address},
            )
            raise EmailDeliveryError(to_address, str(exc)) from exc

        self._logger.info(
            "Email sent to %s (subject=%r)",
            to_address,
            subject,
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
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout_seconds) as connection:
            connection.starttls()
            connection.login(self._username, self._password)
            connection.sendmail(self._from_address, [to_address], message.as_string())

    def _build_message(
        self, *, to_address: str, subject: str, text_body: str, html_body: str | None
    ) -> MIMEMultipart:
        """Construct a MIME message, multipart if an HTML body is provided.

        Per Milestone 9's Email Delivery Resilience audit: this method is
        called exactly once per ``send_email`` call, *before*
        ``retry_call`` retries ``_send_once`` against the same message
        object — so the ``Message-ID`` generated here is identical across
        every retry attempt of one logical send. Without a stable
        ``Message-ID``, a retry after a delivery that actually succeeded
        server-side but failed client-side (e.g. the connection dropped
        while reading the server's final acknowledgement, a scenario
        ``_RETRYABLE_SMTP_EXCEPTIONS`` explicitly retries) would produce
        two messages a receiving mail system has no way to recognize as
        duplicates of each other. A stable id does not *guarantee*
        dedup — that is the receiving system's own behavior, outside this
        codebase's control — but it is the standard, minimal signal this
        codebase can provide, and does not exist without this call.

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
        message["From"] = self._from_address
        message["To"] = to_address
        message["Message-ID"] = make_msgid()
        message.attach(MIMEText(text_body, "plain", "utf-8"))
        if html_body is not None:
            message.attach(MIMEText(html_body, "html", "utf-8"))
        return message
