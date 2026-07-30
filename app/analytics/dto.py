"""Immutable data transfer objects for the Analytics Layer.

Per this package's design brief, every result this layer produces is an
immutable, frozen dataclass. Two DTOs already exist in the Domain Layer
with an identical shape to what this package needs —
``app.models.StatusBreakdown`` and ``app.models.ApprovalThroughput`` —
and are reused directly here rather than redefined, per the "do not
duplicate" constraint on this package. Every other DTO below is new to
this package.

Several fields throughout this module are typed ``| None`` deliberately:
per this package's accuracy requirement, a metric that cannot be computed
correctly from the finalized Repository Layer without introducing an
N+1 query pattern or a sampled/bounded approximation is represented as
``None``, never as ``0`` or an estimated figure. Each such field's
docstring states precisely why it is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.models import ApprovalThroughput, StatusBreakdown
from app.models.enums import UserRole

__all__ = [
    "TimeGranularity",
    "TrendPoint",
    "TimeSeries",
    "ApprovalMetrics",
    "DashboardMetrics",
    "WorkflowMetrics",
    "DepartmentMetrics",
    "UserMetrics",
    "AnalyticsSummary",
]


class TimeGranularity(StrEnum):
    """The three time-bucket sizes this package's trend aggregations support."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"


@dataclass(frozen=True, slots=True)
class TrendPoint:
    """A single bucketed point within a time series.

    Attributes:
        label: A short, human-readable label for this bucket (e.g.
            ``"2026-07-10"`` for a day, ``"2026-W28"`` for a week,
            ``"2026-07"`` for a month).
        period_start: The bucket's inclusive start timestamp.
        period_end: The bucket's exclusive end timestamp.
        value: The bucket's aggregated value (a count, in the current
            baseline's only producer, ``aggregations.build_time_series``).
    """

    label: str
    period_start: datetime
    period_end: datetime
    value: float


@dataclass(frozen=True, slots=True)
class TimeSeries:
    """An ordered sequence of bucketed trend points.

    Attributes:
        granularity: The bucket size every point in ``points`` shares.
        points: The bucketed points, ordered by ``period_start``
            ascending. This series is built from an exhaustive fetch of
            every matching record (no artificial page cap), so it
            represents the complete population in scope, not a sample.
    """

    granularity: TimeGranularity
    points: tuple[TrendPoint, ...]

    @property
    def total(self) -> float:
        """The sum of every point's value across the whole series."""
        return sum(point.value for point in self.points)


@dataclass(frozen=True, slots=True)
class ApprovalMetrics:
    """A composed set of approval-related metrics.

    Attributes:
        throughput: The underlying decision-latency and completion-rate
            figures. ``completed_count``, ``rejected_count``, and
            ``completion_rate`` are always exact for whatever
            department/request_type scope was requested, since
            ``AnalyticsRepository.count_requests_by_status`` natively
            supports both filters. ``average_decision_seconds`` is exact
            only when no department scope is applied (see that field's
            own note); it is ``None`` whenever a department filter is in
            effect, since ``AnalyticsRepository.approval_throughput``
            has no department parameter and computing it correctly would
            require iterating every matching request's stages
            individually (an N+1 pattern this package does not
            introduce).
        average_stage_duration_seconds: The same underlying quantity as
            ``throughput.average_decision_seconds``, exposed under the
            "stage duration" reporting term; ``None`` under the same
            condition.
        approval_latency_seconds: The same underlying quantity again,
            exposed under the SLA-reporting term "latency"; ``None``
            under the same condition.
        escalation_count: The number of ``STAGE_ESCALATED`` audit
            events in scope. This is exact only when computed
            organization-wide (no department or request_type filter
            applied) — ``audit_logs`` carries neither column, so a
            scoped count is not obtainable without joining through every
            matching request individually. Whenever a department or
            request_type scope is in effect, this field is ``None``.
        reminder_count: Always ``None``. ``NotificationRepository``
            exposes no method to query notifications across recipients
            — every read method requires a specific ``recipient_id`` —
            so an organization-wide (or any scoped) reminder count is
            not obtainable without looping over every profile
            individually, which this package does not do.
    """

    throughput: ApprovalThroughput
    average_stage_duration_seconds: float | None
    approval_latency_seconds: float | None
    escalation_count: int | None
    reminder_count: int | None


@dataclass(frozen=True, slots=True)
class DashboardMetrics:
    """Organization-wide, at-a-glance dashboard figures.

    Attributes:
        status_breakdown: Request counts grouped by lifecycle status.
        total_requests: The total number of requests in scope.
        active_requests: Requests not yet in a terminal status
            (``pending`` or ``in_review``).
        completed_requests: Requests that reached ``completed``.
        rejected_requests: Requests that reached ``rejected``.
        approval_metrics: Approval metrics for the same scope; see
            ``ApprovalMetrics``'s own docstring for which fields become
            ``None`` when a department or request_type filter is active.
    """

    status_breakdown: StatusBreakdown
    total_requests: int
    active_requests: int
    completed_requests: int
    rejected_requests: int
    approval_metrics: ApprovalMetrics


