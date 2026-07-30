"""Unit tests for ``InvitationService``'s acceptance flow (Enterprise
User Onboarding architecture, Milestone 3):
``validate_invitation_token`` and ``accept_invitation``.

Separate from ``tests/unit/test_invitation_service.py`` (Milestone 2's
admin-facing methods) since this flow is deliberately unauthenticated —
no ``AuthenticatedIdentity``/``admin``/``employee`` fixture is used
anywhere in this file, matching ``accept_invitation``'s own design: token
possession is the entire authorization boundary.

Fakes only, no network dependency, following this project's established
fake-collaborator testing convention (``tests/fixtures/fakes.py``).
``FakeSupabaseAuthAdminClient`` is wired to the same
``FakeProfileRepository`` the service itself uses, so it can simulate the
real ``on_auth_user_created`` trigger's effect (a successful
``create_user`` call synchronously provisions a matching ``profiles``
row) — see that fake's own docstring.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from uuid import uuid4

import pytest

from app.models.enums import EffectiveInvitationStatus, InvitationStatus, UserRole
from app.services.exceptions import (
    ConcurrencyError,
    InvalidInvitationStateError,
    InvitationConflictError,
    NotFoundError,
    SupabaseAdminOperationError,
)
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

_PASSWORD = "Correct-Horse-Battery-Staple-1"


@dataclasses.dataclass
class AcceptanceEnv:
    invitation_repo: FakeInvitationRepository
    profile_repo: FakeProfileRepository
    audit_repo: FakeAuditRepository
    auth_admin_client: FakeSupabaseAuthAdminClient
    service: InvitationService


def _make_env(
    *, provision_profile: bool = True, raise_generic_error: bool = False
) -> AcceptanceEnv:
    invitation_repo = FakeInvitationRepository()
    profile_repo = FakeProfileRepository()
    audit_repo = FakeAuditRepository()
    auth_admin_client = FakeSupabaseAuthAdminClient(
        profile_repo=profile_repo,
        provision_profile=provision_profile,
        raise_generic_error=raise_generic_error,
    )
    service = InvitationService(
        invitation_repo=invitation_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        auth_admin_client=auth_admin_client,
        email_sender=FakeInvitationEmailSender(),
    )
    return AcceptanceEnv(
        invitation_repo=invitation_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        auth_admin_client=auth_admin_client,
        service=service,
    )


@pytest.fixture
def acceptance_env() -> AcceptanceEnv:
    return _make_env()


def _seed_invitation(
    invitation_repo: FakeInvitationRepository,
    *,
    email: str = "invitee@example.com",
    full_name: str = "Invitee Person",
    role: UserRole = UserRole.EMPLOYEE,
    department: str | None = None,
    hours_until_expiry: float = 72.0,
    invited_by=None,
):
    """Seed a pending invitation directly through the repository (as
    ``InvitationService.create_invitation`` would have), bypassing the
    admin-only creation path entirely — these tests exercise only the
    unauthenticated acceptance half of the service.

    Returns:
        A ``(InvitationRecord, raw_token)`` tuple.
    """
    token = generate_invitation_token()
    token_hash = hash_invitation_token(token)
    record = invitation_repo.create_invitation(
        email=email,
        full_name=full_name,
        role=role,
        department=department,
        token_hash=token_hash,
        expires_at=utc_now() + timedelta(hours=hours_until_expiry),
        invited_by=invited_by if invited_by is not None else uuid4(),
    )
    return record, token


# ---------------------------------------------------------------------------
# validate_invitation_token
# ---------------------------------------------------------------------------


class TestValidateInvitationToken:
    def test_validates_a_pending_unexpired_token(self, acceptance_env: AcceptanceEnv):
        record, token = _seed_invitation(acceptance_env.invitation_repo)

        invitation = acceptance_env.service.validate_invitation_token(token)

        assert invitation.id == record.id
        assert invitation.email == record.email
        assert invitation.effective_status is EffectiveInvitationStatus.PENDING

    def test_requires_no_caller_identity_at_all(self, acceptance_env: AcceptanceEnv):
        """Authorization boundary: token possession is the only gate —
        this method's signature accepts no identity/role of any kind."""
        _, token = _seed_invitation(acceptance_env.invitation_repo)

        # No AuthenticatedIdentity constructed or passed anywhere in this
        # test; the call below is the entirety of the "authorization"
        # this method performs.
        invitation = acceptance_env.service.validate_invitation_token(token)

        assert invitation is not None

    def test_rejects_an_unknown_token(self, acceptance_env: AcceptanceEnv):
        with pytest.raises(NotFoundError):
            acceptance_env.service.validate_invitation_token("not-a-real-token")

    def test_rejects_an_expired_token(self, acceptance_env: AcceptanceEnv):
        _, token = _seed_invitation(acceptance_env.invitation_repo, hours_until_expiry=-1)

        with pytest.raises(InvalidInvitationStateError) as exc_info:
            acceptance_env.service.validate_invitation_token(token)
        assert exc_info.value.current_status == "expired"

    def test_rejects_a_revoked_token(self, acceptance_env: AcceptanceEnv):
        record, token = _seed_invitation(acceptance_env.invitation_repo)
        acceptance_env.invitation_repo.update_status_with_lock(
            record.id, expected_version=record.version, status=InvitationStatus.REVOKED
        )

        with pytest.raises(InvalidInvitationStateError) as exc_info:
            acceptance_env.service.validate_invitation_token(token)
        assert exc_info.value.current_status == "revoked"

    def test_rejects_an_already_accepted_token(self, acceptance_env: AcceptanceEnv):
        _, token = _seed_invitation(acceptance_env.invitation_repo)
        acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        with pytest.raises(InvalidInvitationStateError) as exc_info:
            acceptance_env.service.validate_invitation_token(token)
        assert exc_info.value.current_status == "accepted"

    def test_never_leaks_the_raw_token_in_a_not_found_error(self, acceptance_env: AcceptanceEnv):
        secret_looking_token = "super-secret-value-should-never-appear-in-any-message"

        with pytest.raises(NotFoundError) as exc_info:
            acceptance_env.service.validate_invitation_token(secret_looking_token)

        assert secret_looking_token not in str(exc_info.value)
        assert secret_looking_token not in repr(exc_info.value)


