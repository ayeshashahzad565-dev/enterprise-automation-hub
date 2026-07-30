"""Unit tests for ``app.notifications.email_sender.SmtpEmailProvider``.

No test file for this module existed before Milestone 9's Email Delivery
Resilience audit — every behavior asserted here (timeout propagation,
retry-then-succeed, non-retryable failures never retried, retry
exhaustion, the new stable ``Message-ID`` header, and that a delivery
failure's log line never includes the message body) is exercised for the
first time in this file.
"""

from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from app.config.settings import SmtpSettings
from app.notifications.email_sender import _RETRYABLE_SMTP_EXCEPTIONS, SmtpEmailProvider
from app.notifications.exceptions import EmailDeliveryError, NotificationConfigurationError
from app.utils.retry import RetryPolicy

pytestmark = pytest.mark.unit

_SETTINGS = SmtpSettings(
    host="smtp.example.com",
    port=587,
    username="apikey",
    password="s3cr3t-smtp-password",
    from_address="no-reply@example.com",
)

#: A fast policy for tests exercising retry behavior — real delays would
#: make the suite slow for no benefit; the specific delay values are not
#: under test here (app.utils.retry has its own tests for that).
#: ``retryable_exceptions`` reuses the module's own real set rather than
#: a hand-copied duplicate, so this policy can never silently drift from
#: production behavior the way a second, independently maintained tuple
#: could.
_FAST_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay_seconds=0.0,
    backoff_multiplier=1.0,
    max_delay_seconds=0.0,
    jitter=False,
    retryable_exceptions=_RETRYABLE_SMTP_EXCEPTIONS,
)


def _provider(**overrides) -> SmtpEmailProvider:
    kwargs = {"settings": _SETTINGS, "retry_policy": _FAST_RETRY_POLICY}
    kwargs.update(overrides)
    return SmtpEmailProvider(**kwargs)


class TestConstruction:
    def test_raises_when_smtp_is_not_enabled(self):
        disabled = SmtpSettings(
            host=None, port=None, username=None, password=None, from_address=None
        )

        with pytest.raises(NotificationConfigurationError):
            SmtpEmailProvider(settings=disabled)

    def test_raises_when_only_partially_configured(self):
        partial = SmtpSettings(
            host="smtp.example.com", port=None, username=None, password=None, from_address=None
        )

        with pytest.raises(NotificationConfigurationError):
            SmtpEmailProvider(settings=partial)


class TestSendEmail:
    def test_sends_successfully_on_the_first_attempt(self):
        provider = _provider()
        with patch("app.notifications.email_sender.smtplib.SMTP") as smtp_cls:
            connection = MagicMock()
            smtp_cls.return_value.__enter__.return_value = connection

            provider.send_email(to_address="a@example.com", subject="Hi", text_body="Hello")

            connection.starttls.assert_called_once()
            connection.login.assert_called_once_with("apikey", "s3cr3t-smtp-password")
            connection.sendmail.assert_called_once()

    def test_passes_the_configured_timeout_to_smtplib(self):
        provider = _provider(timeout_seconds=7.5)
        with patch("app.notifications.email_sender.smtplib.SMTP") as smtp_cls:
            smtp_cls.return_value.__enter__.return_value = MagicMock()

            provider.send_email(to_address="a@example.com", subject="Hi", text_body="Hello")

            smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=7.5)

    def test_uses_the_connection_as_a_context_manager_for_cleanup(self):
        # __exit__ is what closes/quits the connection even on failure -
        # asserting the mock was entered via `with` (not just constructed)
        # is the observable proxy for that cleanup happening.
        provider = _provider()
        with patch("app.notifications.email_sender.smtplib.SMTP") as smtp_cls:
            connection = MagicMock()
            smtp_cls.return_value.__enter__.return_value = connection

            provider.send_email(to_address="a@example.com", subject="Hi", text_body="Hello")

            smtp_cls.return_value.__enter__.assert_called_once()
            smtp_cls.return_value.__exit__.assert_called_once()

    def test_retries_a_transient_connection_error_and_then_succeeds(self):
        provider = _provider()
        connection = MagicMock()
        with patch("app.notifications.email_sender.smtplib.SMTP") as smtp_cls:
            smtp_cls.return_value.__enter__.side_effect = [
                smtplib.SMTPConnectError(421, "Service not available"),
                connection,
            ]

            provider.send_email(to_address="a@example.com", subject="Hi", text_body="Hello")

            assert smtp_cls.return_value.__enter__.call_count == 2
            connection.sendmail.assert_called_once()

    def test_exhausting_every_retry_raises_email_delivery_error(self):
        provider = _provider()
        with patch("app.notifications.email_sender.smtplib.SMTP") as smtp_cls:
            smtp_cls.return_value.__enter__.side_effect = smtplib.SMTPServerDisconnected(
                "Connection lost"
            )

            with pytest.raises(EmailDeliveryError):
                provider.send_email(to_address="a@example.com", subject="Hi", text_body="Hello")

            assert smtp_cls.return_value.__enter__.call_count == _FAST_RETRY_POLICY.max_attempts

    def test_an_authentication_failure_is_never_retried(self):
        provider = _provider()
        with patch("app.notifications.email_sender.smtplib.SMTP") as smtp_cls:
            connection = MagicMock()
            smtp_cls.return_value.__enter__.return_value = connection
            connection.login.side_effect = smtplib.SMTPAuthenticationError(535, "bad credentials")

            with pytest.raises(EmailDeliveryError):
                provider.send_email(to_address="a@example.com", subject="Hi", text_body="Hello")

            # Not retried: exactly one connection attempt, matching
            # _RETRYABLE_SMTP_EXCEPTIONS deliberately excluding auth
            # failures (a permanent, not transient, failure).
            assert smtp_cls.return_value.__enter__.call_count == 1

    def test_a_recipient_refused_failure_is_never_retried(self):
        provider = _provider()
        with patch("app.notifications.email_sender.smtplib.SMTP") as smtp_cls:
            connection = MagicMock()
            smtp_cls.return_value.__enter__.return_value = connection
            connection.sendmail.side_effect = smtplib.SMTPRecipientsRefused(
                {"a@example.com": (550, b"no such user")}
            )

            with pytest.raises(EmailDeliveryError):
                provider.send_email(to_address="a@example.com", subject="Hi", text_body="Hello")

            assert smtp_cls.return_value.__enter__.call_count == 1


