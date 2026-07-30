"""Routes for organization-wide analytics, executive/operational
reporting, and the audit-log ("Recent Activity") feed.

Every metrics/summary handler below is a thin wrapper over
``AnalyticsProvider``/``ReportingProvider`` (``app.analytics.analytics_engine
.AnalyticsEngine``/``app.analytics.reporting.ReportingEngine``, wired via
``app.api.dependencies.get_analytics_provider``/``get_reporting_provider``,
both already constructed in Phase 0's ``app.bootstrap``). **Neither engine
performs any identity/role check of its own** (confirmed by direct read of
``app/analytics/interfaces.py`` — no method takes an ``identity`` argument
at all; `app/pages/analytics.py`'s own docstring states this explicitly and
applies its own guard at the Streamlit layer) — every handler here calls
``rbac.require_role`` itself before touching either engine, mirroring the
exact pattern ``app.services.analytics_service.py``'s private
``_require_analytics_access`` already uses. ``require_role`` raises
``RoleNotPermittedError`` (a subclass of the already globally-registered
``AuthError``), so no local exception handling is needed here — it
propagates to ``app.api.exception_handlers``'s existing handler exactly
like ``get_current_identity``'s own auth failures do.

``get_aging_requests`` and ``list_recent_activity`` are a different,
narrower exception: **no Application Service exists for either** —
``ApprovalRepository.list_overdue_stages`` and ``AuditRepository.list_all``
are called directly (both already used internally elsewhere in this
codebase for the same kind of org-wide, unscoped read: the former by the
Scheduler's escalation job, the latter documented in ``docs/api_design.md``
as the intended backing for a `GET /api/v1/audit-logs` endpoint that was
never built at the service layer). Both are admin-only, enforced in this
router, since bypassing the Application Service Layer means no per-caller
visibility scoping exists either.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.analytics.dto import TimeGranularity
from app.analytics.interfaces import AnalyticsProvider, ReportingProvider
from app.api.dependencies import (
    get_analytics_provider,
    get_approval_repository,
    get_audit_repository,
    get_current_identity,
    get_profile_repository,
    get_reporting_provider,
    get_request_service,
)
from app.api.schemas.analytics import (
    AgingRequestItemOut,
    AnalyticsSummaryOut,
    ApprovalMetricsOut,
    AuditLogEntryOut,
    DashboardMetricsOut,
    DepartmentMetricsOut,
    TimeSeriesOut,
    UserMetricsOut,
    WorkflowMetricsOut,
)
from app.auth import rbac
from app.auth.authentication import AuthenticatedIdentity
from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database.exceptions import RecordNotFoundError
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page
from app.database.repositories.user_repository import ProfileRepository
from app.models.enums import AuditAction, UserRole
from app.services.request_service import RequestService
from app.utils.datetime_utils import utc_now
from app.utils.pagination import build_pagination_metadata
from app.utils.response import build_list_response, build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["analytics"])


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _require_analytics_access(identity: AuthenticatedIdentity) -> None:
    """Gate every metrics/summary endpoint to APPROVER/ADMIN, mirroring
    ``app.services.analytics_service.py``'s ``_ANALYTICS_ROLES`` policy."""
    rbac.require_role(identity.role, UserRole.APPROVER, UserRole.ADMIN)


def _require_self_or_admin(identity: AuthenticatedIdentity, user_id: UUID) -> None:
    """User-scoped endpoints: APPROVER/ADMIN base gate, then ADMIN unless
    the caller is asking about themselves."""
    _require_analytics_access(identity)
    if identity.role is not UserRole.ADMIN and identity.user_id != user_id:
        rbac.require_role(identity.role, UserRole.ADMIN)


def _require_admin_only(identity: AuthenticatedIdentity) -> None:
    rbac.require_role(identity.role, UserRole.ADMIN)


def _csv_response(rows: list[tuple[str, Any]], *, filename: str) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["metric", "value"])
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _approval_metrics_rows(approval_metrics: Any) -> list[tuple[str, Any]]:
    """The rows shared by every CSV export that includes an ``ApprovalMetrics``."""
    return [
        ("completion_rate", approval_metrics.throughput.completion_rate),
        ("average_decision_seconds", approval_metrics.approval_latency_seconds),
        ("escalation_count", approval_metrics.escalation_count),
    ]


