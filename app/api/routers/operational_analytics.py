"""Routes for the Operational Analytics Layer (Milestone 12): SLA
tracking, approval-delay detection, bottleneck detection, workload
analytics, trend analytics, executive KPIs, and department analytics.

Every handler below is a thin wrapper over ``OperationalAnalyticsProvider``
(``app.analytics.operational_engine.OperationalAnalyticsEngine``, wired
via ``app.api.dependencies.get_operational_analytics_provider``), mirroring
``app.api.routers.analytics``'s own conventions exactly: the same
``_require_analytics_access`` (APPROVER/ADMIN) gate applied before every
call, the same ``company_id=identity.company_id`` — never client input —
threaded into every provider call, and the same
``build_success_response``/``serialize`` response envelope. No new
response shape, error code, or RBAC policy is introduced by this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.analytics.dto import TimeGranularity
from app.analytics.interfaces import OperationalAnalyticsProvider
from app.api.dependencies import get_current_identity, get_operational_analytics_provider
from app.api.schemas.operational_analytics import (
    ApprovalDelayReportOut,
    BottleneckReportOut,
    DepartmentAnalyticsOut,
    ExecutiveKPIsOut,
    SLAMetricsOut,
    TrendReportOut,
    WorkloadReportOut,
)
from app.auth import rbac
from app.auth.authentication import AuthenticatedIdentity
from app.models.enums import UserRole
from app.utils.response import build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["operational-analytics"])

#: Matches ``app.api.routers.analytics.get_aging_requests``'s existing
#: ranked-dataset page-size ceiling, applied here to every sortable
#: dataset this module's endpoints return.
_MAX_LIMIT = 100


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _require_analytics_access(identity: AuthenticatedIdentity) -> None:
    """Gate every endpoint in this module to APPROVER/ADMIN, mirroring
    ``app.api.routers.analytics``'s identical policy."""
    rbac.require_role(identity.role, UserRole.APPROVER, UserRole.ADMIN)


@router.get("/analytics/operational/sla")
def get_sla_metrics(
    request: Request,
    sla_hours: float | None = Query(None, gt=0),
    department: str | None = Query(None, max_length=200),
    request_type: str | None = Query(None, max_length=200),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: OperationalAnalyticsProvider = Depends(get_operational_analytics_provider),
) -> dict[str, Any]:
    """SLA compliance snapshot. See ``OperationalAnalyticsProvider.get_sla_metrics``."""
    _require_analytics_access(identity)
    result = provider.get_sla_metrics(
        company_id=identity.company_id,
        sla_hours_override=sla_hours,
        department=department,
        request_type=request_type,
        created_after=created_after,
        created_before=created_before,
    )
    out = SLAMetricsOut.model_validate(result)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/operational/approval-delays")
def get_approval_delays(
    request: Request,
    department: str | None = Query(None, max_length=200),
    request_type: str | None = Query(None, max_length=200),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    limit: int = Query(10, ge=1, le=_MAX_LIMIT),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: OperationalAnalyticsProvider = Depends(get_operational_analytics_provider),
) -> dict[str, Any]:
    """Approval-delay datasets. See ``OperationalAnalyticsProvider.get_approval_delays``."""
    _require_analytics_access(identity)
    result = provider.get_approval_delays(
        company_id=identity.company_id,
        department=department,
        request_type=request_type,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
    )
    out = ApprovalDelayReportOut.model_validate(result)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/operational/bottlenecks")
def get_bottlenecks(
    request: Request,
    department: str | None = Query(None, max_length=200),
    request_type: str | None = Query(None, max_length=200),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    limit: int = Query(10, ge=1, le=_MAX_LIMIT),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: OperationalAnalyticsProvider = Depends(get_operational_analytics_provider),
) -> dict[str, Any]:
    """Bottleneck-identification datasets. See ``OperationalAnalyticsProvider.get_bottlenecks``."""
    _require_analytics_access(identity)
    result = provider.get_bottlenecks(
        company_id=identity.company_id,
        department=department,
        request_type=request_type,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
    )
    out = BottleneckReportOut.model_validate(result)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/operational/workload")
def get_workload_report(
    request: Request,
    department: str | None = Query(None, max_length=200),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: OperationalAnalyticsProvider = Depends(get_operational_analytics_provider),
) -> dict[str, Any]:
    """Workload distribution. See ``OperationalAnalyticsProvider.get_workload_report``."""
    _require_analytics_access(identity)
    result = provider.get_workload_report(company_id=identity.company_id, department=department)
    out = WorkloadReportOut.model_validate(result)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/operational/trends")
def get_trends(
    request: Request,
    granularity: TimeGranularity = Query(TimeGranularity.DAY),
    department: str | None = Query(None, max_length=200),
    request_type: str | None = Query(None, max_length=200),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: OperationalAnalyticsProvider = Depends(get_operational_analytics_provider),
) -> dict[str, Any]:
    """Execution trends. See ``OperationalAnalyticsProvider.get_trends``."""
    _require_analytics_access(identity)
    result = provider.get_trends(
        company_id=identity.company_id,
        granularity=granularity,
        department=department,
        request_type=request_type,
        created_after=created_after,
        created_before=created_before,
    )
    out = TrendReportOut.model_validate(result)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/operational/executive")
def get_executive_kpis(
    request: Request,
    department: str | None = Query(None, max_length=200),
    request_type: str | None = Query(None, max_length=200),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: OperationalAnalyticsProvider = Depends(get_operational_analytics_provider),
) -> dict[str, Any]:
    """Single-screen executive KPI composite. See
    ``OperationalAnalyticsProvider.get_executive_kpis``."""
    _require_analytics_access(identity)
    result = provider.get_executive_kpis(
        company_id=identity.company_id,
        department=department,
        request_type=request_type,
        created_after=created_after,
        created_before=created_before,
    )
    out = ExecutiveKPIsOut.model_validate(result)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/operational/departments/{department}")
def get_department_analytics(
    request: Request,
    department: str,
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: OperationalAnalyticsProvider = Depends(get_operational_analytics_provider),
) -> dict[str, Any]:
    """Operational figures for one department. See
    ``OperationalAnalyticsProvider.get_department_analytics``."""
    _require_analytics_access(identity)
    result = provider.get_department_analytics(
        department,
        company_id=identity.company_id,
        created_after=created_after,
        created_before=created_before,
    )
    out = DepartmentAnalyticsOut.model_validate(result)
    return build_success_response(serialize(out), request_id=_request_id_of(request))
