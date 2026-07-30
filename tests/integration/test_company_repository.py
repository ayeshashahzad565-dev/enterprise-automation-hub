"""Real-database tests for ``CompanyRepository``, ``CompanyLicenseRepository``,
and ``FeatureFlagRepository``.

Verifies migration ``0017_platform_admin`` (companies' soft-delete/settings
columns, ``company_licenses``, ``feature_flags``) against genuine
Postgres/postgrest: soft-delete/restore, the unique ``slug`` constraint,
license upsert insert-vs-update, and feature-flag CRUD.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from app.database.exceptions import ConcurrentUpdateError, ConstraintViolationError
from app.database.repositories.base_repository import Page

pytestmark = pytest.mark.integration


class TestCompanyRepositoryAgainstRealPostgres:
    def test_create_company_is_active_and_not_deleted(self, make_test_company):
        company = make_test_company()

        assert company.is_active is True
        assert company.deleted_at is None
        assert company.version == 1

    def test_duplicate_slug_is_rejected(self, real_repos, make_test_company):
        company = make_test_company()

        with pytest.raises(ConstraintViolationError):
            real_repos.company.create_company(name="Another Name", slug=company.slug)

    def test_soft_delete_then_restore_round_trip(self, real_repos, make_test_company, anchor_profile_id):
        company = make_test_company()

        deleted = real_repos.company.soft_delete(
            company.id, expected_version=company.version, deleted_by=anchor_profile_id
        )
        assert deleted.deleted_at is not None

        restored = real_repos.company.restore(company.id, expected_version=deleted.version)
        assert restored.deleted_at is None

    def test_list_companies_excludes_soft_deleted_by_default(
        self, real_repos, make_test_company, anchor_profile_id
    ):
        kept = make_test_company()
        deleted = make_test_company()
        real_repos.company.soft_delete(
            deleted.id, expected_version=deleted.version, deleted_by=anchor_profile_id
        )

        active_ids = {c.id for c in real_repos.company.list_companies(page=Page(size=100)).items}
        assert kept.id in active_ids
        assert deleted.id not in active_ids

    def test_update_company_settings_persists(self, real_repos, make_test_company):
        company = make_test_company()

        updated = real_repos.company.update_company(
            company.id,
            expected_version=company.version,
            contact_email="ops@example.invalid",
            notes="VIP customer",
        )

        assert updated.contact_email == "ops@example.invalid"
        assert updated.notes == "VIP customer"

    def test_concurrent_update_raises(self, real_repos, make_test_company):
        company = make_test_company()

        with pytest.raises(ConcurrentUpdateError):
            real_repos.company.update_company(
                company.id, expected_version=company.version + 1, name="New Name"
            )


class TestCompanyLicenseRepositoryAgainstRealPostgres:
    def test_get_for_company_is_none_when_unconfigured(self, real_repos, make_test_company):
        company = make_test_company()

        assert real_repos.company_license.get_for_company(company.id) is None

    def test_upsert_inserts_then_updates(self, real_repos, make_test_company):
        company = make_test_company()

        created = real_repos.company_license.upsert(
            company.id,
            plan_tier="free",
            seat_limit=None,
            expires_at=None,
            notes=None,
            updated_by=None,
        )
        assert created.plan_tier == "free"

        updated = real_repos.company_license.upsert(
            company.id,
            plan_tier="pro",
            seat_limit=10,
            expires_at=None,
            notes="upgraded",
            updated_by=None,
        )
        assert updated.plan_tier == "pro"
        assert updated.seat_limit == 10
        fetched = real_repos.company_license.get_for_company(company.id)
        assert fetched is not None
        assert fetched.plan_tier == "pro"


def _delete_flag(committing_conn: psycopg.Connection, key: str) -> None:
    """``FeatureFlagRepository`` exposes no delete method by design (only
    platform admins ever write this table, and deletion isn't a modeled
    operation) — tests clean up via a direct superuser connection instead,
    mirroring ``_cleanup_profiles``'s own "go around the Repository Layer
    for cleanup only" precedent.
    """
    with committing_conn.cursor() as cur:
        cur.execute("delete from public.feature_flags where key = %s;", (key,))


class TestFeatureFlagRepositoryAgainstRealPostgres:
    def test_create_get_list_update(self, real_repos, _committing_pg_conn: psycopg.Connection):
        key = f"itest_flag_{uuid.uuid4().hex[:8]}"
        try:
            created = real_repos.feature_flag.create(
                key=key, description="An integration-test flag", enabled=False, updated_by=None
            )
            assert created.enabled is False

            fetched = real_repos.feature_flag.get_by_key(key)
            assert fetched.key == key

            all_flags = real_repos.feature_flag.list_all()
            assert any(f.key == key for f in all_flags)

            updated = real_repos.feature_flag.update(key, enabled=True, updated_by=None)
            assert updated.enabled is True
        finally:
            _delete_flag(_committing_pg_conn, key)

    def test_duplicate_key_is_rejected(self, real_repos, _committing_pg_conn: psycopg.Connection):
        key = f"itest_flag_{uuid.uuid4().hex[:8]}"
        try:
            real_repos.feature_flag.create(
                key=key, description="First", enabled=False, updated_by=None
            )

            with pytest.raises(ConstraintViolationError):
                real_repos.feature_flag.create(
                    key=key, description="Duplicate", enabled=False, updated_by=None
                )
        finally:
            _delete_flag(_committing_pg_conn, key)