def _status_breakdown_rows(status_breakdown: Any) -> list[tuple[str, Any]]:
    return [(f"status:{status.value}", count) for status, count in status_breakdown.counts.items()]


def _dashboard_metrics_rows(metrics: Any) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = [
        ("total_requests", metrics.total_requests),
        ("active_requests", metrics.active_requests),
        ("completed_requests", metrics.completed_requests),
        ("rejected_requests", metrics.rejected_requests),
    ]
    rows += _status_breakdown_rows(metrics.status_breakdown)
    rows += _approval_metrics_rows(metrics.approval_metrics)
    return rows


def _department_metrics_rows(metrics: Any) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = [
        ("department", metrics.department),
        ("workload", metrics.workload),
    ]
    rows += _status_breakdown_rows(metrics.status_breakdown)
    rows += _approval_metrics_rows(metrics.approval_metrics)
    return rows


@router.get("/analytics/dashboard", response_model=None)
def get_dashboard_metrics(
    request: Request,
    department: str | None = Query(None, max_length=200),
    request_type: str | None = Query(None, max_length=200),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    format: Literal["json", "csv"] = Query("json"),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: AnalyticsProvider = Depends(get_analytics_provider),
) -> Response | dict[str, Any]:
    """Organization-wide dashboard figures. See ``AnalyticsProvider.get_dashboard_metrics``."""
    _require_analytics_access(identity)
    metrics = provider.get_dashboard_metrics(
        company_id=identity.company_id,
        department=department,
        request_type=request_type,
        created_after=created_after,
        created_before=created_before,
    )
    if format == "csv":
        return _csv_response(_dashboard_metrics_rows(metrics), filename="dashboard-metrics.csv")
    out = DashboardMetricsOut.model_validate(metrics)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/approvals")
def get_approval_metrics(
    request: Request,
    request_type: str | None = Query(None, max_length=200),
    department: str | None = Query(None, max_length=200),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: AnalyticsProvider = Depends(get_analytics_provider),
) -> dict[str, Any]:
    """Approval throughput/SLA-adjacent figures. See ``AnalyticsProvider.get_approval_metrics``."""
    _require_analytics_access(identity)
    metrics = provider.get_approval_metrics(
        company_id=identity.company_id,
        request_type=request_type,
        department=department,
        created_after=created_after,
        created_before=created_before,
    )
    out = ApprovalMetricsOut.model_validate(metrics)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/workflow/{request_type}")
def get_workflow_metrics(
    request: Request,
    request_type: str,
    department: str | None = Query(None, max_length=200),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: AnalyticsProvider = Depends(get_analytics_provider),
) -> dict[str, Any]:
    """Metrics scoped to one request type. See ``AnalyticsProvider.get_workflow_metrics``."""
    _require_analytics_access(identity)
    metrics = provider.get_workflow_metrics(
        request_type,
        company_id=identity.company_id,
        department=department,
        created_after=created_after,
        created_before=created_before,
    )
    out = WorkflowMetricsOut.model_validate(metrics)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/departments/{department}", response_model=None)
def get_department_metrics(
    request: Request,
    department: str,
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    format: Literal["json", "csv"] = Query("json"),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: AnalyticsProvider = Depends(get_analytics_provider),
) -> Response | dict[str, Any]:
    """Metrics scoped to one department. See ``AnalyticsProvider.get_department_metrics``."""
    _require_analytics_access(identity)
    metrics = provider.get_department_metrics(
        department,
        company_id=identity.company_id,
        created_after=created_after,
        created_before=created_before,
    )
    if format == "csv":
        return _csv_response(
            _department_metrics_rows(metrics), filename=f"department-{department}-metrics.csv"
        )
    out = DepartmentMetricsOut.model_validate(metrics)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/users/{user_id}")
