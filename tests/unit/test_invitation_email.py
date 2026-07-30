"""Unit tests for ``app.services.invitation_email.SmtpInvitationEmailSender``,
the Milestone 4 production ``InvitationEmailSender`` implementation.

Every test exercises the sender against ``FakeEmailProvider`` (see
``tests.fixtures.fakes``) — no real SMTP connection or network call is
made anywhere in this module.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from app.config.settings import InvitationSettings
from app.services.invitation_email import SmtpInvitationEmailSender
from app.utils.datetime_utils import utc_now
from tests.fixtures.fakes import FakeEmailProvider

pytestmark = pytest.mark.unit

_TOKEN = "Sekrit-Raw-Token-Value-Do-Not-Log-1234567890"
_EXPIRES_AT = utc_now() + timedelta(hours=72)


def _make_sender(
    *,
    provider: FakeEmailProvider | None = None,
    app_base_url: str = "https://app.example.com",
    accept_path: str = "/accept-invite",
    expiry_hours: float = 72.0,
) -> tuple[SmtpInvitationEmailSender, FakeEmailProvider]:
    resolved_provider = provider if provider is not None else FakeEmailProvider()
    settings = InvitationSettings(
        expiry_hours=expiry_hours, app_base_url=app_base_url, accept_path=accept_path
    )
    sender = SmtpInvitationEmailSender(email_provider=resolved_provider, settings=settings)
    return sender, resolved_provider


# ---------------------------------------------------------------------------
# New-invitation email generation
# ---------------------------------------------------------------------------


class TestSendNewInvitationEmail:
    def test_dispatches_exactly_one_email_via_the_injected_provider(self) -> None:
        sender, provider = _make_sender()

        result = sender.send_invitation(
            to_email="new.hire@example.com",
            full_name="Ada Lovelace",
            token=_TOKEN,
            expires_at=_EXPIRES_AT,
        )

        assert result is True
        assert len(provider.sent) == 1
        assert provider.sent[0].to_address == "new.hire@example.com"

    def test_subject_indicates_a_new_invitation_not_a_resend(self) -> None:
        sender, provider = _make_sender()

        sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )

        subject = provider.sent[0].subject.lower()
        assert "invited" in subject
        assert "renewed" not in subject

    def test_body_includes_the_recipients_full_name(self) -> None:
        sender, provider = _make_sender()

        sender.send_invitation(
            to_email="a@example.com", full_name="Grace Hopper", token=_TOKEN, expires_at=_EXPIRES_AT
        )

        assert "Grace Hopper" in provider.sent[0].text_body
        assert "Grace Hopper" in (provider.sent[0].html_body or "")

    def test_body_includes_the_acceptance_link_built_from_settings(self) -> None:
        sender, provider = _make_sender(
            app_base_url="https://onboard.example.com", accept_path="/accept-invite"
        )

        sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )

        expected_url = f"https://onboard.example.com/accept-invite?token={_TOKEN}"
        assert expected_url in provider.sent[0].text_body
        assert expected_url in (provider.sent[0].html_body or "")

    def test_html_body_is_rendered_alongside_the_text_body(self) -> None:
        sender, provider = _make_sender()

        sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )

        html_body = provider.sent[0].html_body
        assert html_body is not None
        assert "<html>" in html_body
        assert "<a href=" in html_body

    def test_html_body_escapes_the_recipients_full_name(self) -> None:
        sender, provider = _make_sender()

        sender.send_invitation(
            to_email="a@example.com",
            full_name="<script>alert(1)</script>",
            token=_TOKEN,
            expires_at=_EXPIRES_AT,
        )

        html_body = provider.sent[0].html_body or ""
        assert "<script>" not in html_body
        assert "&lt;script&gt;" in html_body

    def test_text_body_leaves_the_recipients_full_name_unescaped(self) -> None:
        sender, provider = _make_sender()

        sender.send_invitation(
            to_email="a@example.com",
            full_name="O'Brien & Sons",
            token=_TOKEN,
            expires_at=_EXPIRES_AT,
        )

        assert "O'Brien & Sons" in provider.sent[0].text_body

    def test_body_includes_the_expiry_timestamp(self) -> None:
        sender, provider = _make_sender()

        sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )

        assert _EXPIRES_AT.isoformat() in provider.sent[0].text_body


# ---------------------------------------------------------------------------
# Resend-invitation email generation
# ---------------------------------------------------------------------------


class TestSendResendInvitationEmail:
    def test_subject_indicates_a_renewed_invitation(self) -> None:
        sender, provider = _make_sender()

        sender.send_invitation(
            to_email="a@example.com",
            full_name="Ada",
            token=_TOKEN,
            expires_at=_EXPIRES_AT,
            is_resend=True,
        )

        subject = provider.sent[0].subject.lower()
        assert "renewed" in subject

    def test_body_copy_differs_from_a_new_invitation(self) -> None:
        new_sender, new_provider = _make_sender()
        resend_sender, resend_provider = _make_sender()

        new_sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )
        resend_sender.send_invitation(
            to_email="a@example.com",
            full_name="Ada",
            token=_TOKEN,
            expires_at=_EXPIRES_AT,
            is_resend=True,
        )

        assert new_provider.sent[0].text_body != resend_provider.sent[0].text_body

    def test_resend_email_still_carries_the_new_raw_token_in_its_link(self) -> None:
        sender, provider = _make_sender(
            app_base_url="https://app.example.com", accept_path="/accept-invite"
        )

        sender.send_invitation(
            to_email="a@example.com",
            full_name="Ada",
            token="brand-new-rotated-token",
            expires_at=_EXPIRES_AT,
            is_resend=True,
        )

        assert "token=brand-new-rotated-token" in provider.sent[0].text_body

    def test_default_is_resend_is_false(self) -> None:
        sender, provider = _make_sender()

        sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )

        assert "renewed" not in provider.sent[0].subject.lower()


# ---------------------------------------------------------------------------
# Acceptance URL generation / configuration usage
# ---------------------------------------------------------------------------


class TestAcceptanceUrlGeneration:
    def test_url_concatenates_base_url_and_accept_path_exactly(self) -> None:
        sender, provider = _make_sender(
            app_base_url="https://onboard.example.com", accept_path="/join-us"
        )

        sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token="abc123", expires_at=_EXPIRES_AT
        )

        assert "https://onboard.example.com/join-us?token=abc123" in provider.sent[0].text_body

    def test_accept_path_without_a_leading_slash_still_produces_a_valid_url(self) -> None:
        sender, provider = _make_sender(
            app_base_url="https://onboard.example.com", accept_path="join-us"
        )

        sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token="abc123", expires_at=_EXPIRES_AT
        )

        assert "https://onboard.example.com/join-us?token=abc123" in provider.sent[0].text_body

    def test_url_carries_the_exact_raw_token_unmodified(self) -> None:
        sender, provider = _make_sender()
        token = "Exact-Raw-Token_With-Url-Safe.Chars99"

        sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token=token, expires_at=_EXPIRES_AT
        )

        assert f"token={token}" in provider.sent[0].text_body


class TestConfigurationUsage:
    def test_different_base_urls_produce_different_acceptance_links(self) -> None:
        sender_a, provider_a = _make_sender(app_base_url="https://tenant-a.example.com")
        sender_b, provider_b = _make_sender(app_base_url="https://tenant-b.example.com")

        sender_a.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )
        sender_b.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )

        assert "tenant-a.example.com" in provider_a.sent[0].text_body
        assert "tenant-b.example.com" in provider_b.sent[0].text_body
        assert provider_a.sent[0].text_body != provider_b.sent[0].text_body

    def test_different_accept_paths_produce_different_acceptance_links(self) -> None:
        sender_a, provider_a = _make_sender(accept_path="/accept-invite")
        sender_b, provider_b = _make_sender(accept_path="/join")

        sender_a.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )
        sender_b.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )

        assert "/accept-invite?token=" in provider_a.sent[0].text_body
        assert "/join?token=" in provider_b.sent[0].text_body


# ---------------------------------------------------------------------------
# Failure recovery
# ---------------------------------------------------------------------------


class TestEmailFailureRecovery:
    def test_provider_delivery_failure_returns_false_without_raising(self) -> None:
        provider = FakeEmailProvider(raise_delivery_error=True)
        sender, _ = _make_sender(provider=provider)

        result = sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )

        assert result is False

    def test_provider_delivery_failure_does_not_propagate_any_exception(self) -> None:
        provider = FakeEmailProvider(raise_delivery_error=True)
        sender, _ = _make_sender(provider=provider)

        # No pytest.raises: the point of this test is that nothing raises.
        sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )


# ---------------------------------------------------------------------------
# Logging behavior
# ---------------------------------------------------------------------------


class TestLoggingBehavior:
    def test_the_raw_token_never_appears_in_any_log_record(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        sender, _ = _make_sender()
        secret_token = "Never-Log-Me-Token-98765"

        with caplog.at_level(logging.DEBUG):
            sender.send_invitation(
                to_email="a@example.com",
                full_name="Ada",
                token=secret_token,
                expires_at=_EXPIRES_AT,
            )

        for record in caplog.records:
            assert secret_token not in record.getMessage()

    def test_the_acceptance_url_never_appears_in_any_log_record(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        sender, _ = _make_sender(
            app_base_url="https://onboard.example.com", accept_path="/accept-invite"
        )

        with caplog.at_level(logging.DEBUG):
            sender.send_invitation(
                to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
            )

        for record in caplog.records:
            assert "accept-invite?token=" not in record.getMessage()

    def test_a_successful_send_logs_the_recipient_and_resend_flag(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        sender, _ = _make_sender()

        with caplog.at_level(logging.INFO):
            sender.send_invitation(
                to_email="new.hire@example.com",
                full_name="Ada",
                token=_TOKEN,
                expires_at=_EXPIRES_AT,
                is_resend=True,
            )

        messages = [record.getMessage() for record in caplog.records]
        assert any("new.hire@example.com" in message for message in messages)
        assert any("True" in message for message in messages)

    def test_a_failed_send_logs_a_warning_without_the_token(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = FakeEmailProvider(raise_delivery_error=True)
        sender, _ = _make_sender(provider=provider)
        secret_token = "Warning-Path-Token-11111"

        with caplog.at_level(logging.DEBUG):
            sender.send_invitation(
                to_email="a@example.com",
                full_name="Ada",
                token=secret_token,
                expires_at=_EXPIRES_AT,
            )

        warning_records = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert len(warning_records) == 1
        assert secret_token not in warning_records[0].getMessage()


# ---------------------------------------------------------------------------
# Dependency injection wiring
# ---------------------------------------------------------------------------


class TestDependencyInjection:
    def test_sender_delivers_only_through_its_own_injected_provider(self) -> None:
        provider_a = FakeEmailProvider()
        provider_b = FakeEmailProvider()
        sender_a, _ = _make_sender(provider=provider_a)
        sender_b, _ = _make_sender(provider=provider_b)

        sender_a.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )

        assert len(provider_a.sent) == 1
        assert len(provider_b.sent) == 0

    def test_sender_accepts_any_object_structurally_satisfying_email_provider(self) -> None:
        class _MinimalProvider:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def send_email(
                self, *, to_address: str, subject: str, text_body: str, html_body: str | None = None
            ) -> None:
                self.calls.append(to_address)

        minimal_provider = _MinimalProvider()
        sender, _ = _make_sender(provider=minimal_provider)  # type: ignore[arg-type]

        result = sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )

        assert result is True
        assert minimal_provider.calls == ["a@example.com"]

    def test_settings_are_read_only_from_the_injected_invitation_settings(self) -> None:
        sender, provider = _make_sender(
            app_base_url="https://injected-only.example.com", accept_path="/inject-path"
        )

        sender.send_invitation(
            to_email="a@example.com", full_name="Ada", token=_TOKEN, expires_at=_EXPIRES_AT
        )

        assert "injected-only.example.com/inject-path" in provider.sent[0].text_body
