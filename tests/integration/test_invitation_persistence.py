"""Real-database tests for the Enterprise User Onboarding invitation
feature (Milestone 9's Integration Tests requirement).

Every other test file in this directory exercises a feature that
predates the invitation work; this file is the first real-Postgres
coverage the invitation feature has ever had — every previous milestone's
invitation tests (``tests/unit/test_invitation_*.py``,
``tests/unit/test_api_*_invitations.py``) run exclusively against
``FakeInvitationRepository`` (an in-memory, plain-Python analogue that,
by its own module docstring, "can't exercise real PostgREST ILIKE
semantics"). This file closes that gap: partial unique index behavior,
optimistic-locking rejection, real Supabase Auth Admin API profile
provisioning, RLS policy enforcement, and — the most important gap a fake
repository structurally cannot cover — that the Milestone 9 search/filter
escaping fix (``escape_ilike_special_characters``/
``quote_postgrest_filter_value``, ``base_repository.py``) actually
produces the intended literal-match behavior against a real PostgREST
wire request, not just the intended Python string transformation.

See ``tests/integration/README.md`` for how to point this suite at a
disposable test Supabase project; every fixture here (and in
``tests/integration/conftest.py``) skips, rather than fails, when no test
database is configured, matching this directory's existing, documented
posture — this file introduces no new such limitation.
"""

from __future__ import annotations

import contextlib
import dataclasses
import uuid
from datetime import timedelta

import psycopg
import pytest

from app.database.exceptions import ConcurrentUpdateError, ConstraintViolationError
from app.database.repositories.base_repository import Page
from app.database.repositories.invitation_repository import InvitationStatus
from app.models.enums import UserRole
from app.services.invitation_service import (
    InvitationService,
    generate_invitation_token,
    hash_invitation_token,
)
from app.services.supabase_admin_client import SupabaseAuthAdminClientImpl
from app.utils.datetime_utils import utc_now

pytestmark = pytest.mark.integration


def _unique_email(label: str) -> str:
    return f"itest.{label}.{uuid.uuid4().hex[:10]}@example.invalid"


@dataclasses.dataclass
class InvitationCleanupTracker:
    """Collects everything a test creates so it can be torn down in the
    correct FK-safe order — see ``invitation_cleanup``'s own docstring.
    """

    invitation_ids: list[uuid.UUID] = dataclasses.field(default_factory=list)
    accepted_profile_ids: list[uuid.UUID] = dataclasses.field(default_factory=list)


@pytest.fixture
def invitation_cleanup(_committing_pg_conn, supabase_service_client, make_test_profile):
    """Deletes every ``user_invitations`` row (and any Supabase user
    created by accepting one) a test registers here, before
    ``make_test_profile``'s own teardown deletes the ``profiles`` row(s)
    those invitations reference.

    Necessary because ``user_invitations.invited_by`` and
    ``user_invitations.accepted_profile_id`` both reference
    ``profiles(id)`` with no ``ON DELETE CASCADE`` (migration 0007's own
    schema) — deleting a referenced profile first would fail with a
    foreign-key violation. Taking ``make_test_profile`` as a parameter
    (even though it is never called directly here) forces pytest to set
    it up *before* this fixture, which — by pytest's LIFO fixture
    teardown order — guarantees this fixture's own teardown (invitation
    rows, then accepted-invitation Supabase users) runs *before*
    ``make_test_profile``'s teardown deletes the inviting/anchor
    profiles, exactly the FK-safe order required.
    """
    tracker = InvitationCleanupTracker()
    yield tracker

    if tracker.invitation_ids:
        with _committing_pg_conn.cursor() as cur:
            cur.execute(
                "delete from public.user_invitations where id = any(%s);",
                ([str(i) for i in tracker.invitation_ids],),
            )
    for profile_id in tracker.accepted_profile_ids:
        with contextlib.suppress(Exception):  # best-effort, matches _cleanup_profiles
            supabase_service_client.auth.admin.delete_user(str(profile_id))


