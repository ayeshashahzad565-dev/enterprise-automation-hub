"""Routes for the ``platform`` resource: company management.

Every handler is a thin wrapper over ``CompanyService``'s existing
methods. Gated by ``authorize_platform_admin`` (enforced inside the
service, not duplicated here, matching every other service-backed
router's convention) — deliberately orthogonal to every other admin-only
router in this codebase, which gates on ``UserRole.ADMIN`` instead. See
``app.auth.authorization.authorize_platform_admin``'s docstring for why
these are two distinct capabilities.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.analytics.aggregations import build_time_series
from app.analytics.dto import TimeGranularity
from app.api.dependencies import (
    get_company_service,
    get_current_identity,
    get_feature_flag_service,
    get_resources,
)
from app.api.routers.health import build_readiness_body
from app.api.schemas.platform import (
    CompanyLicenseOut,
    CompanyOut,
    CreateCompanyBody,
    FeatureFlagCreateBody,
    FeatureFlagOut,
    PlatformAuditEntryOut,
    PlatformStatsOut,
    RestoreCompanyBody,
    UpdateCompanyBody,
)
from app.auth.authentication import AuthenticatedIdentity
from app.auth.authorization import authorize_platform_admin
from app.bootstrap import ApplicationResources
from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database.repositories.base_repository import Page
from app.models.company_license import CompanyLicenseUpdate
from app.models.feature_flag import FeatureFlagUpdate
from app.models.platform_stats import PlatformStats
from app.services.company_service import CompanyService
from app.services.feature_flag_service import FeatureFlagService
from app.utils.datetime_utils import utc_now
from app.utils.pagination import build_pagination_metadata
from app.utils.response import build_list_response, build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(prefix="/platform", tags=["platform"])

#: How many days of request-creation history the request-volume trend
#: (`GET /platform/stats`) covers.
_STATS_TREND_WINDOW_DAYS = 30


def _request_id_of(request: Request) -> str | None:
    """Read the correlation id ``RequestIDMiddleware`` attached to this request."""
    return getattr(request.state, "request_id", None)


@router.post("/companies", status_code=201)
def create_company(
    request: Request,
    body: CreateCompanyBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: CompanyService = Depends(get_company_service),
) -> dict[str, Any]:
    """Create a new company. Platform-admin only. See
    ``CompanyService.create_company``."""
    created = service.create_company(identity, name=body.name)
    out = CompanyOut.model_validate(created)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/companies")
def list_companies(
    request: Request,
    include_deleted: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: CompanyService = Depends(get_company_service),
) -> dict[str, Any]:
    """List every company on the platform. Platform-admin only. See
    ``CompanyService.list_companies``."""
    result = service.list_companies(
        identity, include_deleted=include_deleted, page=Page(number=page, size=page_size)
    )
    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    out = [serialize(CompanyOut.model_validate(item)) for item in result.items]
    return build_list_response(out, pagination=pagination, request_id=_request_id_of(request))


@router.get("/companies/{company_id}")
def get_company(
    request: Request,
    company_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: CompanyService = Depends(get_company_service),
) -> dict[str, Any]:
    """Fetch a single company's detail. Platform-admin only. See
    ``CompanyService.get_company``."""
    company = service.get_company(identity, company_id)
    out = CompanyOut.model_validate(company)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.patch("/companies/{company_id}")
def update_company(
    request: Request,
    company_id: UUID,
    body: UpdateCompanyBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: CompanyService = Depends(get_company_service),
) -> dict[str, Any]:
    """Update a company's name, active status, and/or settings.
    Platform-admin only. See ``CompanyService.update_company``."""
    updated = service.update_company(
        identity,
        company_id,
        expected_version=body.expected_version,
        name=body.name,
        is_active=body.is_active,
        contact_email=body.contact_email,
        notes=body.notes,
    )
    out = CompanyOut.model_validate(updated)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.delete("/companies/{company_id}", status_code=200)
def delete_company(
    request: Request,
    company_id: UUID,
    expected_version: int = Query(..., ge=1),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: CompanyService = Depends(get_company_service),
) -> dict[str, Any]:
    """Soft-delete a company. Platform-admin only. See
    ``CompanyService.soft_delete_company``."""
    deleted = service.soft_delete_company(identity, company_id, expected_version=expected_version)
    out = CompanyOut.model_validate(deleted)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.post("/companies/{company_id}/restore")
def restore_company(
    request: Request,
    company_id: UUID,
    body: RestoreCompanyBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: CompanyService = Depends(get_company_service),
) -> dict[str, Any]:
    """Reverse a company's soft-deletion. Platform-admin only. See
    ``CompanyService.restore_company``."""
    restored = service.restore_company(identity, company_id, expected_version=body.expected_version)
    out = CompanyOut.model_validate(restored)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/companies/{company_id}/license")
def get_company_license(
    request: Request,
    company_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: CompanyService = Depends(get_company_service),
) -> dict[str, Any]:
    """Fetch a company's license, if configured. Platform-admin only. See
    ``CompanyService.get_license``."""
    license_ = service.get_license(identity, company_id)
    out = CompanyLicenseOut.model_validate(license_) if license_ is not None else None
    return build_success_response(
        serialize(out) if out is not None else None, request_id=_request_id_of(request)
    )


@router.patch("/companies/{company_id}/license")
def update_company_license(
    request: Request,
    company_id: UUID,
    body: CompanyLicenseUpdate,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: CompanyService = Depends(get_company_service),
) -> dict[str, Any]:
    """Set or update a company's license. Platform-admin only. See
    ``CompanyService.update_license``."""
    updated = service.update_license(
        identity,
        company_id,
        plan_tier=body.plan_tier,
        seat_limit=body.seat_limit,
        expires_at=body.expires_at,
        notes=body.notes,
    )
    out = CompanyLicenseOut.model_validate(updated)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/feature-flags")
def list_feature_flags(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: FeatureFlagService = Depends(get_feature_flag_service),
) -> dict[str, Any]:
    """List every feature flag. Platform-admin only. See
    ``FeatureFlagService.list_flags``."""
    flags = service.list_flags(identity)
    out = [serialize(FeatureFlagOut.model_validate(f)) for f in flags]
    return build_success_response(out, request_id=_request_id_of(request))


@router.post("/feature-flags", status_code=201)
def create_feature_flag(
    request: Request,
    body: FeatureFlagCreateBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: FeatureFlagService = Depends(get_feature_flag_service),
) -> dict[str, Any]:
    """Define a new feature flag. Platform-admin only. See
    ``FeatureFlagService.create_flag``."""
    created = service.create_flag(
        identity, key=body.key, description=body.description, enabled=body.enabled
    )
    out = FeatureFlagOut.model_validate(created)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.patch("/feature-flags/{key}")
def update_feature_flag(
    request: Request,
    key: str,
    body: FeatureFlagUpdate,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: FeatureFlagService = Depends(get_feature_flag_service),
) -> dict[str, Any]:
    """Update a feature flag. Platform-admin only. See
    ``FeatureFlagService.update_flag``."""
    updated = service.update_flag(
        identity, key, description=body.description, enabled=body.enabled
    )
    out = FeatureFlagOut.model_validate(updated)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/stats")
def get_platform_stats(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """Platform-wide statistics: tenants, users, storage, workflow usage,
    request volume. Platform-admin only.

    No Application Service backs this endpoint — pure, read-only
    composition of ``PlatformStatsRepository`` (which itself enforces no
    scoping, matching ``CompanyRepository``'s own precedent), gated
    inline, mirroring ``admin_jobs.py``'s identical "no service layer for
    pure composition" shape.
    """
    authorize_platform_admin(identity)

    stats_repo = resources.platform_stats_repo
    window_start = utc_now() - timedelta(days=_STATS_TREND_WINDOW_DAYS)
    timestamps = stats_repo.request_created_timestamps(created_after=window_start)
    trend = build_time_series(timestamps, TimeGranularity.DAY)

    stats = PlatformStats(
        total_tenants=resources.company_repo.count_companies(include_deleted=False),
        active_tenants=resources.company_repo.count_companies(is_active=True),
        total_users=stats_repo.count_users(),
        total_requests=stats_repo.count_requests(),
        request_volume_trend=list(trend.points),
        active_workflow_definitions=stats_repo.count_active_workflow_definitions(),
        total_storage_bytes=stats_repo.sum_attachment_storage_bytes(),
    )
    out = PlatformStatsOut.model_validate(stats)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/health")
def get_platform_health(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """Consolidated platform health: DB/Redis/scheduler/job-queue
    reachability plus dead-letter backlog. Platform-admin only.

    Reuses ``app.api.routers.health.build_readiness_body`` rather than
    re-implementing any reachability check.
    """
    authorize_platform_admin(identity)

    body, _status_code = build_readiness_body(resources.database_client, resources)
    if resources.job_repository is not None:
        body["dead_letter_by_queue"] = resources.job_repository.count_dead_letter_by_queue()
    return build_success_response(body, request_id=_request_id_of(request))


@router.get("/audit-log")
def list_platform_audit_log(
    request: Request,
    company_id: UUID | None = Query(None),
    actor_id: UUID | None = Query(None),
    action: str | None = Query(None),
    created_after: str | None = Query(None),
    created_before: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """Platform-wide audit history — also the data source for the
    platform dashboard's activity timeline (same endpoint, no
    ``company_id``/date filters, sliced to the first page client-side).
    Platform-admin only. See ``AuditRepository.list_platform_wide``."""
    authorize_platform_admin(identity)

    result = resources.audit_repo.list_platform_wide(
        company_id=company_id,
        actor_id=actor_id,
        action=action,
        created_after=datetime.fromisoformat(created_after) if created_after else None,
        created_before=datetime.fromisoformat(created_before) if created_before else None,
        page=Page(number=page, size=page_size),
    )
    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    out = [serialize(PlatformAuditEntryOut.model_validate(item)) for item in result.items]
    return build_list_response(out, pagination=pagination, request_id=_request_id_of(request))
