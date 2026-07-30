"""HTTP schemas for the admin Users/Roles/Departments/Settings/Dashboard
modules.

``ProfileRecord`` (``app.database.repositories.user_repository``) is a
plain persistence-level dataclass, not a Pydantic model — ``UserOut``
below is a thin ``from_attributes=True`` wrapper around it, the same
"reuse, don't re-derive" technique this API layer uses everywhere a
lower-layer object needs a stable, ``extra="forbid"`` HTTP-facing shape.

Departments, Roles & Permissions, Platform Settings, and the Dashboard
have no single backing model at all (they are compositions — see each
router's own docstring) — their ``Out`` shapes below are plain
``EAHBaseModel``s describing the composed response shape directly.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ConfigDict, Field

from app.models.base import EAHBaseModel, UTCDatetime
from app.models.enums import UserRole

__all__ = [
    "UserOut",
    "UserPatchBody",
    "RolePermissionsOut",
    "DepartmentMemberCountsOut",
    "DepartmentSummaryOut",
    "DepartmentWorkloadOut",
    "PlatformSettingsOut",
]


class UserOut(EAHBaseModel):
    """Wraps ``app.database.repositories.user_repository.ProfileRecord``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    id: UUID
    full_name: str
    role: UserRole
    department: str | None
    version: int
    created_at: UTCDatetime
    updated_at: UTCDatetime
    is_active: bool
    deleted_at: UTCDatetime | None
    deleted_by: UUID | None


class UserPatchBody(EAHBaseModel):
    """Body for ``PATCH /admin/users/{id}``. Mirrors
    ``UserService.update_profile``'s real kwargs. ``full_name`` is
    intentionally omitted: Phase 7's admin surface only covers role and
    department assignment, per the spec's own scope — a user's display
    name remains theirs to change, via ``UPDATE_OWN_PROFILE``, not an
    admin action. ``is_active`` was added for the profile-lifecycle
    feature (deactivation/reactivation) — see ``UserService.
    update_profile``'s own docstring; erasure is a separate, irreversible
    operation (``DELETE /admin/users/{id}``), not exposed here."""

    expected_version: int = Field(ge=1)
    role: UserRole | None = None
    department: str | None = None
    is_active: bool | None = None


class RolePermissionsOut(EAHBaseModel):
    """One row of the read-only Roles & Permissions matrix. Wraps a
    single ``app.auth.permissions.ROLE_PERMISSIONS`` entry."""

    role: UserRole
    permissions: list[str]


class DepartmentMemberCountsOut(EAHBaseModel):
    """Per-role member counts within one composed department bucket."""

    employee: int
    approver: int
    admin: int


class DepartmentSummaryOut(EAHBaseModel):
    """One row of the composed department list. See
    ``app.api.routers.admin_shared.fetch_all_profiles``/
    ``group_profiles_by_department`` for how this is computed — a
    composition over ``ProfileRepository.list_by_role``, not a query
    against a formal ``Department`` entity (none exists)."""

    department: str
    member_count: int
    roles: DepartmentMemberCountsOut


class DepartmentWorkloadOut(EAHBaseModel):
    """One department's member list plus its request-volume workload.

    ``workload`` is sourced from
    ``AnalyticsProvider.get_department_metrics`` — the same call
    ``DepartmentComparePanel`` already uses via the analytics router —
    not a new aggregation.
    """

    department: str
    member_count: int
    workload: int
    members: list[UserOut]


class PlatformSettingsOut(EAHBaseModel):
    """A read-only, non-secret projection of
    ``app.config.settings.AppSettings``. Deliberately excludes
    ``smtp.host``/``username``/``password``/``from_address``, the raw
    ``database_url``, and the Supabase connection settings — only
    ``smtp_enabled`` (a boolean) is exposed for the SMTP subsystem."""

    environment: str
    default_escalation_hours: float
    read_per_minute: int
    write_per_minute: int
    upload_per_minute: int
    login_per_5_minutes: int
    notification_poll_per_minute: int
    log_level: str
    smtp_enabled: bool