@pytest.fixture
def invitation_service(real_repos, supabase_service_client) -> InvitationService:
    """A real, unmodified ``InvitationService`` wired to the test
    project's real repositories and real Supabase Auth Admin API — no
    fakes anywhere in this object graph."""
    return InvitationService(
        invitation_repo=real_repos.invitation,
        profile_repo=real_repos.profile,
        audit_repo=real_repos.audit,
        auth_admin_client=SupabaseAuthAdminClientImpl(supabase_service_client),
        email_sender=None,
    )


class TestInvitationCreation:
    def test_create_invitation_persists_all_fields(
        self, real_repos, make_test_profile, invitation_cleanup
    ):
        admin = make_test_profile(role=UserRole.ADMIN)
        email = _unique_email("create")

        created = real_repos.invitation.create_invitation(
            email=email,
            full_name="Ivy Integration",
            role=UserRole.EMPLOYEE,
            department="sales",
            token_hash="a" * 64,
            expires_at=utc_now() + timedelta(hours=72),
            invited_by=admin.id,
        )
        invitation_cleanup.invitation_ids.append(created.id)

        reloaded = real_repos.invitation.get_by_id(created.id)
        assert reloaded.email == email
        assert reloaded.full_name == "Ivy Integration"
        assert reloaded.role is UserRole.EMPLOYEE
        assert reloaded.department == "sales"
        assert reloaded.status is InvitationStatus.PENDING
        assert reloaded.invited_by == admin.id
        assert reloaded.resend_count == 0
        assert reloaded.version == 1

    def test_a_second_pending_invitation_for_the_same_email_violates_the_partial_unique_index(
        self, real_repos, make_test_profile, invitation_cleanup
    ):
        """The database-level backstop
        ``user_invitations_pending_email_idx`` (migration 0007) — the
        race two admins concurrently inviting the same address closes,
        independent of ``InvitationService.create_invitation``'s own
        ``find_pending_by_email`` pre-check.
        """
        admin = make_test_profile(role=UserRole.ADMIN)
        email = _unique_email("duplicate")
        first = real_repos.invitation.create_invitation(
            email=email,
            full_name="First Attempt",
            token_hash="b" * 64,
            expires_at=utc_now() + timedelta(hours=72),
            invited_by=admin.id,
        )
        invitation_cleanup.invitation_ids.append(first.id)

        with pytest.raises(ConstraintViolationError):
            real_repos.invitation.create_invitation(
                email=email.upper(),  # case-insensitive index - must still collide
                full_name="Second Attempt",
                token_hash="c" * 64,
                expires_at=utc_now() + timedelta(hours=72),
                invited_by=admin.id,
            )

    def test_a_new_pending_invitation_is_allowed_once_the_first_is_revoked(
        self, real_repos, make_test_profile, invitation_cleanup
    ):
        """Proves the partial index's ``where status = 'pending'`` scope
        is real: revoking the first invitation frees its email address
        for a brand-new pending invitation, which a non-partial unique
        index on ``lower(email)`` alone would incorrectly still reject.
        """
        admin = make_test_profile(role=UserRole.ADMIN)
        email = _unique_email("revoke-then-reinvite")
        first = real_repos.invitation.create_invitation(
            email=email,
            full_name="First",
            token_hash="d" * 64,
            expires_at=utc_now() + timedelta(hours=72),
            invited_by=admin.id,
        )
        invitation_cleanup.invitation_ids.append(first.id)
        real_repos.invitation.update_status_with_lock(
            first.id,
            expected_version=first.version,
            status=InvitationStatus.REVOKED,
            revoked_at=utc_now(),
        )

        second = real_repos.invitation.create_invitation(
            email=email,
            full_name="Second",
            token_hash="e" * 64,
            expires_at=utc_now() + timedelta(hours=72),
            invited_by=admin.id,
        )
        invitation_cleanup.invitation_ids.append(second.id)

        assert second.email == email
        assert second.status is InvitationStatus.PENDING