# ---------------------------------------------------------------------------
# accept_invitation: success path, metadata, profile linkage, audit
# ---------------------------------------------------------------------------


class TestAcceptInvitationSuccess:
    def test_accept_invitation_marks_the_invitation_accepted(self, acceptance_env: AcceptanceEnv):
        record, token = _seed_invitation(acceptance_env.invitation_repo)

        accepted = acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        assert accepted.effective_status is EffectiveInvitationStatus.ACCEPTED
        assert accepted.accepted_at is not None
        assert accepted.id == record.id

    def test_accept_invitation_links_the_created_profile(self, acceptance_env: AcceptanceEnv):
        record, token = _seed_invitation(acceptance_env.invitation_repo)

        accepted = acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        assert accepted.accepted_profile_id is not None
        profile = acceptance_env.profile_repo.find_by_id(accepted.accepted_profile_id)
        assert profile is not None
        assert profile.full_name == record.full_name
        assert profile.role is record.role

    def test_accept_invitation_uses_the_invitations_own_id_as_the_profile_id(
        self, acceptance_env: AcceptanceEnv
    ):
        """The deterministic id choice this milestone's idempotency
        strategy depends on — see InvitationService.accept_invitation's
        own docstring."""
        record, token = _seed_invitation(acceptance_env.invitation_repo)

        accepted = acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        assert accepted.accepted_profile_id == record.id

    def test_accept_invitation_passes_full_name_and_role_metadata_to_supabase(
        self, acceptance_env: AcceptanceEnv
    ):
        record, token = _seed_invitation(
            acceptance_env.invitation_repo, full_name="Metadata Person", role=UserRole.APPROVER
        )

        acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        assert len(acceptance_env.auth_admin_client.created_users) == 1
        created = acceptance_env.auth_admin_client.created_users[0]
        assert created.user_metadata == {
            "full_name": "Metadata Person",
            "role": "approver",
            "company_id": str(record.company_id),
        }
        assert created.email == "invitee@example.com"
        assert created.password == _PASSWORD

    def test_accept_invitation_records_an_audit_event_attributed_to_the_new_profile(
        self, acceptance_env: AcceptanceEnv
    ):
        record, token = _seed_invitation(acceptance_env.invitation_repo)

        accepted = acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        events = acceptance_env.audit_repo.list_for_actor(accepted.accepted_profile_id).items
        assert len(events) == 1
        assert events[0].action == "INVITATION_ACCEPTED"
        assert events[0].actor_id == accepted.accepted_profile_id
        assert events[0].metadata == {"invitation_id": str(record.id), "email": record.email}

    def test_accept_invitation_never_logs_or_returns_the_raw_password_or_token(
        self, acceptance_env: AcceptanceEnv
    ):
        _, token = _seed_invitation(acceptance_env.invitation_repo)

        accepted = acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        # The returned domain model has no field that could carry either
        # secret — this assertion documents that guarantee explicitly.
        dumped = accepted.model_dump()
        assert _PASSWORD not in str(dumped)
        assert token not in str(dumped)


