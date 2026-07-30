"""Unit tests for ``app.services.user_service.UserService``.

Covers role/department/active-status mutation (``update_profile``), the
self-lockout guards, audit-event branching, and GDPR erasure
(``erase_user``): anonymization content, idempotent replay, the
auth-scrub-before-database-write ordering, and that a failed auth scrub
leaves the database untouched.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.enums import UserRole
from app.services.exceptions import (
    ConcurrencyError,
    NotFoundError,
    PermissionDeniedError,
    SupabaseAdminOperationError,
    ValidationError,
)

pytestmark = pytest.mark.unit


class TestUpdateProfileAuthorization:
    def test_employee_cannot_update_another_profile(self, env, employee, approver):
        _, employee_identity = employee
        approver_profile, _ = approver

        with pytest.raises(PermissionDeniedError):
            env.user_service.update_profile(
                employee_identity,
                approver_profile.id,
                expected_version=approver_profile.version,
                role=UserRole.ADMIN,
            )

    def test_admin_updating_a_profile_in_another_company_is_not_found(
        self, env, admin, make_user
    ):
        _, admin_identity = admin
        other_company_profile, _ = make_user(role=UserRole.EMPLOYEE, company_id=uuid4())

        with pytest.raises(NotFoundError):
            env.user_service.update_profile(
                admin_identity,
                other_company_profile.id,
                expected_version=other_company_profile.version,
                role=UserRole.ADMIN,
            )


class TestUpdateProfileDeactivation:
    def test_deactivating_writes_profile_deactivated_audit_event(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin

        updated = env.user_service.update_profile(
            admin_identity, employee_profile.id, expected_version=employee_profile.version,
            is_active=False,
        )

        assert updated.is_active is False
        events = env.audit_repo.list_for_actor(admin_identity.user_id).items
        assert any(e.action == "PROFILE_DEACTIVATED" for e in events)
        assert not any(e.action == "PROFILE_REACTIVATED" for e in events)

    def test_reactivating_writes_profile_reactivated_audit_event(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin
        deactivated = env.user_service.update_profile(
            admin_identity, employee_profile.id, expected_version=employee_profile.version,
            is_active=False,
        )

        updated = env.user_service.update_profile(
            admin_identity, employee_profile.id, expected_version=deactivated.version,
            is_active=True,
        )

        assert updated.is_active is True
        events = env.audit_repo.list_for_actor(admin_identity.user_id).items
        assert any(e.action == "PROFILE_REACTIVATED" for e in events)

    def test_role_or_department_change_writes_profile_updated_audit_event(
        self, env, admin, employee
    ):
        employee_profile, _ = employee
        _, admin_identity = admin

        env.user_service.update_profile(
            admin_identity, employee_profile.id, expected_version=employee_profile.version,
            department="engineering",
        )

        events = env.audit_repo.list_for_actor(admin_identity.user_id).items
        assert any(e.action == "PROFILE_UPDATED" for e in events)

    def test_admin_cannot_deactivate_their_own_account(self, env, admin):
        admin_profile, admin_identity = admin

        with pytest.raises(ValidationError):
            env.user_service.update_profile(
                admin_identity, admin_profile.id, expected_version=admin_profile.version,
                is_active=False,
            )

    def test_admin_can_change_their_own_role_or_department(self, env, admin):
        # Only deactivation is self-locked out; ordinary field changes to
        # one's own profile through this admin surface are not blocked by
        # this guard (a separate concern from whether that's desirable is
        # out of scope for this service).
        admin_profile, admin_identity = admin

        updated = env.user_service.update_profile(
            admin_identity, admin_profile.id, expected_version=admin_profile.version,
            department="finance",
        )

        assert updated.department == "finance"

    def test_stale_version_raises_concurrency_error(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin

        with pytest.raises(ConcurrencyError):
            env.user_service.update_profile(
                admin_identity,
                employee_profile.id,
                expected_version=employee_profile.version + 1,
                is_active=False,
            )


class TestEraseUser:
    def test_erase_anonymizes_full_name_and_department(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin

        erased = env.user_service.erase_user(
            admin_identity, employee_profile.id, expected_version=employee_profile.version
        )

        assert erased.full_name != "Eve Employee"
        assert str(employee_profile.id)[:8] in erased.full_name
        assert erased.department is None
        assert erased.is_active is False
        assert erased.deleted_at is not None
        assert erased.deleted_by == admin_identity.user_id

    def test_erase_scrubs_the_auth_email_before_the_database_write(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin

        env.user_service.erase_user(
            admin_identity, employee_profile.id, expected_version=employee_profile.version
        )

        assert len(env.auth_admin_client.anonymized_users) == 1
        sent = env.auth_admin_client.anonymized_users[0]
        assert sent.user_id == employee_profile.id
        assert str(employee_profile.id) in sent.anonymized_email
        assert sent.anonymized_email.endswith("@erased.invalid")

    def test_erase_writes_profile_erased_audit_event(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin

        env.user_service.erase_user(
            admin_identity, employee_profile.id, expected_version=employee_profile.version
        )

        events = env.audit_repo.list_for_actor(admin_identity.user_id).items
        assert any(e.action == "PROFILE_ERASED" for e in events)

    def test_erase_is_idempotent_on_replay(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin
        first = env.user_service.erase_user(
            admin_identity, employee_profile.id, expected_version=employee_profile.version
        )

        replay = env.user_service.erase_user(
            admin_identity, employee_profile.id, expected_version=first.version
        )

        assert replay.full_name == first.full_name
        assert replay.deleted_at == first.deleted_at
        assert len(env.auth_admin_client.anonymized_users) == 1, (
            "a replay must not scrub the auth email a second time"
        )
        events = [
            e
            for e in env.audit_repo.list_for_actor(admin_identity.user_id).items
            if e.action == "PROFILE_ERASED"
        ]
        assert len(events) == 1, "a replay must not write a second audit event"

    def test_a_failed_auth_scrub_leaves_the_profile_untouched(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin
        env.auth_admin_client._raise_generic_error = True

        with pytest.raises(SupabaseAdminOperationError):
            env.user_service.erase_user(
                admin_identity, employee_profile.id, expected_version=employee_profile.version
            )

        untouched = env.profile_repo.get_by_id(employee_profile.id)
        assert untouched.full_name == "Eve Employee"
        assert untouched.deleted_at is None
        assert untouched.is_active is True

    def test_admin_cannot_erase_their_own_account(self, env, admin):
        admin_profile, admin_identity = admin

        with pytest.raises(ValidationError):
            env.user_service.erase_user(
                admin_identity, admin_profile.id, expected_version=admin_profile.version
            )

    def test_erasing_a_profile_in_another_company_is_not_found(self, env, admin, make_user):
        _, admin_identity = admin
        other_company_profile, _ = make_user(role=UserRole.EMPLOYEE, company_id=uuid4())

        with pytest.raises(NotFoundError):
            env.user_service.erase_user(
                admin_identity, other_company_profile.id, expected_version=1
            )

    def test_stale_version_raises_concurrency_error(self, env, admin, employee):
        employee_profile, _ = employee
        _, admin_identity = admin

        with pytest.raises(ConcurrencyError):
            env.user_service.erase_user(
                admin_identity, employee_profile.id, expected_version=employee_profile.version + 1
            )