class TestOptimisticLocking:
    def test_a_stale_version_update_is_rejected_by_the_real_database(
        self, real_repos, make_test_profile, invitation_cleanup
    ):
        admin = make_test_profile(role=UserRole.ADMIN)
        created = real_repos.invitation.create_invitation(
            email=_unique_email("optimistic-lock"),
            full_name="Lock Test",
            token_hash="f" * 64,
            expires_at=utc_now() + timedelta(hours=72),
            invited_by=admin.id,
        )
        invitation_cleanup.invitation_ids.append(created.id)
        assert created.version == 1

        updated = real_repos.invitation.update_status_with_lock(
            created.id,
            expected_version=1,
            status=InvitationStatus.REVOKED,
            revoked_at=utc_now(),
        )
        assert updated.version == 2

        # A second write against the now-stale version 1 - simulating a
        # second admin who read the row before the first revoke
        # committed - is rejected by the real `WHERE version = 1`
        # predicate matching zero rows.
        with pytest.raises(ConcurrentUpdateError):
            real_repos.invitation.update_status_with_lock(
                created.id,
                expected_version=1,
                status=InvitationStatus.REVOKED,
                revoked_at=utc_now(),
            )


class TestAcceptanceAndProfileCreation:
    def test_accepting_an_invitation_provisions_a_real_profile_via_the_service(
        self, real_repos, make_test_profile, invitation_cleanup, invitation_service
    ):
        """End-to-end through the real, unmodified ``InvitationService``
        — token generation/hashing, the real Supabase Auth Admin API
        (``SupabaseAuthAdminClientImpl``), the real
        ``on_auth_user_created`` trigger (migration 0002) provisioning
        ``profiles``, and the real optimistic-locked status transition —
        with no fake anywhere in the chain.
        """
        admin = make_test_profile(role=UserRole.ADMIN)
        raw_token = generate_invitation_token()
        created = real_repos.invitation.create_invitation(
            email=_unique_email("accept"),
            full_name="Accepted Invitee",
            role=UserRole.APPROVER,
            department="finance",
            token_hash=hash_invitation_token(raw_token),
            expires_at=utc_now() + timedelta(hours=72),
            invited_by=admin.id,
        )
        invitation_cleanup.invitation_ids.append(created.id)
        invitation_cleanup.accepted_profile_ids.append(created.id)  # deterministic id scheme

        accepted = invitation_service.accept_invitation(raw_token, password="Correct-Horse-42!")

        assert accepted.effective_status.value == "accepted"
        assert accepted.accepted_profile_id is not None

        provisioned_profile = real_repos.profile.get_by_id(accepted.accepted_profile_id)
        assert provisioned_profile.role is UserRole.APPROVER
        assert provisioned_profile.full_name == "Accepted Invitee"

        reloaded_invitation = real_repos.invitation.get_by_id(created.id)
        assert reloaded_invitation.status is InvitationStatus.ACCEPTED
        assert reloaded_invitation.accepted_profile_id == provisioned_profile.id


class TestEffectiveStatusFiltering:
    def test_expires_after_and_expires_at_or_before_correctly_partition_rows(
        self, real_repos, make_test_profile, invitation_cleanup
    ):
        """The real-database counterpart to
        ``tests/unit/test_invitation_service.py``'s fake-backed
        regression test for the Milestone 1-5 cleanup pass — proves
        ``list_invitations``'s ``expires_after``/``expires_at_or_before``
        filters (and, by extension, ``InvitationService``'s
        effective-status computation built on them) produce an exact,
        correctly-partitioned result against real Postgres, not just
        against ``FakeInvitationRepository``'s Python re-implementation
        of the same filter.
        """
        admin = make_test_profile(role=UserRole.ADMIN)
        reference_now = utc_now()
        fresh = real_repos.invitation.create_invitation(
            email=_unique_email("fresh"),
            full_name="Fresh Invitee",
            token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            expires_at=reference_now + timedelta(hours=1),
            invited_by=admin.id,
        )
        stale = real_repos.invitation.create_invitation(
            email=_unique_email("stale"),
            full_name="Stale Invitee",
            token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            expires_at=reference_now - timedelta(hours=1),
            invited_by=admin.id,
        )
        invitation_cleanup.invitation_ids.extend([fresh.id, stale.id])

        pending_effective = real_repos.invitation.list_invitations(
            status=InvitationStatus.PENDING, expires_after=reference_now, page=Page(size=100)
        )
        expired_effective = real_repos.invitation.list_invitations(
            status=InvitationStatus.PENDING,
            expires_at_or_before=reference_now,
            page=Page(size=100),
        )

        assert fresh.id in [i.id for i in pending_effective.items]
        assert stale.id not in [i.id for i in pending_effective.items]
        assert stale.id in [i.id for i in expired_effective.items]
        assert fresh.id not in [i.id for i in expired_effective.items]