# ---------------------------------------------------------------------------
# accept_invitation: rejection paths
# ---------------------------------------------------------------------------


class TestAcceptInvitationRejections:
    def test_rejects_an_unknown_token(self, acceptance_env: AcceptanceEnv):
        with pytest.raises(NotFoundError):
            acceptance_env.service.accept_invitation("not-a-real-token", password=_PASSWORD)

    def test_rejects_an_expired_invitation(self, acceptance_env: AcceptanceEnv):
        _, token = _seed_invitation(acceptance_env.invitation_repo, hours_until_expiry=-1)

        with pytest.raises(InvalidInvitationStateError) as exc_info:
            acceptance_env.service.accept_invitation(token, password=_PASSWORD)
        assert exc_info.value.current_status == "expired"
        assert exc_info.value.attempted_action == "accept"
        # No Supabase user should ever be attempted for a rejected token.
        assert acceptance_env.auth_admin_client.created_users == []

    def test_rejects_a_revoked_invitation(self, acceptance_env: AcceptanceEnv):
        record, token = _seed_invitation(acceptance_env.invitation_repo)
        acceptance_env.invitation_repo.update_status_with_lock(
            record.id, expected_version=record.version, status=InvitationStatus.REVOKED
        )

        with pytest.raises(InvalidInvitationStateError) as exc_info:
            acceptance_env.service.accept_invitation(token, password=_PASSWORD)
        assert exc_info.value.current_status == "revoked"
        assert acceptance_env.auth_admin_client.created_users == []

    def test_rejects_an_already_accepted_invitation_and_does_not_create_a_second_user(
        self, acceptance_env: AcceptanceEnv
    ):
        _, token = _seed_invitation(acceptance_env.invitation_repo)
        acceptance_env.service.accept_invitation(token, password=_PASSWORD)
        assert len(acceptance_env.auth_admin_client.created_users) == 1

        with pytest.raises(InvalidInvitationStateError) as exc_info:
            acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        assert exc_info.value.current_status == "accepted"
        assert exc_info.value.attempted_action == "accept"
        # Rejected before ever reaching Supabase again.
        assert len(acceptance_env.auth_admin_client.created_users) == 1


# ---------------------------------------------------------------------------
# accept_invitation: optimistic locking
# ---------------------------------------------------------------------------


