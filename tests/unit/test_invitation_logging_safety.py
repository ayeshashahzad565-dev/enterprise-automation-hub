"""Milestone 9's Logging Audit, made concrete: rather than relying on
manual code review alone that a raw password or invitation token is
never logged, this file captures every log record ``InvitationService``
emits across representative success and failure invocations of
``validate_invitation_token``/``accept_invitation`` (both wrapped by
``app.utils.decorators.log_calls``) and asserts the raw secret values
never appear — neither in a record's rendered message nor in any
structured ``extra=`` field value.

``log_calls`` itself never logs a wrapped function's arguments (only
``component``/``outcome`` — see that decorator's own source), so the
real risk this file actually guards against is a raw secret leaking via
an *exception message* that ``log_calls``'s failure-path logging then
includes via ``exc_info``/``%s`` formatting — for example, if a future
change to ``_find_by_token_or_raise`` accidentally interpolated the real
token into ``NotFoundError``'s message instead of the fixed
``"<redacted-token>"`` placeholder it uses today.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.services.exceptions import InvalidInvitationStateError, NotFoundError
from app.services.invitation_service import (
    InvitationService,
    generate_invitation_token,
    hash_invitation_token,
)
from app.utils.datetime_utils import utc_now
from tests.fixtures.fakes import (
    FakeAuditRepository,
    FakeInvitationEmailSender,
    FakeInvitationRepository,
    FakeProfileRepository,
    FakeSupabaseAuthAdminClient,
)

pytestmark = pytest.mark.unit

_PASSWORD = "Sup3r-Secret-Password-Do-Not-Log-Me"


def _build_service() -> tuple[InvitationService, FakeInvitationRepository]:
    invitation_repo = FakeInvitationRepository()
    profile_repo = FakeProfileRepository()
    audit_repo = FakeAuditRepository()
    auth_admin_client = FakeSupabaseAuthAdminClient(profile_repo=profile_repo)
    service = InvitationService(
        invitation_repo=invitation_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        auth_admin_client=auth_admin_client,
        email_sender=FakeInvitationEmailSender(),
    )
    return service, invitation_repo


def _seed(invitation_repo: FakeInvitationRepository) -> tuple[str]:
    token = generate_invitation_token()
    invitation_repo.create_invitation(
        email="invitee@example.com",
        full_name="Invitee Person",
        token_hash=hash_invitation_token(token),
        expires_at=utc_now() + timedelta(hours=72),
        invited_by=uuid4(),
    )
    return (token,)


def _assert_never_logged(caplog: pytest.LogCaptureFixture, secret: str) -> None:
    for record in caplog.records:
        assert (
            secret not in record.getMessage()
        ), f"Secret value leaked into log message: {record.getMessage()!r}"
        for key, value in record.__dict__.items():
            if key == "msg":
                continue  # already checked via getMessage() above
            assert secret not in str(
                value
            ), f"Secret value leaked into extra field {key!r}: {value!r}"


class TestAcceptInvitationNeverLogsThePasswordOrToken:
    def test_successful_acceptance(self, caplog: pytest.LogCaptureFixture):
        service, invitation_repo = _build_service()
        (token,) = _seed(invitation_repo)

        with caplog.at_level("DEBUG"):
            service.accept_invitation(token, password=_PASSWORD)

        _assert_never_logged(caplog, _PASSWORD)
        _assert_never_logged(caplog, token)

    def test_unknown_token(self, caplog: pytest.LogCaptureFixture):
        service, _ = _build_service()

        with caplog.at_level("DEBUG"), pytest.raises(NotFoundError):
            service.accept_invitation("some-unknown-raw-token-value", password=_PASSWORD)

        _assert_never_logged(caplog, _PASSWORD)
        _assert_never_logged(caplog, "some-unknown-raw-token-value")

    def test_already_accepted_token(self, caplog: pytest.LogCaptureFixture):
        service, invitation_repo = _build_service()
        (token,) = _seed(invitation_repo)
        service.accept_invitation(token, password=_PASSWORD)
        caplog.clear()

        with caplog.at_level("DEBUG"), pytest.raises(InvalidInvitationStateError):
            service.accept_invitation(token, password="Another-Different-Password-2")

        _assert_never_logged(caplog, _PASSWORD)
        _assert_never_logged(caplog, "Another-Different-Password-2")
        _assert_never_logged(caplog, token)


class TestValidateInvitationTokenNeverLogsTheToken:
    def test_successful_validation(self, caplog: pytest.LogCaptureFixture):
        service, invitation_repo = _build_service()
        (token,) = _seed(invitation_repo)

        with caplog.at_level("DEBUG"):
            service.validate_invitation_token(token)

        _assert_never_logged(caplog, token)

    def test_unknown_token(self, caplog: pytest.LogCaptureFixture):
        service, _ = _build_service()

        with caplog.at_level("DEBUG"), pytest.raises(NotFoundError):
            service.validate_invitation_token("another-unknown-raw-token")

        _assert_never_logged(caplog, "another-unknown-raw-token")
