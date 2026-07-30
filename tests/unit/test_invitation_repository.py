"""Unit tests for the ``user_invitations`` persistence layer (Enterprise
User Onboarding architecture, Milestone 1).

Two things are exercised here, both without any network/database
dependency:

- ``_map_invitation_row``, the real, unmodified row-mapping function from
  ``app.database.repositories.invitation_repository`` — the one piece of
  that module's logic testable without a live Supabase client.
- ``FakeInvitationRepository`` (``tests/fixtures/fakes.py``), an
  in-memory analogue exposing the exact same public method signatures as
  the real ``InvitationRepository``, following this project's existing
  fake-repository testing convention (see ``tests/fixtures/fakes.py``'s
  module docstring). No ``InvitationService`` exists yet as of this
  milestone, so these tests exercise the repository contract directly
  rather than through a service.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.database.exceptions import ConcurrentUpdateError, InvalidQueryError, RecordNotFoundError
from app.database.repositories.base_repository import Page
from app.database.repositories.invitation_repository import _map_invitation_row
from app.models.enums import InvitationStatus, UserRole
from app.utils.datetime_utils import utc_now
from tests.fixtures.fakes import FakeInvitationRepository

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _map_invitation_row
# ---------------------------------------------------------------------------


class TestMapInvitationRow:
    def test_maps_every_field_from_a_full_row(self):
        invitation_id = uuid4()
        invited_by = uuid4()
        accepted_profile_id = uuid4()
        row = {
            "id": str(invitation_id),
            "email": "new.hire@example.com",
            "full_name": "New Hire",
            "role": "approver",
            "department": "finance",
            "token_hash": "a" * 64,
            "status": "accepted",
            "invited_by": str(invited_by),
            "expires_at": "2026-07-23T00:00:00+00:00",
            "accepted_at": "2026-07-21T00:00:00+00:00",
            "revoked_at": None,
            "accepted_profile_id": str(accepted_profile_id),
            "resend_count": 2,
            "version": 3,
            "created_at": "2026-07-20T00:00:00+00:00",
            "updated_at": "2026-07-21T00:00:00+00:00",
            "company_id": str(uuid4()),
        }

        record = _map_invitation_row(row)

        assert record.id == invitation_id
        assert record.email == "new.hire@example.com"
        assert record.full_name == "New Hire"
        assert record.role is UserRole.APPROVER
        assert record.department == "finance"
        assert record.token_hash == "a" * 64
        assert record.status is InvitationStatus.ACCEPTED
        assert record.invited_by == invited_by
        assert record.accepted_profile_id == accepted_profile_id
        assert record.resend_count == 2
        assert record.version == 3
        assert record.revoked_at is None

    def test_maps_optional_fields_as_none_when_absent(self):
        invitation_id = uuid4()
        invited_by = uuid4()
        row = {
            "id": str(invitation_id),
            "email": "pending.invite@example.com",
            "full_name": "Pending Invite",
            "role": "employee",
            "department": None,
            "token_hash": "b" * 64,
            "status": "pending",
            "invited_by": str(invited_by),
            "expires_at": "2026-07-23T00:00:00+00:00",
            "accepted_at": None,
            "revoked_at": None,
            "accepted_profile_id": None,
            "resend_count": 0,
            "version": 1,
            "created_at": "2026-07-20T00:00:00+00:00",
            "updated_at": "2026-07-20T00:00:00+00:00",
            "company_id": str(uuid4()),
        }

        record = _map_invitation_row(row)

        assert record.department is None
        assert record.accepted_at is None
        assert record.revoked_at is None
        assert record.accepted_profile_id is None
        assert record.status is InvitationStatus.PENDING


# ---------------------------------------------------------------------------
# FakeInvitationRepository
# ---------------------------------------------------------------------------


def _create(
    repo: FakeInvitationRepository,
    *,
    email: str = "invitee@example.com",
    full_name: str = "Invitee Person",
    role: UserRole = UserRole.EMPLOYEE,
    department: str | None = None,
    token_hash: str = "token-hash-1",
    hours_until_expiry: float = 72.0,
    invited_by=None,
):
    return repo.create_invitation(
        email=email,
        full_name=full_name,
        role=role,
        department=department,
        token_hash=token_hash,
        expires_at=utc_now() + timedelta(hours=hours_until_expiry),
        invited_by=invited_by if invited_by is not None else uuid4(),
    )


class TestCreateInvitation:
    def test_create_invitation_defaults_to_pending_with_zero_resend_count(self):
        repo = FakeInvitationRepository()

        created = _create(repo)

        assert created.status is InvitationStatus.PENDING
        assert created.resend_count == 0
        assert created.version == 1
        assert created.accepted_at is None
        assert created.revoked_at is None
        assert created.accepted_profile_id is None

    def test_create_invitation_raises_when_a_pending_invitation_already_exists_for_the_email(self):
        repo = FakeInvitationRepository()
        _create(repo, email="duplicate@example.com")

        with pytest.raises(InvalidQueryError):
            _create(repo, email="duplicate@example.com")

    def test_create_invitation_email_uniqueness_check_is_case_insensitive(self):
        repo = FakeInvitationRepository()
        _create(repo, email="Case.Sensitive@Example.com")

        with pytest.raises(InvalidQueryError):
            _create(repo, email="case.sensitive@example.com")

    def test_create_invitation_allowed_again_once_the_prior_one_is_no_longer_pending(self):
        repo = FakeInvitationRepository()
        first = _create(repo, email="repeat@example.com")
        repo.update_status_with_lock(
            first.id, expected_version=first.version, status=InvitationStatus.REVOKED
        )

        second = _create(repo, email="repeat@example.com")

        assert second.id != first.id
        assert second.status is InvitationStatus.PENDING


class TestGetAndFind:
    def test_get_by_id_raises_not_found_for_an_unknown_invitation(self):
        repo = FakeInvitationRepository()

        with pytest.raises(RecordNotFoundError):
            repo.get_by_id(uuid4())

    def test_find_by_id_returns_none_for_an_unknown_invitation(self):
        repo = FakeInvitationRepository()

        assert repo.find_by_id(uuid4()) is None

    def test_get_by_id_returns_the_created_record(self):
        repo = FakeInvitationRepository()
        created = _create(repo)

        fetched = repo.get_by_id(created.id)

        assert fetched.id == created.id
        assert fetched.email == created.email

    def test_find_by_token_hash_returns_the_matching_invitation(self):
        repo = FakeInvitationRepository()
        created = _create(repo, token_hash="the-real-token-hash")

        found = repo.find_by_token_hash("the-real-token-hash")

        assert found is not None
        assert found.id == created.id

    def test_find_by_token_hash_returns_none_for_an_unknown_token(self):
        repo = FakeInvitationRepository()
        _create(repo, token_hash="some-other-hash")

        assert repo.find_by_token_hash("not-a-real-hash") is None

    def test_find_pending_by_email_matches_case_insensitively(self):
        repo = FakeInvitationRepository()
        _create(repo, email="Mixed.Case@Example.com")

        found = repo.find_pending_by_email("mixed.case@example.com")

        assert found is not None

    def test_find_pending_by_email_ignores_non_pending_invitations(self):
        repo = FakeInvitationRepository()
        created = _create(repo, email="accepted@example.com")
        repo.update_status_with_lock(
            created.id, expected_version=created.version, status=InvitationStatus.ACCEPTED
        )

        assert repo.find_pending_by_email("accepted@example.com") is None


class TestListInvitations:
    def test_list_invitations_filters_by_status(self):
        repo = FakeInvitationRepository()
        pending = _create(repo, email="still-pending@example.com")
        accepted = _create(repo, email="already-accepted@example.com")
        repo.update_status_with_lock(
            accepted.id, expected_version=accepted.version, status=InvitationStatus.ACCEPTED
        )

        result = repo.list_invitations(status=InvitationStatus.PENDING)

        assert [i.id for i in result.items] == [pending.id]

    def test_list_invitations_query_matches_full_name_or_email(self):
        repo = FakeInvitationRepository()
        by_name = _create(repo, email="a@example.com", full_name="Zara Zebra")
        by_email = _create(repo, email="findme@example.com", full_name="Someone Else")
        _create(repo, email="unrelated@example.com", full_name="Unrelated Person")

        matched_ids = {i.id for i in repo.list_invitations(query="zebra").items}
        assert matched_ids == {by_name.id}

        matched_ids = {i.id for i in repo.list_invitations(query="findme").items}
        assert matched_ids == {by_email.id}

    def test_list_invitations_raises_on_an_empty_query(self):
        repo = FakeInvitationRepository()

        with pytest.raises(InvalidQueryError):
            repo.list_invitations(query="   ")

    def test_list_invitations_orders_newest_first_and_paginates(self):
        repo = FakeInvitationRepository()
        first = _create(repo, email="one@example.com")
        second = _create(repo, email="two@example.com")

        result = repo.list_invitations(page=Page(number=1, size=1))

        assert result.total_records == 2
        assert result.items[0].id == second.id
        assert first.id not in [i.id for i in result.items]

    def test_list_invitations_filters_by_expires_after(self):
        repo = FakeInvitationRepository()
        fresh = _create(repo, email="fresh@example.com", hours_until_expiry=1)
        repo.create_invitation(
            email="stale@example.com",
            full_name="Stale",
            token_hash="stale-hash",
            expires_at=utc_now() - timedelta(hours=1),
            invited_by=uuid4(),
        )
        reference_now = utc_now()

        result = repo.list_invitations(expires_after=reference_now)

        assert [i.id for i in result.items] == [fresh.id]

    def test_list_invitations_filters_by_expires_at_or_before(self):
        repo = FakeInvitationRepository()
        _create(repo, email="fresh@example.com", hours_until_expiry=1)
        stale = repo.create_invitation(
            email="stale@example.com",
            full_name="Stale",
            token_hash="stale-hash",
            expires_at=utc_now() - timedelta(hours=1),
            invited_by=uuid4(),
        )
        reference_now = utc_now()

        result = repo.list_invitations(expires_at_or_before=reference_now)

        assert [i.id for i in result.items] == [stale.id]


class TestUpdateStatusWithLock:
    def test_transitions_status_and_increments_version(self):
        repo = FakeInvitationRepository()
        created = _create(repo)

        updated = repo.update_status_with_lock(
            created.id, expected_version=created.version, status=InvitationStatus.REVOKED
        )

        assert updated.status is InvitationStatus.REVOKED
        assert updated.version == created.version + 1

    def test_raises_concurrent_update_error_on_a_stale_version(self):
        repo = FakeInvitationRepository()
        created = _create(repo)
        repo.update_status_with_lock(
            created.id, expected_version=created.version, status=InvitationStatus.REVOKED
        )

        with pytest.raises(ConcurrentUpdateError):
            repo.update_status_with_lock(
                created.id, expected_version=created.version, status=InvitationStatus.ACCEPTED
            )

    def test_only_applies_explicitly_provided_optional_fields(self):
        repo = FakeInvitationRepository()
        created = _create(repo, token_hash="original-hash")

        updated = repo.update_status_with_lock(
            created.id, expected_version=created.version, status=InvitationStatus.PENDING
        )

        assert updated.token_hash == "original-hash"
        assert updated.accepted_at is None
        assert updated.accepted_profile_id is None

    def test_accept_transition_sets_accepted_at_and_profile_id(self):
        repo = FakeInvitationRepository()
        created = _create(repo)
        accepted_profile_id = uuid4()
        now = utc_now()

        updated = repo.update_status_with_lock(
            created.id,
            expected_version=created.version,
            status=InvitationStatus.ACCEPTED,
            accepted_at=now,
            accepted_profile_id=accepted_profile_id,
        )

        assert updated.status is InvitationStatus.ACCEPTED
        assert updated.accepted_at == now
        assert updated.accepted_profile_id == accepted_profile_id

    def test_resend_transition_rotates_token_extends_expiry_and_bumps_resend_count(self):
        repo = FakeInvitationRepository()
        created = _create(repo, token_hash="old-hash")
        new_expiry = utc_now() + timedelta(hours=72)

        updated = repo.update_status_with_lock(
            created.id,
            expected_version=created.version,
            status=InvitationStatus.PENDING,
            token_hash="new-hash",
            expires_at=new_expiry,
            resend_count=created.resend_count + 1,
        )

        assert updated.token_hash == "new-hash"
        assert updated.expires_at == new_expiry
        assert updated.resend_count == 1