def get_user_metrics(
    request: Request,
    user_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: AnalyticsProvider = Depends(get_analytics_provider),
) -> dict[str, Any]:
    """Metrics scoped to one user. See ``AnalyticsProvider.get_user_metrics``."""
    _require_self_or_admin(identity, user_id)
    metrics = provider.get_user_metrics(user_id, company_id=identity.company_id)
    out = UserMetricsOut.model_validate(metrics)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/workload", response_model=None)
def get_workload_summary(
    request: Request,
    department: str | None = Query(None, max_length=200),
    format: Literal["json", "csv"] = Query("json"),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: AnalyticsProvider = Depends(get_analytics_provider),
) -> Response | dict[str, Any]:
    """Per-approver/admin workload. See ``AnalyticsProvider.get_workload_summary``."""
    _require_analytics_access(identity)
    users = provider.get_workload_summary(company_id=identity.company_id, department=department)
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "user_id",
                "full_name",
                "role",
                "decisions_approved",
                "decisions_rejected",
                "pending_assigned_count",
                "decisions_made",
            ]
        )
        for user in users:
            writer.writerow(
                [
                    str(user.user_id),
                    user.full_name,
                    user.role.value,
                    user.decisions_approved,
                    user.decisions_rejected,
                    user.pending_assigned_count,
                    user.decisions_made,
                ]
            )
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="workload-summary.csv"'},
        )
    out = [serialize(UserMetricsOut.model_validate(u)) for u in users]
    return build_success_response(out, request_id=_request_id_of(request))


@router.get("/analytics/trend", response_model=None)
def get_request_trend(
    request: Request,
    granularity: TimeGranularity = Query(TimeGranularity.DAY),
    department: str | None = Query(None, max_length=200),
    request_type: str | None = Query(None, max_length=200),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    format: Literal["json", "csv"] = Query("json"),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: AnalyticsProvider = Depends(get_analytics_provider),
) -> Response | dict[str, Any]:
    """Submission-volume time series. See ``AnalyticsProvider.get_request_trend``."""
    _require_analytics_access(identity)
    series = provider.get_request_trend(
        company_id=identity.company_id,
        granularity=granularity,
        department=department,
        request_type=request_type,
        created_after=created_after,
        created_before=created_before,
    )
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["label", "period_start", "period_end", "value"])
        for point in series.points:
            writer.writerow(
                [
                    point.label,
                    point.period_start.isoformat(),
                    point.period_end.isoformat(),
                    point.value,
                ]
            )
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="request-trend.csv"'},
        )
    out = TimeSeriesOut.model_validate(series)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/summary/executive")
def get_executive_summary(
    request: Request,
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    reporting_provider: ReportingProvider = Depends(get_reporting_provider),
) -> dict[str, Any]:
    """See ``ReportingProvider.build_executive_summary``."""
    _require_analytics_access(identity)
    summary = reporting_provider.build_executive_summary(
        company_id=identity.company_id, created_after=created_after, created_before=created_before
    )
    out = AnalyticsSummaryOut.model_validate(summary)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/summary/operational")
def get_operational_summary(
    request: Request,
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    reporting_provider: ReportingProvider = Depends(get_reporting_provider),
) -> dict[str, Any]:
    """See ``ReportingProvider.build_operational_summary``."""
    _require_analytics_access(identity)
    summary = reporting_provider.build_operational_summary(
        company_id=identity.company_id, created_after=created_after, created_before=created_before
    )
    out = AnalyticsSummaryOut.model_validate(summary)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/summary/workflow/{request_type}")
def get_workflow_summary(
    request: Request,
    request_type: str,
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    reporting_provider: ReportingProvider = Depends(get_reporting_provider),
) -> dict[str, Any]:
    """See ``ReportingProvider.build_workflow_summary``."""
    _require_analytics_access(identity)
    summary = reporting_provider.build_workflow_summary(
        request_type,
        company_id=identity.company_id,
        created_after=created_after,
        created_before=created_before,
    )
    out = AnalyticsSummaryOut.model_validate(summary)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/summary/department/{department}")
def get_department_summary(
    request: Request,
    department: str,
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    reporting_provider: ReportingProvider = Depends(get_reporting_provider),
) -> dict[str, Any]:
    """See ``ReportingProvider.build_department_summary``."""
    _require_analytics_access(identity)
    summary = reporting_provider.build_department_summary(
        department,
        company_id=identity.company_id,
        created_after=created_after,
        created_before=created_before,
    )
    out = AnalyticsSummaryOut.model_validate(summary)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/summary/user/{user_id}")