class TestSearchEscapingAgainstRealPostgres:
    """The core value-add this file exists for: proving the Milestone 9
    search/filter-injection fix produces the intended behavior against a
    genuine PostgREST wire request, which
    ``FakeInvitationRepository``'s in-memory Python matching cannot
    exercise (confirmed by that fake's own module-level docstring note).
    """

    def test_a_literal_percent_in_the_search_term_is_not_treated_as_an_ilike_wildcard(
        self, real_repos, make_test_profile, invitation_cleanup
    ):
        admin = make_test_profile(role=UserRole.ADMIN)
        unique = uuid.uuid4().hex[:8]
        literal_percent = real_repos.invitation.create_invitation(
            email=_unique_email("percent"),
            full_name=f"{unique} 50% Off Deal",
            token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            expires_at=utc_now() + timedelta(hours=72),
            invited_by=admin.id,
        )
        decoy = real_repos.invitation.create_invitation(
            email=_unique_email("decoy"),
            full_name=f"{unique} 50X Off Deal",
            token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            expires_at=utc_now() + timedelta(hours=72),
            invited_by=admin.id,
        )
        invitation_cleanup.invitation_ids.extend([literal_percent.id, decoy.id])

        # If "%" were sent to Postgres unescaped, ILIKE would interpret
        # it as "any sequence of characters", matching both rows. Escaped
        # correctly, only the row with a literal "%" matches.
        result = real_repos.invitation.list_invitations(query=f"{unique} 50%", page=Page(size=100))

        matched_ids = {i.id for i in result.items}
        assert literal_percent.id in matched_ids
        assert decoy.id not in matched_ids

    def test_find_pending_by_email_matches_case_insensitively_and_exactly(
        self, real_repos, make_test_profile, invitation_cleanup
    ):
        admin = make_test_profile(role=UserRole.ADMIN)
        email = _unique_email("Case.Sensitive")
        created = real_repos.invitation.create_invitation(
            email=email,
            full_name="Case Test",
            token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            expires_at=utc_now() + timedelta(hours=72),
            invited_by=admin.id,
        )
        invitation_cleanup.invitation_ids.append(created.id)

        found = real_repos.invitation.find_pending_by_email(email.upper())

        assert found is not None
        assert found.id == created.id

    def test_a_search_term_containing_comma_and_parenthesis_never_breaks_the_or_filter(
        self, real_repos, make_test_profile, invitation_cleanup
    ):
        """The ``quote_postgrest_filter_value`` fix's real-world proof:
        a free-text search containing PostgREST's own filter-structural
        characters (``,``/``)``) must be treated as a literal substring
        to search for, never as syntax that restructures the ``.or_()``
        clause itself (which — since this repository runs on the
        service-role client, bypassing RLS — would otherwise be a real
        authorization-relevant injection, not just a search-quality bug).
        """
        admin = make_test_profile(role=UserRole.ADMIN)
        unique = uuid.uuid4().hex[:8]
        created = real_repos.invitation.create_invitation(
            email=_unique_email("structural"),
            full_name=f"{unique} Ordinary Name",
            token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            expires_at=utc_now() + timedelta(hours=72),
            invited_by=admin.id,
        )
        invitation_cleanup.invitation_ids.append(created.id)

        malicious_query = f'{unique}",email.ilike."%,status.eq.accepted'

        # Must not raise (a malformed/unescaped filter sent to PostgREST
        # would surface as an InvalidQueryError/RepositoryError here) and
        # must not match anything, since no row's name/email actually
        # contains this literal payload.
        result = real_repos.invitation.list_invitations(query=malicious_query, page=Page())

        assert result.items == []
        assert result.total_records == 0