class TestMessageIdForDuplicateSendAvoidance:
    def test_every_message_gets_a_message_id_header(self):
        provider = _provider()
        message = provider._build_message(
            to_address="a@example.com", subject="Hi", text_body="Hello", html_body=None
        )

        assert message["Message-ID"] is not None
        assert message["Message-ID"].strip() != ""

    def test_two_independently_built_messages_get_different_message_ids(self):
        provider = _provider()
        first = provider._build_message(
            to_address="a@example.com", subject="Hi", text_body="Hello", html_body=None
        )
        second = provider._build_message(
            to_address="a@example.com", subject="Hi", text_body="Hello", html_body=None
        )

        assert first["Message-ID"] != second["Message-ID"]

    def test_the_message_id_is_stable_across_every_retry_of_one_logical_send(self):
        # _build_message is called exactly once per send_email call, and
        # the *same* message object is reused by every retry_call
        # attempt of _send_once below - this is the behavior that makes
        # a receiving mail system's own dedup-by-Message-ID possible.
        # connection.sendmail(from_addr, to_addrs, msg_string) receives
        # the message pre-rendered to a string (email.message.Message.as_string()),
        # not the MIMEMultipart object itself - the Message-ID header is
        # extracted by scanning that rendered string's header lines.
        provider = _provider()
        seen_message_ids: list[str] = []

        def _extract_message_id(rendered_message: str) -> str:
            for line in rendered_message.splitlines():
                if line.lower().startswith("message-id:"):
                    return line.split(":", 1)[1].strip()
            raise AssertionError("No Message-ID header found in the rendered message.")

        def _capture_and_fail_twice(from_addr, to_addrs, msg_string):
            seen_message_ids.append(_extract_message_id(msg_string))
            raise smtplib.SMTPConnectError(421, "not available yet")

        with patch("app.notifications.email_sender.smtplib.SMTP") as smtp_cls:
            connection = MagicMock()
            connection.sendmail.side_effect = _capture_and_fail_twice
            smtp_cls.return_value.__enter__.return_value = connection

            with pytest.raises(EmailDeliveryError):
                provider.send_email(to_address="a@example.com", subject="Hi", text_body="Hello")

        assert len(seen_message_ids) == _FAST_RETRY_POLICY.max_attempts
        assert len(set(seen_message_ids)) == 1


class TestLoggingNeverExposesMessageContent:
    def test_a_delivery_failure_log_line_never_includes_the_message_body(self, caplog):
        provider = _provider()
        secret_body = "the quarterly bonus figure is $184,203.17 - keep confidential"
        with patch("app.notifications.email_sender.smtplib.SMTP") as smtp_cls:
            smtp_cls.return_value.__enter__.side_effect = smtplib.SMTPServerDisconnected("gone")

            with caplog.at_level("WARNING"), pytest.raises(EmailDeliveryError):
                provider.send_email(
                    to_address="a@example.com", subject="Confidential", text_body=secret_body
                )

        for record in caplog.records:
            assert secret_body not in record.getMessage()

    def test_a_successful_send_log_line_never_includes_the_message_body(self, caplog):
        provider = _provider()
        secret_body = "the quarterly bonus figure is $184,203.17 - keep confidential"
        with patch("app.notifications.email_sender.smtplib.SMTP") as smtp_cls:
            smtp_cls.return_value.__enter__.return_value = MagicMock()

            with caplog.at_level("INFO"):
                provider.send_email(
                    to_address="a@example.com", subject="Confidential", text_body=secret_body
                )

        for record in caplog.records:
            assert secret_body not in record.getMessage()
