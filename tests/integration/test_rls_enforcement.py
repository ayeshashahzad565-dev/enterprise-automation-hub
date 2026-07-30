"""Live-Postgres proof that Row-Level Security itself — not application
code — enforces per-user isolation on ``notification_preferences``.

Every other file in this suite either runs on the service-role client
(which carries ``BYPASSRLS`` and is therefore unaffected by any policy),
or exercises RLS indirectly via a raw-SQL ``SET LOCAL ROLE``/
``request.jwt.claims`` simulation (``TestRowLevelSecurity`` in
``test_invitation_persistence.py``). This file instead signs in as a
real user (``auth.sign_in_with_password``) and issues requests through
the same ``SupabaseClientFactory.create_user_scoped_client`` mechanism
``app.api.dependencies.bind_tenant_database_client`` binds for every real
authenticated request — the closest this suite gets to an actual
PostgREST call over a real JWT, without a running FastAPI process.

This closes a gap ``docs/tenant_isolation.md`` explicitly disclosed as
not yet done: "A live-Postgres integration test proving RLS actually
blocks a cross-tenant read under a real user JWT... needs a new
signed-in-user fixture." ``notification_preferences`` is the simplest
RLS-enforced table to prove this against — a single self-owned row, no
parent request/workflow/company setup required — but the same
``make_authenticated_user`` fixture applies equally to the other
RLS-enforced repositories listed in that document (Comment, Attachment,
SavedFilter, SearchHistory, WorkflowDefinition).

``NotificationPreferenceRepository.get_for_user`` and ``.upsert`` accept
whatever ``user_id`` the caller passes with no identity check of their
own (see ``app/database/repositories/notification_preference_repository.py``)
— by design, since enforcing that predicate is exactly what Postgres RLS
is for here. That makes these tests a genuine test of the database
policy, not a redundant restatement of an application-layer check.
"""

from __future__ import annotations

import pytest

from app.database.exceptions import DatabaseError
from app.database.repositories.notification_preference_repository import (
    NotificationPreferenceRepository,
)
from app.models.enums import NotificationType

pytestmark = pytest.mark.integration


class TestNotificationPreferenceRowLevelSecurity:
    def test_a_signed_in_user_can_read_their_own_preferences(
        self, real_repos, make_authenticated_user
    ):
        profile, sign_in = make_authenticated_user(full_name="RLS Self Read")
        real_repos.notification_preference.upsert(
            profile.id,
            NotificationType.ASSIGNMENT,
            in_app_enabled=False,
            email_enabled=True,
        )

        scoped_client = sign_in()
        scoped_repo = NotificationPreferenceRepository(
            scoped_client, always_use_injected_client=True
        )

        result = scoped_repo.get_for_user(profile.id)

        assert [r.notification_type for r in result] == [NotificationType.ASSIGNMENT]
        assert result[0].user_id == profile.id

    def test_a_signed_in_user_cannot_read_another_user_s_preferences(
        self, real_repos, make_authenticated_user
    ):
        victim, _ = make_authenticated_user(full_name="RLS Victim")
        _, attacker_sign_in = make_authenticated_user(full_name="RLS Attacker")
        real_repos.notification_preference.upsert(
            victim.id,
            NotificationType.ESCALATION,
            in_app_enabled=True,
            email_enabled=True,
        )

        scoped_client = attacker_sign_in()
        scoped_repo = NotificationPreferenceRepository(
            scoped_client, always_use_injected_client=True
        )

        # The repository method itself performs no ownership check — it
        # queries by whatever user_id it's given (see this module's
        # docstring). Only the `notification_preferences_select_own`
        # policy (`user_id = auth.uid()`) stands between the attacker and
        # the victim's row; if it ever regressed (e.g. dropped by a future
        # migration, or the RLS-enforced/service-role classification for
        # this repository flipped without the policy actually matching)
        # this assertion would fail as the victim's row leaks through.
        result = scoped_repo.get_for_user(victim.id)

        assert result == []

    def test_a_signed_in_user_cannot_write_another_user_s_preferences(
        self, make_authenticated_user
    ):
        victim, _ = make_authenticated_user(full_name="RLS Write Victim")
        _, attacker_sign_in = make_authenticated_user(full_name="RLS Write Attacker")

        scoped_client = attacker_sign_in()
        scoped_repo = NotificationPreferenceRepository(
            scoped_client, always_use_injected_client=True
        )

        # Postgres reports a row-level-security policy violation as
        # SQLSTATE 42501 ("new row violates row-level security policy"),
        # which this repository's generic exception translation surfaces
        # as a DatabaseError (see BaseRepository._translate_and_raise —
        # 42501 has no dedicated ConstraintViolationError subtype, unlike
        # unique/FK/check violations).
        with pytest.raises(DatabaseError):
            scoped_repo.upsert(
                victim.id,
                NotificationType.SYSTEM,
                in_app_enabled=False,
                email_enabled=False,
            )