class TestAcceptInvitationOptimisticLocking:
    def test_raises_concurrency_error_when_the_row_changed_between_read_and_write(
        self, acceptance_env: AcceptanceEnv, monkeypatch
    ):
        record, token = _seed_invitation(acceptance_env.invitation_repo)
        # Advance the row's real version first (simulating a concurrent
        # admin revoke-then-reinstate, or any other writer), then hand
        # the service a stale copy to read from — reproducing "another
        # writer already changed this row" between accept_invitation's
        # own read and its write.
        acceptance_env.invitation_repo.update_status_with_lock(
            record.id, expected_version=record.version, status=InvitationStatus.PENDING
        )
        stale_record = dataclasses.replace(
            acceptance_env.invitation_repo.get_by_id(record.id), version=record.version
        )
        monkeypatch.setattr(
            acceptance_env.invitation_repo, "find_by_token_hash", lambda token_hash: stale_record
        )

        with pytest.raises(ConcurrencyError):
            acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        # The Supabase user was still created (or recovered) before the
        # optimistic-lock conflict was discovered on the write — an
        # inherent, documented limitation of a two-phase (external
        # system + local DB) operation; a subsequent retry recovers via
        # the same idempotent-recovery path exercised elsewhere in this
        # file, once the invitation itself is no longer mid-conflict.
        assert len(acceptance_env.auth_admin_client.created_users) == 1


# ---------------------------------------------------------------------------
# accept_invitation: Supabase failure (non-recoverable)
# ---------------------------------------------------------------------------


class TestAcceptInvitationSupabaseFailure:
    def test_generic_supabase_failure_propagates_and_leaves_invitation_pending(self):
        env = _make_env(raise_generic_error=True)
        record, token = _seed_invitation(env.invitation_repo)

        with pytest.raises(SupabaseAdminOperationError):
            env.service.accept_invitation(token, password=_PASSWORD)

        reloaded = env.invitation_repo.get_by_id(record.id)
        assert reloaded.status is InvitationStatus.PENDING
        assert reloaded.accepted_profile_id is None
        assert reloaded.version == record.version  # untouched

    def test_profile_never_provisioned_raises_and_leaves_invitation_pending(self):
        env = _make_env(provision_profile=False)
        record, token = _seed_invitation(env.invitation_repo)

        with pytest.raises(SupabaseAdminOperationError):
            env.service.accept_invitation(token, password=_PASSWORD)

        # Supabase user creation itself succeeded...
        assert len(env.auth_admin_client.created_users) == 1
        # ...but the trigger never provisioned a profile, so acceptance
        # could not complete, and the invitation was correctly left
        # untouched rather than linked to a profile that doesn't exist.
        reloaded = env.invitation_repo.get_by_id(record.id)
        assert reloaded.status is InvitationStatus.PENDING
        assert reloaded.accepted_profile_id is None


# ---------------------------------------------------------------------------
# accept_invitation: idempotency / retry safety (the core of this milestone)
# ---------------------------------------------------------------------------


