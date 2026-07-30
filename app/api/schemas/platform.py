"""HTTP schemas for the ``platform`` (company management) resource.

``app.models.company.Company`` is already a Pydantic model — ``CompanyOut``
below is a thin ``from_attributes=True`` wrapper around it, the same
"reuse, don't re-derive" technique used throughout this API layer.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field

from app.models.base import EAHBaseModel, UTCDatetime
from app.models.enums import AuditAction

__all__ = [
    "CompanyOut",
    "CreateCompanyBody",
    "UpdateCompanyBody",
    "RestoreCompanyBody",
    "CompanyLicenseOut",
    "FeatureFlagOut",
    "FeatureFlagCreateBody",
    "TrendPointOut",
    "PlatformStatsOut",
    "PlatformAuditEntryOut",
]


class CompanyOut(EAHBaseModel):
    """Wraps ``app.models.company.Company``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    id: UUID
    name: str
    slug: str
    is_active: bool
    contact_email: str | None
    notes: str | None
    version: int
    created_at: UTCDatetime
    updated_at: UTCDatetime
    deleted_at: UTCDatetime | None
    deleted_by: UUID | None
    is_deleted: bool


class CreateCompanyBody(EAHBaseModel):
    """Body for ``POST /platform/companies``."""

    name: str = Field(min_length=1, max_length=200)


class UpdateCompanyBody(EAHBaseModel):
    """Body for ``PATCH /platform/companies/{id}``."""

    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    contact_email: str | None = None
    notes: str | None = None


class RestoreCompanyBody(EAHBaseModel):
    """Body for ``POST /platform/companies/{id}/restore``."""

    expected_version: int = Field(ge=1)


class CompanyLicenseOut(EAHBaseModel):
    """Wraps ``app.models.company_license.CompanyLicense``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    company_id: UUID
    plan_tier: str
    seat_limit: int | None
    expires_at: UTCDatetime | None
    notes: str | None
    seats_used: int
    is_expired: bool
    updated_at: UTCDatetime


class FeatureFlagOut(EAHBaseModel):
    """Wraps ``app.models.feature_flag.FeatureFlag``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    key: str
    description: str
    enabled: bool
    updated_at: UTCDatetime


class FeatureFlagCreateBody(EAHBaseModel):
    """Body for ``POST /platform/feature-flags``."""

    key: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    enabled: bool = False


class TrendPointOut(EAHBaseModel):
    """Wraps ``app.analytics.dto.TrendPoint``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    label: str
    period_start: UTCDatetime
    period_end: UTCDatetime
    value: float


class PlatformStatsOut(EAHBaseModel):
    """Wraps ``app.models.platform_stats.PlatformStats``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    total_tenants: int
    active_tenants: int
    total_users: int
    total_requests: int
    request_volume_trend: list[TrendPointOut]
    active_workflow_definitions: int
    total_storage_bytes: int


class PlatformAuditEntryOut(EAHBaseModel):
    """Wraps ``app.database.repositories.audit_repository.AuditLogRecord``
    for the platform-wide audit history/activity timeline — distinct from
    ``app.api.schemas.audit.AuditEntryOut`` (which wraps a per-request,
    actor-name-resolved read model instead), since this view is
    cross-tenant and shows the raw ``company_id``/``actor_id`` rather
    than a resolved name (the frontend already holds the company list
    client-side and can join locally).
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    id: UUID
    actor_id: UUID | None
    company_id: UUID | None
    request_id: UUID | None
    action: AuditAction
    metadata: dict[str, Any] | None
    created_at: UTCDatetime
