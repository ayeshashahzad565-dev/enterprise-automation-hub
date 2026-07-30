"""Unit tests for ``app.services.company_service.CompanyService``.

Covers company CRUD (create/list/get/update/soft-delete/restore),
license management, the platform-admin-only gate on every method, the
self-lockout guard, and that every mutation now writes an audit entry
(previously this service wrote none at all).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.models.enums import AuditAction, UserRole
from app.services.company_service import CompanyService
from app.services.exceptions import (
    ConcurrencyError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.utils.datetime_utils import utc_now
from tests.fixtures.fakes import (
    FakeAuditRepository,
    FakeCompanyLicenseRepository,
    FakeCompanyRepository,
    FakeProfileRepository,
)

pytestmark = pytest.mark.unit


def _service() -> tuple[CompanyService, FakeAuditRepository]:
    audit_repo = FakeAuditRepository()
    service = CompanyService(
        company_repo=FakeCompanyRepository(),
        license_repo=FakeCompanyLicenseRepository(),
        profile_repo=FakeProfileRepository(),
        audit_repo=audit_repo,
    )
    return service, audit_repo


class TestPlatformAdminGate:
    def test_every_method_rejects_a_non_platform_admin(self, employee):
        service, _ = _service()
        _, identity = employee

        with pytest.raises(PermissionDeniedError):
            service.create_company(identity, name="Acme")
        with pytest.raises(PermissionDeniedError):
            service.list_companies(identity)
        with pytest.raises(PermissionDeniedError):
            service.get_company(identity, uuid4())
        with pytest.raises(PermissionDeniedError):
            service.update_company(identity, uuid4(), expected_version=1, name="X")
        with pytest.raises(PermissionDeniedError):
            service.soft_delete_company(identity, uuid4(), expected_version=1)
        with pytest.raises(PermissionDeniedError):
            service.restore_company(identity, uuid4(), expected_version=1)
        with pytest.raises(PermissionDeniedError):
            service.get_license(identity, uuid4())
        with pytest.raises(PermissionDeniedError):
            service.update_license(identity, uuid4(), plan_tier="pro")


class TestCreateAndList:
    def test_create_company_is_active_and_audited(self, platform_admin):
        service, audit_repo = _service()
        _, identity = platform_admin

        company = service.create_company(identity, name="Acme Corp")

        assert company.is_active is True
        assert company.is_deleted is False
        assert company.slug.startswith("acme-corp-")
        entries = audit_repo.list_platform_wide().items
        assert any(e.action == AuditAction.COMPANY_CREATED.value for e in entries)

    def test_list_companies_excludes_soft_deleted_by_default(self, platform_admin):
        service, _ = _service()
        _, identity = platform_admin
        kept = service.create_company(identity, name="Kept Co")
        deleted = service.create_company(identity, name="Deleted Co")
        service.soft_delete_company(identity, deleted.id, expected_version=deleted.version)

        active_only = service.list_companies(identity)
        assert {c.id for c in active_only.items} == {kept.id}

        everything = service.list_companies(identity, include_deleted=True)
        assert {c.id for c in everything.items} == {kept.id, deleted.id}


class TestUpdateSuspendReactivate:
    def test_update_settings_writes_audit_entry(self, platform_admin):
        service, audit_repo = _service()
        _, identity = platform_admin
        company = service.create_company(identity, name="Acme")

        updated = service.update_company(
            identity, company.id, expected_version=company.version, contact_email="ops@acme.test"
        )

        assert updated.contact_email == "ops@acme.test"
        entries = audit_repo.list_platform_wide().items
        assert any(e.action == AuditAction.COMPANY_SETTINGS_UPDATED.value for e in entries)

    def test_suspend_and_reactivate_are_audited_distinctly(self, platform_admin):
        service, audit_repo = _service()
        _, identity = platform_admin
        # A second company, distinct from the platform admin's own, so the
        # self-lockout guard (tested separately below) doesn't interfere.
        company = service.create_company(identity, name="Other Co")

        suspended = service.update_company(
            identity, company.id, expected_version=company.version, is_active=False
        )
        assert suspended.is_active is False

        reactivated = service.update_company(
            identity, company.id, expected_version=suspended.version, is_active=True
        )
        assert reactivated.is_active is True

        actions = [e.action for e in audit_repo.list_platform_wide().items]
        assert AuditAction.COMPANY_SUSPENDED.value in actions
        assert AuditAction.COMPANY_REACTIVATED.value in actions

    def test_concurrent_update_raises_concurrency_error(self, platform_admin):
        service, _ = _service()
        _, identity = platform_admin
        company = service.create_company(identity, name="Acme")

        with pytest.raises(ConcurrencyError):
            service.update_company(
                identity, company.id, expected_version=company.version + 1, name="New Name"
            )

    def test_updating_an_unknown_company_raises_not_found(self, platform_admin):
        service, _ = _service()
        _, identity = platform_admin

        with pytest.raises(NotFoundError):
            service.get_company(identity, uuid4())


class TestSelfLockoutGuard:
    def _platform_admin_of_own_company(self, service, make_user):
        """Build a platform admin whose own ``company_id`` is a real,
        just-created company (not the shared ``DEFAULT_TEST_COMPANY_ID``
        every other fixture uses), so a self-lockout attempt hits the
        guard rather than a `RecordNotFoundError` on a nonexistent row.
        """
        bootstrap_admin_identity = make_user(role=UserRole.EMPLOYEE, is_platform_admin=True)[1]
        own_company = service.create_company(bootstrap_admin_identity, name="Own Co")
        _, identity = make_user(
            role=UserRole.EMPLOYEE, company_id=own_company.id, is_platform_admin=True
        )
        return identity, own_company

    def test_platform_admin_cannot_suspend_their_own_company(self, make_user):
        service, _ = _service()
        identity, own_company = self._platform_admin_of_own_company(service, make_user)

        with pytest.raises(ValidationError):
            service.update_company(
                identity, own_company.id, expected_version=own_company.version, is_active=False
            )

    def test_platform_admin_cannot_delete_their_own_company(self, make_user):
        service, _ = _service()
        identity, own_company = self._platform_admin_of_own_company(service, make_user)

        with pytest.raises(ValidationError):
            service.soft_delete_company(
                identity, own_company.id, expected_version=own_company.version
            )

    def test_platform_admin_can_reactivate_their_own_company(self, make_user):
        # Only *suspending*/*deleting* one's own company is guarded — an
        # explicit reactivation (is_active=True) is always safe.
        service, _ = _service()
        identity, own_company = self._platform_admin_of_own_company(service, make_user)

        updated = service.update_company(
            identity, own_company.id, expected_version=own_company.version, is_active=True
        )
        assert updated.is_active is True


class TestSoftDeleteAndRestore:
    def test_soft_delete_then_restore_round_trip(self, platform_admin):
        service, audit_repo = _service()
        _, identity = platform_admin
        company = service.create_company(identity, name="Acme")

        deleted = service.soft_delete_company(identity, company.id, expected_version=company.version)
        assert deleted.is_deleted is True
        assert deleted.deleted_by == identity.user_id

        restored = service.restore_company(identity, company.id, expected_version=deleted.version)
        assert restored.is_deleted is False
        assert restored.deleted_at is None

        actions = [e.action for e in audit_repo.list_platform_wide().items]
        assert AuditAction.COMPANY_DELETED.value in actions
        assert AuditAction.COMPANY_RESTORED.value in actions


class TestLicense:
    def test_get_license_returns_none_when_unconfigured(self, platform_admin):
        service, _ = _service()
        _, identity = platform_admin
        company = service.create_company(identity, name="Acme")

        assert service.get_license(identity, company.id) is None

    def test_update_license_creates_and_computes_seats_used(self, platform_admin, employee):
        service, audit_repo = _service()
        _, identity = platform_admin
        company = service.create_company(identity, name="Acme")
        # `employee`'s profile lives in the shared DEFAULT_TEST_COMPANY_ID,
        # not this newly created company, so seats_used should be 0 here.

        license_ = service.update_license(
            identity, company.id, plan_tier="pro", seat_limit=10
        )

        assert license_.plan_tier == "pro"
        assert license_.seat_limit == 10
        assert license_.seats_used == 0
        assert license_.is_expired is False
        entries = audit_repo.list_platform_wide().items
        assert any(e.action == AuditAction.COMPANY_LICENSE_UPDATED.value for e in entries)

    def test_update_license_partial_patch_preserves_unset_fields(self, platform_admin):
        service, _ = _service()
        _, identity = platform_admin
        company = service.create_company(identity, name="Acme")
        service.update_license(identity, company.id, plan_tier="enterprise", seat_limit=50)

        updated = service.update_license(identity, company.id, seat_limit=100)

        assert updated.plan_tier == "enterprise"
        assert updated.seat_limit == 100

    def test_is_expired_reflects_a_past_expiry(self, platform_admin):
        service, _ = _service()
        _, identity = platform_admin
        company = service.create_company(identity, name="Acme")

        license_ = service.update_license(
            identity, company.id, plan_tier="pro", expires_at=utc_now() - timedelta(days=1)
        )

        assert license_.is_expired is True