@dataclass(frozen=True, slots=True)
class WorkflowMetrics:
    """Metrics scoped to a single request type (workflow).

    Attributes:
        request_type: The request type these metrics describe.
        status_breakdown: Request counts grouped by lifecycle status,
            scoped to this request type.
        approval_metrics: Approval metrics scoped to this request type.
            Per ``ApprovalMetrics``'s own docstring, ``escalation_count``
            is always ``None`` here (request_type is not a filterable
            column on ``audit_logs``); ``reminder_count`` is always
            ``None``; ``average_decision_seconds`` is exact (request
            type *is* a supported filter on
            ``AnalyticsRepository.approval_throughput``, so this is not
            subject to the department limitation).
        throughput_per_day: The average number of requests of this type
            completed per day. Exact only when the caller supplied both
            ``created_after`` and ``created_before`` explicitly, giving
            a real period length to divide by; ``None`` otherwise, since
            no default period assumption is made.
    """

    request_type: str
    status_breakdown: StatusBreakdown
    approval_metrics: ApprovalMetrics
    throughput_per_day: float | None


@dataclass(frozen=True, slots=True)
class DepartmentMetrics:
    """Metrics scoped to a single department.

    Attributes:
        department: The department these metrics describe.
        status_breakdown: Request counts grouped by lifecycle status,
            scoped to this department.
        approval_metrics: Approval metrics scoped to this department.
            ``completed_count``/``rejected_count``/``completion_rate``
            are exact (derived from the department-scoped
            ``status_breakdown``); ``average_decision_seconds``,
            ``escalation_count``, and ``reminder_count`` are always
            ``None`` — see ``ApprovalMetrics``'s docstring for why.
        workload: The number of this department's requests not yet in a
            terminal status. Exact.
    """

    department: str
    status_breakdown: StatusBreakdown
    approval_metrics: ApprovalMetrics
    workload: int


@dataclass(frozen=True, slots=True)
class UserMetrics:
    """Metrics scoped to a single user.

    Attributes:
        user_id: The user's id.
        full_name: The user's display name.
        role: The user's RBAC role.
        decisions_approved: The number of ``STAGE_APPROVED`` audit
            events attributed to this user. Exact.
        decisions_rejected: The number of ``STAGE_REJECTED`` audit
            events attributed to this user. Exact.
        pending_assigned_count: The number of stages currently pending
            this user's decision. Exact.
        average_decision_seconds: Always ``None``. No repository method
            exists to list workflow stages filtered by ``decided_by``
            — only by ``request_id`` — so computing this would require
            iterating every request in the system to reconstruct a
            per-user history, which is not a real aggregation. This
            field is retained for forward compatibility should such a
            query become available in a future revision of
            ``app.database``.
    """

    user_id: UUID
    full_name: str
    role: UserRole
    decisions_approved: int
    decisions_rejected: int
    pending_assigned_count: int
    average_decision_seconds: float | None

    @property
    def decisions_made(self) -> int:
        """The total number of decisions (approvals plus rejections) this user has made."""
        return self.decisions_approved + self.decisions_rejected


@dataclass(frozen=True, slots=True)
class AnalyticsSummary:
    """A structured report, suitable for a dashboard or an export.

    Every ``reporting.ReportingEngine.build_*`` method returns one of
    these, populating only the fields relevant to that specific report
    type and leaving the rest at their empty defaults.

    Attributes:
        title: A short, human-readable report title.
        generated_at: When this summary was assembled.
        dashboard: Organization-wide dashboard figures, populated for
            executive and operational summaries.
        workflow_metrics: Per-workflow metrics, populated for workflow
            summaries (a single-element tuple in the current baseline,
            since each call scopes to one request type).
        department_metrics: Per-department metrics, populated for
            department summaries.
        user_metrics: Per-user metrics, populated for user and workload
            summaries.
        trend: A time series relevant to this report, if applicable.
        narrative: A short, plain-text summary of the figures above,
            suitable for display alongside the structured data. Any
            underlying figure that is ``None`` (unavailable) is
            rendered as ``"unavailable"`` in this text, never omitted
            silently or presented as zero.
    """

    title: str
    generated_at: datetime
    dashboard: DashboardMetrics | None = None
    workflow_metrics: tuple[WorkflowMetrics, ...] = ()
    department_metrics: tuple[DepartmentMetrics, ...] = ()
    user_metrics: tuple[UserMetrics, ...] = ()
    trend: TimeSeries | None = None
    narrative: str = ""
