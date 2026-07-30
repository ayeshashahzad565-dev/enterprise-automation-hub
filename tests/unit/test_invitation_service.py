"""Unit tests for ``InvitationService``'s admin-facing methods
(Enterprise User Onboarding architecture, Milestone 2: create, list, get,
resend, revoke). The acceptance flow (``validate_invitation_token``,
``accept_invitation``, Milestone 3) is tested separately in
``tests/unit/test_invitation_service_acceptance.py``.

Follows this project's established service-testing convention: fake
repositories/collaborators (``tests/fixtures/fakes.py``) wired into the
real, unmodified ``InvitationService``, exercised entirely in-memory with
no network dependency. Identities are built via the existing
``admin``/``employee``/``make_user`` fixtures from ``tests/conftest.py``
(auto-discovered; no import needed), rather than duplicating that
fixture machinery here.

``profile_repo`` and ``auth_admin_client`` are constructor dependencies
``InvitationService`` needs for ``accept_invitation`` (Milestone 3), not
exercised by any test in this file — fakes are still supplied here
because the constructor requires them.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from uuid import uuid4

import pytest

from app.database.repositories.base_repository import Page
from app.models.enums import AuditAction, EffectiveInvitationStatus, InvitationStatus, UserRole
from app.services.exceptions import (
    ConcurrencyError,
    InvalidInvitationStateError,
    InvitationConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.services.invitation_service import (
    DEFAULT_INVITATION_EXPIRY_HOURS,
    InvitationService,
    compute_effective_status,
    generate_invitation_token,
    hash_invitation_token,
    verify_invitation_token,
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


@dataclasses.dataclass
class InvitationEnv:
    invitation_repo: FakeInvitationRepository
    profile_repo: FakeProfileRepository
    audit_repo: FakeAuditRepository
    email_sender: FakeInvitationEmailSender
    auth_admin_client: FakeSupabaseAuthAdminClient
    service: InvitationService


@pytest.fixture
def invitation_env() -> InvitationEnv:
    invitation_repo = FakeInvitationRepository()
    profile_repo = FakeProfileRepository()
    audit_repo = FakeAuditRepository()
    email_sender = FakeInvitationEmailSender()
    auth_admin_client = FakeSupabaseAuthAdminClient(profile_repo=profile_repo)
    service = InvitationService(
        invitation_repo=invitation_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        auth_admin_client=auth_admin_client,
        email_sender=email_sender,
    )
    return InvitationEnv(
        invitation_repo=invitation_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        email_sender=email_sender,
        auth_admin_client=auth_admin_client,
        service=service,
    )


# ---------------------------------------------------------------------------
# Token generation / hashing
# ---------------------------------------------------------------------------


class TestTokenHandling:
    def test_generate_invitation_token_is_high_entropy_and_url_safe(self):
        token = generate_invitation_token()

        assert len(token) >= 32
        assert all(c.isalnum() or c in "-_" for c in token)

    def test_generate_invitation_token_is_unique_per_call(self):
        tokens = {generate_invitation_token() for _ in range(50)}

        assert len(tokens) == 50

    def test_hash_invitation_token_is_deterministic(self):
        token = generate_invitation_token()

        assert hash_invitation_token(token) == hash_invitation_token(token)

    def test_hash_invitation_token_differs_for_different_tokens(self):
        assert hash_invitation_token("token-a") != hash_invitation_token("token-b")

    def test_hash_invitation_token_never_returns_the_raw_token(self):
        token = "a-raw-token-value"

        assert hash_invitation_token(token) != token

    def test_verify_invitation_token_accepts_the_matching_token(self):
        token = generate_invitation_token()
        token_hash = hash_invitation_token(token)

        assert verify_invitation_token(token, token_hash) is True

    def test_verify_invitation_token_rejects_a_wrong_token(self):
        token_hash = hash_invitation_token(generate_invitation_token())

        assert verify_invitation_token("not-the-right-token", token_hash) is False


# ---------------------------------------------------------------------------
# compute_effective_status
# ---------------------------------------------------------------------------


class TestComputeEffectiveStatus:
    def test_pending_and_unexpired_is_pending(self):
        status = compute_effective_status(
            status=InvitationStatus.PENDING,
            expires_at=utc_now() + timedelta(hours=1),
        )
        assert status is EffectiveInvitationStatus.PENDING

    def test_pending_and_expired_is_expired(self):
        status = compute_effective_status(
            status=InvitationStatus.PENDING,
            expires_at=utc_now() - timedelta(hours=1),
        )
        assert status is EffectiveInvitationStatus.EXPIRED

    def test_accepted_is_always_accepted_even_if_expires_at_is_in_the_past(self):
        status = compute_effective_status(
            status=InvitationStatus.ACCEPTED,
            expires_at=utc_now() - timedelta(hours=1),
        )
        assert status is EffectiveInvitationStatus.ACCEPTED

    def test_revoked_is_always_revoked_even_if_not_yet_expired(self):
        status = compute_effective_status(
            status=InvitationStatus.REVOKED,
            expires_at=utc_now() + timedelta(hours=1),
        )
        assert status is EffectiveInvitationStatus.REVOKED

    def test_accepts_an_explicit_reference_time_for_determinism(self):
        expires_at = utc_now()
        just_before = expires_at - timedelta(seconds=1)
        just_after = expires_at + timedelta(seconds=1)

        assert (
            compute_effective_status(
                status=InvitationStatus.PENDING, expires_at=expires_at, now=just_before
            )
            is EffectiveInvitationStatus.PENDING
        )
        assert (
            compute_effective_status(
                status=InvitationStatus.PENDING, expires_at=expires_at, now=just_after
            )
            is EffectiveInvitationStatus.EXPIRED
        )


# ---------------------------------------------------------------------------
# create_invitation
# ---------------------------------------------------------------------------


class TestCreateInvitation:
    def test_admin_can_create_an_invitation(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin

        invitation = invitation_env.service.create_invitation(
            admin_identity,
            email="new.hire@example.com",
            full_name="New Hire",
            role=UserRole.EMPLOYEE,
        )

        assert invitation.email == "new.hire@example.com"
        assert invitation.full_name == "New Hire"
        assert invitation.role is UserRole.EMPLOYEE
        assert invitation.effective_status is EffectiveInvitationStatus.PENDING
        assert invitation.resend_count == 0
        assert invitation.version == 1
        assert invitation.invited_by == admin_identity.user_id

    def test_create_invitation_sets_expiry_using_the_configured_duration(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin
        before = utc_now()

        invitation = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )

        expected = before + timedelta(hours=DEFAULT_INVITATION_EXPIRY_HOURS)
        assert abs((invitation.expires_at - expected).total_seconds()) < 5

    def test_non_admin_cannot_create_an_invitation(self, invitation_env: InvitationEnv, employee):
        _, employee_identity = employee

        with pytest.raises(PermissionDeniedError):
            invitation_env.service.create_invitation(
                employee_identity, email="a@example.com", full_name="A"
            )

    def test_approver_cannot_create_an_invitation(self, invitation_env: InvitationEnv, approver):
        _, approver_identity = approver

        with pytest.raises(PermissionDeniedError):
            invitation_env.service.create_invitation(
                approver_identity, email="a@example.com", full_name="A"
            )

    def test_create_invitation_rejects_a_malformed_email(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin

        with pytest.raises(ValidationError):
            invitation_env.service.create_invitation(
                admin_identity, email="not-an-email", full_name="A"
            )

    def test_create_invitation_rejects_a_blank_full_name(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin

        with pytest.raises(ValidationError):
            invitation_env.service.create_invitation(
                admin_identity, email="a@example.com", full_name="   "
            )

    def test_create_invitation_rejects_an_overlong_full_name(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin

        with pytest.raises(ValidationError):
            invitation_env.service.create_invitation(
                admin_identity, email="a@example.com", full_name="x" * 201
            )

    def test_create_invitation_rejects_an_overlong_email(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin
        overlong_email = f"{'x' * 250}@example.com"

        with pytest.raises(ValidationError):
            invitation_env.service.create_invitation(
                admin_identity, email=overlong_email, full_name="A"
            )

    def test_create_invitation_rejects_an_overlong_department(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin

        with pytest.raises(ValidationError):
            invitation_env.service.create_invitation(
                admin_identity, email="a@example.com", full_name="A", department="x" * 201
            )

    def test_duplicate_pending_invitation_is_rejected(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        invitation_env.service.create_invitation(
            admin_identity, email="dup@example.com", full_name="First"
        )

        with pytest.raises(InvitationConflictError):
            invitation_env.service.create_invitation(
                admin_identity, email="dup@example.com", full_name="Second"
            )

    def test_duplicate_check_is_case_insensitive(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        invitation_env.service.create_invitation(
            admin_identity, email="Mixed.Case@Example.com", full_name="First"
        )

        with pytest.raises(InvitationConflictError):
            invitation_env.service.create_invitation(
                admin_identity, email="mixed.case@example.com", full_name="Second"
            )

    def test_create_invitation_records_an_audit_event(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin

        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )

        events = invitation_env.audit_repo.list_for_actor(admin_identity.user_id).items
        assert len(events) == 1
        assert events[0].action == AuditAction.INVITATION_CREATED.value
        assert events[0].metadata == {"invitation_id": str(created.id), "email": "a@example.com"}
        assert events[0].actor_id == admin_identity.user_id

    def test_create_invitation_dispatches_an_email_with_the_raw_token(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin

        invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )

        assert len(invitation_env.email_sender.sent) == 1
        sent = invitation_env.email_sender.sent[0]
        assert sent.to_email == "a@example.com"
        assert sent.full_name == "A"
        assert sent.token  # a raw token was passed through
        # The stored record only ever carries a hash, never the raw token.
        stored = invitation_env.invitation_repo.find_pending_by_email("a@example.com")
        assert stored is not None
        assert stored.token_hash != sent.token
        assert verify_invitation_token(sent.token, stored.token_hash) is True

    def test_create_invitation_does_not_raise_when_email_dispatch_fails(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin
        invitation_env.email_sender = FakeInvitationEmailSender(raise_exception=True)
        service = InvitationService(
            invitation_repo=invitation_env.invitation_repo,
            profile_repo=invitation_env.profile_repo,
            audit_repo=invitation_env.audit_repo,
            auth_admin_client=invitation_env.auth_admin_client,
            email_sender=invitation_env.email_sender,
        )

        invitation = service.create_invitation(admin_identity, email="a@example.com", full_name="A")

        assert invitation.email == "a@example.com"  # invitation still created

    def test_create_invitation_works_with_no_email_sender_configured(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin
        service = InvitationService(
            invitation_repo=invitation_env.invitation_repo,
            profile_repo=invitation_env.profile_repo,
            audit_repo=invitation_env.audit_repo,
            auth_admin_client=invitation_env.auth_admin_client,
        )

        invitation = service.create_invitation(admin_identity, email="a@example.com", full_name="A")

        assert invitation.email == "a@example.com"


# ---------------------------------------------------------------------------
# get_invitation
# ---------------------------------------------------------------------------


class TestGetInvitation:
    def test_admin_can_get_an_existing_invitation(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )

        fetched = invitation_env.service.get_invitation(admin_identity, created.id)

        assert fetched.id == created.id
        assert fetched.email == "a@example.com"

    def test_get_invitation_raises_not_found_for_an_unknown_id(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin

        with pytest.raises(NotFoundError):
            invitation_env.service.get_invitation(admin_identity, uuid4())

    def test_non_admin_cannot_get_an_invitation(self, invitation_env: InvitationEnv, employee):
        _, employee_identity = employee

        with pytest.raises(PermissionDeniedError):
            invitation_env.service.get_invitation(employee_identity, uuid4())


# ---------------------------------------------------------------------------
# list_invitations
# ---------------------------------------------------------------------------


class TestListInvitations:
    def test_non_admin_cannot_list_invitations(self, invitation_env: InvitationEnv, employee):
        _, employee_identity = employee

        with pytest.raises(PermissionDeniedError):
            invitation_env.service.list_invitations(employee_identity)

    def test_list_invitations_returns_every_invitation_by_default(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin
        invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )
        invitation_env.service.create_invitation(
            admin_identity, email="b@example.com", full_name="B"
        )

        result = invitation_env.service.list_invitations(admin_identity)

        assert result.total_records == 2
        assert {i.email for i in result.items} == {"a@example.com", "b@example.com"}

    def test_list_invitations_filters_by_accepted_status_directly(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin
        pending = invitation_env.service.create_invitation(
            admin_identity, email="pending@example.com", full_name="P"
        )
        accepted = invitation_env.service.create_invitation(
            admin_identity, email="accepted@example.com", full_name="A"
        )
        invitation_env.invitation_repo.update_status_with_lock(
            accepted.id, expected_version=accepted.version, status=InvitationStatus.ACCEPTED
        )

        result = invitation_env.service.list_invitations(
            admin_identity, status=EffectiveInvitationStatus.ACCEPTED
        )

        assert [i.id for i in result.items] == [accepted.id]
        assert pending.id not in [i.id for i in result.items]

    def test_list_invitations_filters_expired_from_pending(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin
        fresh = invitation_env.service.create_invitation(
            admin_identity, email="fresh@example.com", full_name="F"
        )
        # Force-expire a second invitation by writing an already-past
        # expires_at directly through the repository (the service itself
        # has no method to backdate expiry; this simulates the passage of
        # time for a previously-created invitation).
        stale_record = invitation_env.invitation_repo.create_invitation(
            email="stale@example.com",
            full_name="S",
            token_hash="stale-hash",
            expires_at=utc_now() - timedelta(hours=1),
            invited_by=admin_identity.user_id,
        )

        pending_only = invitation_env.service.list_invitations(
            admin_identity, status=EffectiveInvitationStatus.PENDING
        )
        expired_only = invitation_env.service.list_invitations(
            admin_identity, status=EffectiveInvitationStatus.EXPIRED
        )

        assert [i.id for i in pending_only.items] == [fresh.id]
        assert [i.id for i in expired_only.items] == [stale_record.id]

    def test_list_invitations_status_filter_paginates_and_counts_correctly(
        self, invitation_env: InvitationEnv, admin
    ):
        """Regression test for the effective-status pagination bug: an
        earlier implementation fetched a persisted-pending page and
        filtered it further in Python, which under- or over-counted
        ``total_records`` and could under-fill a page for the computed
        PENDING/EXPIRED statuses specifically. Three expired invitations
        plus one fresh (unexpired) one, with a page size smaller than the
        expired count, must still report the exact expired total and
        return every expired invitation across pages.
        """
        _, admin_identity = admin
        invitation_env.service.create_invitation(
            admin_identity, email="fresh@example.com", full_name="Fresh"
        )
        for i in range(3):
            invitation_env.invitation_repo.create_invitation(
                email=f"stale{i}@example.com",
                full_name=f"Stale {i}",
                token_hash=f"stale-hash-{i}",
                expires_at=utc_now() - timedelta(hours=1),
                invited_by=admin_identity.user_id,
            )

        first_page = invitation_env.service.list_invitations(
            admin_identity, status=EffectiveInvitationStatus.EXPIRED, page=Page(number=1, size=2)
        )
        second_page = invitation_env.service.list_invitations(
            admin_identity, status=EffectiveInvitationStatus.EXPIRED, page=Page(number=2, size=2)
        )

        assert first_page.total_records == 3
        assert len(first_page.items) == 2
        assert len(second_page.items) == 1
        all_ids = {i.id for i in first_page.items} | {i.id for i in second_page.items}
        assert len(all_ids) == 3
        assert all(
            i.effective_status is EffectiveInvitationStatus.EXPIRED for i in first_page.items
        )

    def test_list_invitations_query_matches_name_or_email(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin
        invitation_env.service.create_invitation(
            admin_identity, email="findme@example.com", full_name="Someone"
        )
        invitation_env.service.create_invitation(
            admin_identity, email="other@example.com", full_name="Unrelated"
        )

        result = invitation_env.service.list_invitations(admin_identity, query="findme")

        assert len(result.items) == 1
        assert result.items[0].email == "findme@example.com"


# ---------------------------------------------------------------------------
# resend_invitation
# ---------------------------------------------------------------------------


class TestResendInvitation:
    def test_resend_rotates_the_token(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )
        original_token = invitation_env.email_sender.sent[0].token
        original_hash = invitation_env.invitation_repo.get_by_id(created.id).token_hash

        invitation_env.service.resend_invitation(admin_identity, created.id)

        new_hash = invitation_env.invitation_repo.get_by_id(created.id).token_hash
        assert new_hash != original_hash
        assert verify_invitation_token(original_token, new_hash) is False

    def test_resend_extends_expiry(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )
        before_resend = utc_now()

        resent = invitation_env.service.resend_invitation(admin_identity, created.id)

        expected = before_resend + timedelta(hours=DEFAULT_INVITATION_EXPIRY_HOURS)
        assert abs((resent.expires_at - expected).total_seconds()) < 5

    def test_resend_increments_resend_count(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )

        first = invitation_env.service.resend_invitation(admin_identity, created.id)
        second = invitation_env.service.resend_invitation(admin_identity, first.id)

        assert first.resend_count == 1
        assert second.resend_count == 2

    def test_resend_preserves_pending_effective_status(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )

        resent = invitation_env.service.resend_invitation(admin_identity, created.id)

        assert resent.effective_status is EffectiveInvitationStatus.PENDING

    def test_resend_can_revive_an_expired_invitation(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        stale_record = invitation_env.invitation_repo.create_invitation(
            email="stale@example.com",
            full_name="S",
            token_hash="stale-hash",
            expires_at=utc_now() - timedelta(hours=1),
            invited_by=admin_identity.user_id,
        )

        revived = invitation_env.service.resend_invitation(admin_identity, stale_record.id)

        assert revived.effective_status is EffectiveInvitationStatus.PENDING

    def test_resend_records_an_audit_event(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )

        invitation_env.service.resend_invitation(admin_identity, created.id)

        # list_for_actor returns newest first, matching the real
        # AuditRepository's identical ordering.
        events = invitation_env.audit_repo.list_for_actor(admin_identity.user_id).items
        assert [e.action for e in events] == [
            AuditAction.INVITATION_RESENT.value,
            AuditAction.INVITATION_CREATED.value,
        ]

    def test_resend_raises_not_found_for_an_unknown_invitation(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin

        with pytest.raises(NotFoundError):
            invitation_env.service.resend_invitation(admin_identity, uuid4())

    def test_resend_rejects_an_already_accepted_invitation(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )
        invitation_env.invitation_repo.update_status_with_lock(
            created.id, expected_version=created.version, status=InvitationStatus.ACCEPTED
        )

        with pytest.raises(InvalidInvitationStateError):
            invitation_env.service.resend_invitation(admin_identity, created.id)

    def test_resend_rejects_a_revoked_invitation(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )
        invitation_env.service.revoke_invitation(admin_identity, created.id)

        with pytest.raises(InvalidInvitationStateError):
            invitation_env.service.resend_invitation(admin_identity, created.id)

    def test_non_admin_cannot_resend(self, invitation_env: InvitationEnv, admin, employee):
        _, admin_identity = admin
        _, employee_identity = employee
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )

        with pytest.raises(PermissionDeniedError):
            invitation_env.service.resend_invitation(employee_identity, created.id)

    def test_resend_raises_concurrency_error_when_the_row_changed_between_read_and_write(
        self, invitation_env: InvitationEnv, admin, monkeypatch
    ):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )
        # Advance the row's real version first (simulating a second,
        # concurrent writer), then hand the service a stale copy of the
        # record to read from — reproducing "another writer already
        # changed this row" between this method's own read and write.
        invitation_env.invitation_repo.update_status_with_lock(
            created.id, expected_version=created.version, status=InvitationStatus.PENDING
        )
        stale_record = dataclasses.replace(
            invitation_env.invitation_repo.get_by_id(created.id), version=created.version
        )
        monkeypatch.setattr(
            invitation_env.invitation_repo, "get_by_id", lambda invitation_id: stale_record
        )

        with pytest.raises(ConcurrencyError):
            invitation_env.service.resend_invitation(admin_identity, created.id)


# ---------------------------------------------------------------------------
# revoke_invitation
# ---------------------------------------------------------------------------


class TestRevokeInvitation:
    def test_revoke_sets_revoked_status_and_timestamp(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )

        revoked = invitation_env.service.revoke_invitation(admin_identity, created.id)

        assert revoked.effective_status is EffectiveInvitationStatus.REVOKED
        assert revoked.revoked_at is not None

    def test_revoke_records_an_audit_event(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )

        invitation_env.service.revoke_invitation(admin_identity, created.id)

        # list_for_actor returns newest first, so the revoke event is at
        # index 0, matching the real AuditRepository's identical ordering.
        events = invitation_env.audit_repo.list_for_actor(admin_identity.user_id).items
        assert events[0].action == AuditAction.INVITATION_REVOKED.value
        assert events[0].metadata == {"invitation_id": str(created.id), "email": "a@example.com"}

    def test_revoke_raises_not_found_for_an_unknown_invitation(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin

        with pytest.raises(NotFoundError):
            invitation_env.service.revoke_invitation(admin_identity, uuid4())

    def test_revoke_rejects_an_already_revoked_invitation(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )
        invitation_env.service.revoke_invitation(admin_identity, created.id)

        with pytest.raises(InvalidInvitationStateError):
            invitation_env.service.revoke_invitation(admin_identity, created.id)

    def test_revoke_rejects_an_accepted_invitation(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )
        invitation_env.invitation_repo.update_status_with_lock(
            created.id, expected_version=created.version, status=InvitationStatus.ACCEPTED
        )

        with pytest.raises(InvalidInvitationStateError):
            invitation_env.service.revoke_invitation(admin_identity, created.id)

    def test_revoke_allows_reinviting_the_same_email_afterward(
        self, invitation_env: InvitationEnv, admin
    ):
        _, admin_identity = admin
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )
        invitation_env.service.revoke_invitation(admin_identity, created.id)

        second = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A Again"
        )

        assert second.id != created.id
        assert second.effective_status is EffectiveInvitationStatus.PENDING

    def test_non_admin_cannot_revoke(self, invitation_env: InvitationEnv, admin, employee):
        _, admin_identity = admin
        _, employee_identity = employee
        created = invitation_env.service.create_invitation(
            admin_identity, email="a@example.com", full_name="A"
        )

        with pytest.raises(PermissionDeniedError):
            invitation_env.service.revoke_invitation(employee_identity, created.id)


# ---------------------------------------------------------------------------
# Pagination pass-through sanity check
# ---------------------------------------------------------------------------


class TestListInvitationsPagination:
    def test_list_invitations_respects_an_explicit_page(self, invitation_env: InvitationEnv, admin):
        _, admin_identity = admin
        for i in range(3):
            invitation_env.service.create_invitation(
                admin_identity, email=f"user{i}@example.com", full_name=f"User {i}"
            )

        page_one = invitation_env.service.list_invitations(
            admin_identity, page=Page(number=1, size=2)
        )

        assert page_one.total_records == 3
        assert len(page_one.items) == 2