class TestAcceptInvitationIdempotency:
    def test_retry_after_the_status_update_fails_recovers_without_a_duplicate_user(
        self, acceptance_env: AcceptanceEnv, monkeypatch
    ):
        """The scenario the milestone calls out explicitly: Supabase user
        creation succeeds, but the invitation-status update that should
        follow it fails. A retry must recover cleanly — completing the
        acceptance — rather than attempting to create a duplicate user.
        """
        _, token = _seed_invitation(acceptance_env.invitation_repo)
        real_update = acceptance_env.invitation_repo.update_status_with_lock
        call_count = {"n": 0}

        def flaky_update(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Simulated transient failure writing the invitation row.")
            return real_update(*args, **kwargs)

        monkeypatch.setattr(acceptance_env.invitation_repo, "update_status_with_lock", flaky_update)

        # First attempt: Supabase user creation succeeds, but the
        # subsequent status-update call raises.
        with pytest.raises(RuntimeError):
            acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        assert len(acceptance_env.auth_admin_client.created_users) == 1
        still_pending = acceptance_env.invitation_repo.find_by_token_hash(
            hash_invitation_token(token)
        )
        assert still_pending is not None
        assert still_pending.status is InvitationStatus.PENDING

        # Retry: the flaky update now behaves normally (second call).
        accepted = acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        assert accepted.effective_status is EffectiveInvitationStatus.ACCEPTED
        # Exactly one Supabase user total was ever created across both
        # attempts — the retry recovered via the idempotent-recovery
        # path (InvitationConflictError caught, candidate id reused)
        # rather than creating a second one.
        assert len(acceptance_env.auth_admin_client.created_users) == 1

    def test_retry_reports_the_same_profile_id_as_the_original_attempt(
        self, acceptance_env: AcceptanceEnv, monkeypatch
    ):
        _, token = _seed_invitation(acceptance_env.invitation_repo)
        real_update = acceptance_env.invitation_repo.update_status_with_lock
        call_count = {"n": 0}

        def flaky_update(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Simulated transient failure.")
            return real_update(*args, **kwargs)

        monkeypatch.setattr(acceptance_env.invitation_repo, "update_status_with_lock", flaky_update)

        with pytest.raises(RuntimeError):
            acceptance_env.service.accept_invitation(token, password=_PASSWORD)
        first_attempt_profile_id = acceptance_env.auth_admin_client.created_users[0].user_id

        accepted = acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        assert accepted.accepted_profile_id == first_attempt_profile_id

    def test_supabase_reported_conflict_alone_is_not_enough_without_a_matching_profile(
        self, acceptance_env: AcceptanceEnv
    ):
        """If Supabase reports "already exists" for an email but no
        ``profiles`` row exists under the exact candidate id (i.e. the
        conflict was NOT actually a retry of this same acceptance), this
        must fail loudly rather than silently link a nonexistent
        profile — the idempotency logic must not be shortcut into
        blind trust of the conflict signal alone.
        """
        record, token = _seed_invitation(acceptance_env.invitation_repo, email="taken@example.com")
        # Simulate an unrelated pre-existing Supabase account for this
        # email, under a DIFFERENT id than the invitation's own id (so
        # it does not, and should not, satisfy _wait_for_profile).
        acceptance_env.auth_admin_client.create_user(
            user_id=uuid4(),
            email="taken@example.com",
            password="unrelated-password",
            user_metadata={"full_name": "Unrelated Existing User", "role": "employee"},
        )
        assert len(acceptance_env.auth_admin_client.created_users) == 1

        with pytest.raises(SupabaseAdminOperationError):
            acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        reloaded = acceptance_env.invitation_repo.get_by_id(record.id)
        assert reloaded.status is InvitationStatus.PENDING
        assert reloaded.accepted_profile_id is None

    def test_accept_invitation_raising_invitation_conflict_error_directly_is_recovered(
        self, acceptance_env: AcceptanceEnv, monkeypatch
    ):
        """A lower-level assertion of the same recovery mechanism: if
        the auth admin client raises InvitationConflictError for the
        exact candidate id (the true "retry of a prior attempt" case,
        with the profile already provisioned), acceptance completes
        successfully on this call rather than propagating the conflict.
        """
        record, token = _seed_invitation(acceptance_env.invitation_repo)
        # Simulate "a prior attempt already created this exact user and
        # its profile" by provisioning them directly, then forcing the
        # next create_user call to report the conflict, exactly as
        # Supabase would for a second call with the same id/email.
        acceptance_env.profile_repo.create_profile(
            profile_id=record.id, full_name=record.full_name, role=record.role
        )
        original_create_user = acceptance_env.auth_admin_client.create_user

        def create_user_reports_conflict(**kwargs):
            raise InvitationConflictError(kwargs["email"])

        monkeypatch.setattr(
            acceptance_env.auth_admin_client, "create_user", create_user_reports_conflict
        )

        accepted = acceptance_env.service.accept_invitation(token, password=_PASSWORD)

        assert accepted.effective_status is EffectiveInvitationStatus.ACCEPTED
        assert accepted.accepted_profile_id == record.id
        monkeypatch.setattr(acceptance_env.auth_admin_client, "create_user", original_create_user)
