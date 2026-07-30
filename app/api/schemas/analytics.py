"""HTTP-only schemas for the ``analytics`` resource and the org-wide
audit-log feed.

``app.analytics.dto`` (``TimeSeries``, ``TrendPoint``, ``ApprovalMetrics``,
``DashboardMetrics``, ``WorkflowMetrics``, ``DepartmentMetrics``,
``UserMetrics``, ``AnalyticsSummary``) are all plain frozen
``@dataclass``es, not Pydantic models — exactly like Phase 2's
``WorkflowStageDetail``/``WorkflowProgress``. The wrappers below give them
a JSON-serializable shape via ``Model.model_validate(dataclass_instance)``
(``from_attributes=True``), never re-deriving a field. Two of
``app.analytics.dto``'s own fields (``ApprovalMetrics.throughput``,
``DashboardMetrics.status_breakdown``) are themselves already
``app.models.ApprovalThroughput``/``StatusBreakdown`` Pydantic models —
reused directly, not re-wrapped, per that module's own "do not duplicate"
docstring.

``AgingRequestItemOut`` and ``AuditLogEntryOut`` are genuinely new
composition schemas: the first merges a raw ``WorkflowStageRecord`` (from
``ApprovalRepository.list_overdue_stages``, called directly per this
router's documented scoped exception) with its owning ``Request``; the
second merges a raw ``AuditLogRecord`` (from ``AuditRepository.list_all``,
same exception) with its actor's resolved display name.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ConfigDict, Field

from app.analytics.dto import TimeGranularity
from app.models import ApprovalThroughput, StatusBreakdown
from app.models.base import EAHBaseModel, RequestTitle, UTCDatetime
from app.models.enums import AuditAction, RequestStatus, StageStatus, UserRole

__all__ = [
    "TrendPointOut",
    "TimeSeriesOut",
    "ApprovalMetricsOut",
    "DashboardMetricsOut",
    "WorkflowMetricsOut",
    "DepartmentMetricsOut",
    "UserMetricsOut",
    "AnalyticsSummaryOut",
    "AgingRequestItemOut",
    "AuditLogEntryOut",
]


class TrendPointOut(EAHBaseModel):
    """Wraps ``app.analytics.dto.TrendPoint``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    label: str
    period_start: UTCDatetime
    period_end: UTCDatetime
    value: float


class TimeSeriesOut(EAHBaseModel):
    """Wraps ``app.analytics.dto.TimeSeries`` (``total`` is that dataclass's
    own computed property, read via ``from_attributes`` like any other
    attribute)."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    granularity: TimeGranularity
    points: list[TrendPointOut]
    total: float


class ApprovalMetricsOut(EAHBaseModel):
    """Wraps ``app.analytics.dto.ApprovalMetrics``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    throughput: ApprovalThroughput
    average_stage_duration_seconds: float | None
    approval_latency_seconds: float | None
    escalation_count: int | None
    reminder_count: int | None


class DashboardMetricsOut(EAHBaseModel):
    """Wraps ``app.analytics.dto.DashboardMetrics``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    status_breakdown: StatusBreakdown
    total_requests: int
    active_requests: int
    completed_requests: int
    rejected_requests: int
    approval_metrics: ApprovalMetricsOut


class WorkflowMetricsOut(EAHBaseModel):
    """Wraps ``app.analytics.dto.WorkflowMetrics``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    request_type: str
    status_breakdown: StatusBreakdown
    approval_metrics: ApprovalMetricsOut
    throughput_per_day: float | None


class DepartmentMetricsOut(EAHBaseModel):
    """Wraps ``app.analytics.dto.DepartmentMetrics``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    department: str
    status_breakdown: StatusBreakdown
    approval_metrics: ApprovalMetricsOut
    workload: int


class UserMetricsOut(EAHBaseModel):
    """Wraps ``app.analytics.dto.UserMetrics`` (``decisions_made`` is that
    dataclass's own computed property)."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    user_id: UUID
    full_name: str
    role: UserRole
    decisions_approved: int
    decisions_rejected: int
    pending_assigned_count: int
    average_decision_seconds: float | None
    decisions_made: int


class AnalyticsSummaryOut(EAHBaseModel):
    """Wraps ``app.analytics.dto.AnalyticsSummary``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    title: str
    generated_at: UTCDatetime
    dashboard: DashboardMetricsOut | None
    workflow_metrics: list[WorkflowMetricsOut]
    department_metrics: list[DepartmentMetricsOut]
    user_metrics: list[UserMetricsOut]
    trend: TimeSeriesOut | None
    narrative: str


class AgingRequestItemOut(EAHBaseModel):
    """One row of the Aging Requests / Bottlenecks view: an overdue
    pending ``WorkflowStage`` merged with its owning ``Request``'s
    summary fields (the same composition shape as Phase 3's
    ``ApprovalInboxItemOut``, plus a computed ``age_hours``).

    Attributes:
        age_hours: Hours elapsed since this stage began waiting for a
            decision, computed in the router at request time (pure
            presentation arithmetic on an already-fetched timestamp, not
            a new aggregation).
    """

    stage_id: UUID
    stage_version: int = Field(ge=1)
    stage_order: int = Field(gt=0)
    stage_name: str
    stage_status: StageStatus
    assigned_role: UserRole | None
    stage_created_at: UTCDatetime
    age_hours: float
    request_id: UUID
    request_title: RequestTitle
    request_type: str
    department: str | None
    requester_id: UUID
    request_status: RequestStatus


class AuditLogEntryOut(EAHBaseModel):
    """One row of the organization-wide Recent Activity feed: a raw
    ``AuditLogRecord`` merged with its actor's resolved display name.

    Attributes:
        actor_name: The acting user's display name, or ``None`` for a
            system-initiated action (``actor_id`` is ``None``) or if the
            profile could no longer be resolved.
    """

    id: UUID
    actor_id: UUID | None
    actor_name: str | None
    request_id: UUID | None
    action: AuditAction
    metadata: dict[str, object] | None
    created_at: UTCDatetime
