"""Unit tests for ``app.services.feature_flag_service.FeatureFlagService``."""

from __future__ import annotations

import pytest

from app.models.enums import AuditAction
from app.services.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from app.services.feature_flag_service import FeatureFlagService
from tests.fixtures.fakes import FakeAuditRepository, FakeFeatureFlagRepository

pytestmark = pytest.mark.unit


def _service() -> tuple[FeatureFlagService, FakeAuditRepository]:
    audit_repo = FakeAuditRepository()
    service = FeatureFlagService(feature_flag_repo=FakeFeatureFlagRepository(), audit_repo=audit_repo)
    return service, audit_repo


class TestPlatformAdminGate:
    def test_every_method_rejects_a_non_platform_admin(self, employee):
        service, _ = _service()
        _, identity = employee

        with pytest.raises(PermissionDeniedError):
            service.create_flag(identity, key="new_ui", description="New UI")
        with pytest.raises(PermissionDeniedError):
            service.list_flags(identity)
        with pytest.raises(PermissionDeniedError):
            service.update_flag(identity, "new_ui", enabled=True)


class TestCreateListUpdate:
    def test_create_flag_defaults_to_disabled_and_is_audited(self, platform_admin):
        service, audit_repo = _service()
        _, identity = platform_admin

        flag = service.create_flag(identity, key="new_dashboard", description="New dashboard layout")

        assert flag.enabled is False
        assert flag.description == "New dashboard layout"
        entries = audit_repo.list_platform_wide().items
        assert any(e.action == AuditAction.FEATURE_FLAG_UPDATED.value for e in entries)

    def test_create_flag_with_duplicate_key_raises(self, platform_admin):
        service, _ = _service()
        _, identity = platform_admin
        service.create_flag(identity, key="new_ui", description="New UI")

        with pytest.raises(ValidationError):
            service.create_flag(identity, key="new_ui", description="Duplicate")

    def test_list_flags_returns_every_flag_alphabetically(self, platform_admin):
        service, _ = _service()
        _, identity = platform_admin
        service.create_flag(identity, key="zeta_flag", description="Z")
        service.create_flag(identity, key="alpha_flag", description="A")

        flags = service.list_flags(identity)

        assert [f.key for f in flags] == ["alpha_flag", "zeta_flag"]

    def test_update_flag_toggles_enabled_state(self, platform_admin):
        service, audit_repo = _service()
        _, identity = platform_admin
        service.create_flag(identity, key="new_ui", description="New UI", enabled=False)

        updated = service.update_flag(identity, "new_ui", enabled=True)

        assert updated.enabled is True
        entries = audit_repo.list_platform_wide().items
        assert sum(1 for e in entries if e.action == AuditAction.FEATURE_FLAG_UPDATED.value) == 2

    def test_updating_an_unknown_flag_raises_not_found(self, platform_admin):
        service, _ = _service()
        _, identity = platform_admin

        with pytest.raises(NotFoundError):
            service.update_flag(identity, "does_not_exist", enabled=True)
