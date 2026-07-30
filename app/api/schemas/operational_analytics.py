"""HTTP-only schemas for the ``/analytics/operational/*`` resources
(Milestone 12).

``app.analytics.operational_dto`` (``SLAMetrics``, ``PendingApprovalAge``,
``ApprovalDelayReport``, ``DurationBucket``, ``BottleneckReport``,
``CountBucket``, ``RejectionBucket``, ``WorkloadReport``, ``TrendReport``,
``ExecutiveKPIs``, ``DepartmentAnalytics``) are all plain frozen
``@dataclass``es, not Pydantic models — exactly like ``app.analytics.dto``.
The wrappers below give them a JSON-serializable shape via
``Model.model_validate(dataclass_instance)`` (``from_attributes=True``),
never re-deriving a field. ``UserMetricsOut``/``TimeSeriesOut`` are reused
directly from ``app.api.schemas.analytics`` rather than redefined, since
``BottleneckReport.approver_queue_depth``/``WorkloadReport
.approvals_per_approver`` and every trend field are already exactly that
shape.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ConfigDict

from app.api.schemas.analytics import TimeSeriesOut, UserMetricsOut
from app.models.base import EAHBaseModel, RequestTitle, UTCDatetime
from app.models.enums import UserRole

__all__ = [
    "PendingApprovalAgeOut",
    "SLAMetricsOut",
    "DurationBucketOut",
    "ApprovalDelayReportOut",
    "CountBucketOut",
    "RejectionBucketOut",
    "BottleneckReportOut",
    "WorkloadReportOut",
    "TrendReportOut",
    "ExecutiveKPIsOut",
    "DepartmentAnalyticsOut",
]


class PendingApprovalAgeOut(EAHBaseModel):
    """Wraps ``app.analytics.operational_dto.PendingApprovalAge``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    stage_id: UUID
    request_id: UUID
    request_title: RequestTitle
    request_type: str
    department: str | None
    stage_name: str
    stage_order: int
    assigned_to: UUID | None
    assigned_role: UserRole | None
    created_at: UTCDatetime
    age_hours: float
    sla_hours: float | None
    is_overdue: bool


class SLAMetricsOut(EAHBaseModel):
    """Wraps ``app.analytics.operational_dto.SLAMetrics``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    sla_hours_override: float | None
    pending_stage_count: int
    overdue_stage_count: int
    overdue_request_count: int
    average_current_stage_age_hours: float | None
    decided_stage_count: int
    sla_breaches_decided: int
    sla_compliance_percentage: float | None
    average_total_workflow_duration_seconds: float | None
    average_approval_duration_seconds: float | None


class DurationBucketOut(EAHBaseModel):
    """Wraps ``app.analytics.operational_dto.DurationBucket``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    key: str
    average_seconds: float | None
    count: int


class ApprovalDelayReportOut(EAHBaseModel):
    """Wraps ``app.analytics.operational_dto.ApprovalDelayReport``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    longest_pending: list[PendingApprovalAgeOut]
    oldest_pending_requests: list[PendingApprovalAgeOut]
    average_approval_seconds: float | None
    median_approval_seconds: float | None
    duration_by_stage: list[DurationBucketOut]
    duration_by_department: list[DurationBucketOut]
    duration_by_workflow: list[DurationBucketOut]


class CountBucketOut(EAHBaseModel):
    """Wraps ``app.analytics.operational_dto.CountBucket``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    key: str
    count: int


class RejectionBucketOut(EAHBaseModel):
    """Wraps ``app.analytics.operational_dto.RejectionBucket``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    key: str
    decided_count: int
    rejected_count: int
    rejection_rate: float | None


class BottleneckReportOut(EAHBaseModel):
    """Wraps ``app.analytics.operational_dto.BottleneckReport``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    slowest_stages: list[DurationBucketOut]
    slowest_workflows: list[DurationBucketOut]
    departments_causing_delay: list[DurationBucketOut]
    approver_queue_depth: list[UserMetricsOut]
    frequently_overdue_stages: list[CountBucketOut]
    rejection_hotspots: list[RejectionBucketOut]


class WorkloadReportOut(EAHBaseModel):
    """Wraps ``app.analytics.operational_dto.WorkloadReport``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    approvals_per_approver: list[UserMetricsOut]
    requests_per_department: dict[str, int]
    requests_per_workflow: dict[str, int]
    completed_today: int
    completed_this_week: int
    completed_this_month: int
    active_workload: int
    completed_workload: int
    pending_workload: int


class TrendReportOut(EAHBaseModel):
    """Wraps ``app.analytics.operational_dto.TrendReport``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    request_volume: TimeSeriesOut
    completion_trend: TimeSeriesOut
    approval_trend: TimeSeriesOut
    rejection_trend: TimeSeriesOut
    average_completion_time_trend: TimeSeriesOut


class ExecutiveKPIsOut(EAHBaseModel):
    """Wraps ``app.analytics.operational_dto.ExecutiveKPIs``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    average_approval_seconds: float | None
    average_workflow_completion_seconds: float | None
    sla_compliance_percentage: float | None
    active_requests: int
    completed_requests: int
    pending_approvals: int
    overdue_approvals: int
    rejection_rate: float | None
    throughput_per_day: float | None
    workflow_efficiency_score: float | None


class DepartmentAnalyticsOut(EAHBaseModel):
    """Wraps ``app.analytics.operational_dto.DepartmentAnalytics``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    department: str
    throughput_per_day: float | None
    sla_compliance_percentage: float | None
    average_approval_seconds: float | None
    active_workload: int
    backlog_count: int