def get_user_summary(
    request: Request,
    user_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    reporting_provider: ReportingProvider = Depends(get_reporting_provider),
) -> dict[str, Any]:
    """See ``ReportingProvider.build_user_summary``."""
    _require_self_or_admin(identity, user_id)
    summary = reporting_provider.build_user_summary(user_id, company_id=identity.company_id)
    out = AnalyticsSummaryOut.model_validate(summary)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/analytics/aging-requests")
def get_aging_requests(
    request: Request,
    older_than_hours: float = Query(24.0, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    approval_repo: ApprovalRepository = Depends(get_approval_repository),
    request_service: RequestService = Depends(get_request_service),
) -> dict[str, Any]:
    """Pending stages older than ``older_than_hours``, enriched with their
    owning request's summary. Admin-only — see this module's docstring."""
    _require_admin_only(identity)
    threshold = utc_now() - timedelta(hours=older_than_hours)
    result = approval_repo.list_overdue_stages(
        created_before=threshold,
        company_id=identity.company_id,
        page=Page(number=page, size=page_size),
    )

    now = utc_now()
    requests_by_id: dict[UUID, Any] = {}
    items: list[AgingRequestItemOut] = []
    for stage in result.items:
        owning_request = requests_by_id.get(stage.request_id)
        if owning_request is None:
            owning_request = request_service.get_request(identity, stage.request_id)
            requests_by_id[stage.request_id] = owning_request
        items.append(
            AgingRequestItemOut(
                stage_id=stage.id,
                stage_version=stage.version,
                stage_order=stage.stage_order,
                stage_name=stage.stage_name,
                stage_status=stage.status,
                assigned_role=stage.assigned_role,
                stage_created_at=stage.created_at,
                age_hours=round((now - stage.created_at).total_seconds() / 3600, 1),
                request_id=owning_request.id,
                request_title=owning_request.title,
                request_type=owning_request.request_type,
                department=owning_request.department,
                requester_id=owning_request.requester_id,
                request_status=owning_request.status,
            )
        )

    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    return build_list_response(
        [serialize(item) for item in items],
        pagination=pagination,
        request_id=_request_id_of(request),
    )


@router.get("/audit-logs")
def list_recent_activity(
    request: Request,
    actor_id: UUID | None = Query(None),
    action: str | None = Query(None, max_length=100),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
) -> dict[str, Any]:
    """Organization-wide audit feed ("Recent Activity"). Admin-only — see
    this module's docstring. See ``AuditRepository.list_all``.

    ``actor_id`` backs the Activity Center's "Organization" tab's
    click-to-filter-by-user affordance (Phase 5) — no user-directory
    endpoint exists anywhere in this API, so the frontend captures a
    user's id from an already-displayed activity row rather than from a
    picker.
    """
    _require_admin_only(identity)
    result = audit_repo.list_all(
        company_id=identity.company_id,
        actor_id=actor_id,
        action=action,
        created_after=created_after,
        created_before=created_before,
        page=Page(number=page, size=page_size),
    )

    names_by_actor: dict[UUID, str | None] = {}
    items: list[AuditLogEntryOut] = []
    for entry in result.items:
        actor_name: str | None = None
        if entry.actor_id is not None:
            if entry.actor_id not in names_by_actor:
                try:
                    names_by_actor[entry.actor_id] = profile_repo.get_by_id(
                        entry.actor_id
                    ).full_name
                except RecordNotFoundError:
                    names_by_actor[entry.actor_id] = None
            actor_name = names_by_actor[entry.actor_id]
        items.append(
            AuditLogEntryOut(
                id=entry.id,
                actor_id=entry.actor_id,
                actor_name=actor_name,
                request_id=entry.request_id,
                action=AuditAction(entry.action),
                metadata=entry.metadata,
                created_at=entry.created_at,
            )
        )

    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    return build_list_response(
        [serialize(item) for item in items],
        pagination=pagination,
        request_id=_request_id_of(request),
    )