class TestRowLevelSecurity:
    """Defense-in-depth RLS coverage for ``user_invitations`` (migration
    0007's ``user_invitations_admin_all`` policy) — simulated via
    ``SET LOCAL ROLE``/``request.jwt.claims`` on the shared ``pg_conn``
    transaction, the standard technique for exercising Postgres RLS from
    raw SQL outside of an actual PostgREST request. This application's
    own repository layer always runs on the service-role client (which
    carries ``BYPASSRLS`` and is therefore unaffected by anything tested
    here, per every migration's own documented rationale) — this policy
    is a defense-in-depth backstop for a hypothetical anon-key caller,
    not this application's primary enforcement mechanism (that is
    ``InvitationService._authorize_admin``, already covered by
    ``tests/unit/test_invitation_service.py``).
    """

    def test_a_non_admin_authenticated_caller_cannot_see_invitations(
        self, pg_conn, make_test_profile
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        invitation_id = uuid.uuid4()
        with pg_conn.cursor() as cur:
            cur.execute(
                "insert into public.user_invitations "
                "(id, email, full_name, token_hash, expires_at, invited_by) "
                "values (%s, %s, %s, %s, now() + interval '72 hours', %s);",
                (
                    str(invitation_id),
                    _unique_email("rls"),
                    "RLS Test Subject",
                    uuid.uuid4().hex + uuid.uuid4().hex,
                    str(admin.id),
                ),
            )

            cur.execute("set local role authenticated;")
            cur.execute(
                "set local request.jwt.claims = %s;",
                (f'{{"sub": "{employee.id}"}}',),
            )
            cur.execute(
                "select id from public.user_invitations where id = %s;", (str(invitation_id),)
            )
            assert cur.fetchone() is None

    def test_an_admin_authenticated_caller_can_see_invitations(self, pg_conn, make_test_profile):
        admin = make_test_profile(role=UserRole.ADMIN)
        invitation_id = uuid.uuid4()
        with pg_conn.cursor() as cur:
            cur.execute(
                "insert into public.user_invitations "
                "(id, email, full_name, token_hash, expires_at, invited_by) "
                "values (%s, %s, %s, %s, now() + interval '72 hours', %s);",
                (
                    str(invitation_id),
                    _unique_email("rls-admin"),
                    "RLS Admin Subject",
                    uuid.uuid4().hex + uuid.uuid4().hex,
                    str(admin.id),
                ),
            )

            cur.execute("set local role authenticated;")
            cur.execute(
                "set local request.jwt.claims = %s;",
                (f'{{"sub": "{admin.id}"}}',),
            )
            cur.execute(
                "select id from public.user_invitations where id = %s;", (str(invitation_id),)
            )
            assert cur.fetchone() is not None

    def test_a_non_admin_authenticated_caller_cannot_insert_an_invitation(
        self, pg_conn, make_test_profile
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        with pg_conn.cursor() as cur:
            cur.execute("set local role authenticated;")
            cur.execute(
                "set local request.jwt.claims = %s;",
                (f'{{"sub": "{employee.id}"}}',),
            )
            # Postgres reports a row-level-security policy violation as
            # SQLSTATE 42501 ("new row violates row-level security
            # policy"), which psycopg maps to InsufficientPrivilege.
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(
                    "insert into public.user_invitations "
                    "(id, email, full_name, token_hash, expires_at, invited_by) "
                    "values (%s, %s, %s, %s, now() + interval '72 hours', %s);",
                    (
                        str(uuid.uuid4()),
                        _unique_email("rls-insert-denied"),
                        "Should Not Insert",
                        uuid.uuid4().hex + uuid.uuid4().hex,
                        str(employee.id),
                    ),
                )
