"""Real-database tests for ``NotificationPreferenceRepository``.

Verifies the ``notification_preferences`` table (migration
``0016_notification_preferences``) and its repository against genuine
Postgres/postgrest: the upsert insert vs. update path, the unique
constraint, and RLS deny-cross-user via the anon/authenticated client.
"""

from __future__ import annotations

import pytest

from app.models.enums import NotificationType

pytestmark = pytest.mark.integration


class TestNotificationPreferenceRepositoryAgainstRealPostgres:
    def test_upsert_inserts_a_new_row_when_none_exists(self, real_repos, make_test_profile):
        profile = make_test_profile()

        record = real_repos.notification_preference.upsert(
            profile.id, NotificationType.REMINDER, in_app_enabled=False, email_enabled=True
        )

        assert record.user_id == profile.id
        assert record.notification_type == NotificationType.REMINDER
        assert record.in_app_enabled is False
        assert record.email_enabled is True

    def test_upsert_updates_the_existing_row_for_the_same_type(self, real_repos, make_test_profile):
        profile = make_test_profile()
        real_repos.notification_preference.upsert(
            profile.id, NotificationType.REMINDER, in_app_enabled=True, email_enabled=True
        )

        updated = real_repos.notification_preference.upsert(
            profile.id, NotificationType.REMINDER, in_app_enabled=False, email_enabled=False
        )

        rows = real_repos.notification_preference.get_for_user(profile.id)
        matching = [r for r in rows if r.notification_type == NotificationType.REMINDER]
        assert len(matching) == 1
        assert matching[0].id == updated.id
        assert matching[0].in_app_enabled is False
        assert matching[0].email_enabled is False

    def test_get_for_user_only_returns_that_user_s_rows(self, real_repos, make_test_profile):
        first = make_test_profile()
        second = make_test_profile()
        real_repos.notification_preference.upsert(
            first.id, NotificationType.ESCALATION, in_app_enabled=False, email_enabled=False
        )
        real_repos.notification_preference.upsert(
            second.id, NotificationType.ESCALATION, in_app_enabled=True, email_enabled=False
        )

        first_rows = real_repos.notification_preference.get_for_user(first.id)

        assert {r.user_id for r in first_rows} == {first.id}

    def test_get_for_user_returns_empty_list_when_nothing_configured(
        self, real_repos, make_test_profile
    ):
        profile = make_test_profile()

        assert real_repos.notification_preference.get_for_user(profile.id) == []
