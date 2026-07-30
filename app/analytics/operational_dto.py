"""Immutable data transfer objects for the Operational Analytics Layer
(Milestone 12: SLA tracking, approval-delay detection, bottleneck
detection, workload analytics, trend analytics, executive KPIs, and
department analytics).

Per this package's design brief (see ``dto.py``), every DTO here is an
immutable, frozen dataclass, and any field that cannot be computed
accurately from real, already-persisted execution data is ``None``
rather than a fabricated or estimated value. Wherever an existing
``app.analytics.dto`` or ``app.models`` type already captures the
needed shape exactly (``UserMetrics`` for a per-approver figure,
``TimeSeries`` for a bucketed trend), it is reused directly here, never
redefined — this module adds only the shapes genuinely new to
operational intelligence: SLA snapshots, ranked delay/bottleneck tables,
and small named "key -> aggregate" buckets.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.analytics.dto import TimeSeries, UserMetrics
from app.models.enums import UserRole

__all__ = [
    "PendingApprovalAge",
    "SLAMetrics",
    "DurationBucket",
    "ApprovalDelayReport",
    "CountBucket",
    "RejectionBucket",
    "BottleneckReport",
    "WorkloadReport",
    "TrendReport",
    "ExecutiveKPIs",
    "DepartmentAnalytics",
]


@dataclass(frozen=True, slots=True)
class PendingApprovalAge:
    """One currently pending stage, with its live age and SLA status.

    Attributes:
        stage_id: The stage's id.
        request_id: The owning request's id.
        request_title: The owning request's title.
        request_type: The owning request's type.
        department: The owning request's department, if any.
        stage_name: The stage's human-readable label.
        stage_order: The stage's 1-indexed position in its workflow.
        assigned_to: The stage's specific assignee, if resolved.
        assigned_role: The stage's eligible role, if not assigned to a
            specific user.
        created_at: When this stage began waiting for a decision.
        age_hours: Hours elapsed since ``created_at``, computed at query
            time.
        sla_hours: The SLA threshold this stage is evaluated against —
            either the caller's explicit override, or (the default) the
            stage's own workflow definition's configured
            ``escalation_hours``. ``None`` only if neither is available
            (the owning workflow definition could not be resolved).
        is_overdue: Whether ``age_hours`` has already exceeded
            ``sla_hours`` — computed via the same
            ``WorkflowEngine.is_stage_escalation_eligible`` function the
            Scheduler's Escalation Check job already uses, so "SLA
            breach" and "escalation eligible" are, by construction, the
            same real, already-governing threshold, never a second,
            independently invented one.
    """

    stage_id: UUID
    request_id: UUID
    request_title: str
    request_type: str
    department: str | None
    stage_name: str
    stage_order: int
    assigned_to: UUID | None
    assigned_role: UserRole | None
    created_at: datetime
    age_hours: float
    sla_hours: float | None
    is_overdue: bool


@dataclass(frozen=True, slots=True)
class SLAMetrics:
    """A company's (optionally further-scoped) SLA compliance snapshot.

    Attributes:
        sla_hours_override: The caller-supplied SLA threshold used for
            this snapshot's overdue calculations, if one was provided;
            ``None`` when every stage was evaluated against its own
            workflow definition's ``escalation_hours`` instead (the
            default, real-data behavior).
        pending_stage_count: The number of currently pending stages in
            scope.
        overdue_stage_count: Of those, the number currently past their
            SLA threshold.
        overdue_request_count: The number of distinct requests with at
            least one currently overdue stage.
        average_current_stage_age_hours: The mean age, in hours, of every
            currently pending stage in scope. ``None`` if none are
            pending.
        decided_stage_count: The number of approved-or-rejected stages
            considered for the compliance percentage below.
        sla_breaches_decided: Of those, the number decided *after* their
            own SLA threshold had already passed.
        sla_compliance_percentage: The fraction of ``decided_stage_count``
            that did **not** breach — see
            ``app.analytics.metrics.compliance_rate``. ``None`` if no
            stage was decided in scope.
        average_total_workflow_duration_seconds: The mean
            ``completed_at - created_at`` across every completed request
            in scope. ``None`` if none completed.
        average_approval_duration_seconds: The mean per-stage decision
            latency in scope — the same figure
            ``AnalyticsRepository.approval_throughput`` already computes
            (reused directly, not recomputed).
    """

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


@dataclass(frozen=True, slots=True)
class DurationBucket:
    """A named group's average decision duration — the shared shape
    behind every "duration/slowness by X" breakdown this layer produces
    (by stage, by department, by workflow).

    Attributes:
        key: The grouping key (a stage name, department, or request
            type).
        average_seconds: The mean ``decided_at - created_at`` across this
            group's decided stages. ``None`` if the group has no decided
            stage in scope.
        count: The number of decided stages this average was computed
            over.
    """

    key: str
    average_seconds: float | None
    count: int


@dataclass(frozen=True, slots=True)
class ApprovalDelayReport:
    """Sortable approval-delay datasets for a company.

    Attributes:
        longest_pending: Currently pending stages, oldest (largest
            ``age_hours``) first.
        oldest_pending_requests: Currently pending stages, one per
            distinct request, ordered by the *request's* own
            ``created_at`` ascending (oldest request first) — distinct
            from ``longest_pending``, which ranks by the *current
            stage's* own age and may include more than one stage per
            request's history.
        average_approval_seconds: The mean decision latency across every
            decided stage in scope.
        median_approval_seconds: The median decision latency across the
            same population — a second, more outlier-resistant central
            tendency figure the existing Analytics Layer does not
            compute.
        duration_by_stage: Average decision duration grouped by stage
            name.
        duration_by_department: Average decision duration grouped by the
            owning request's department.
        duration_by_workflow: Average decision duration grouped by the
            owning request's request type.
    """

    longest_pending: tuple[PendingApprovalAge, ...]
    oldest_pending_requests: tuple[PendingApprovalAge, ...]
    average_approval_seconds: float | None
    median_approval_seconds: float | None
    duration_by_stage: tuple[DurationBucket, ...]
    duration_by_department: tuple[DurationBucket, ...]
    duration_by_workflow: tuple[DurationBucket, ...]


@dataclass(frozen=True, slots=True)
class CountBucket:
    """A named group's raw count — used for "frequently overdue stages."

    Attributes:
        key: The grouping key (a stage name).
        count: The number of matching occurrences.
    """

    key: str
    count: int


@dataclass(frozen=True, slots=True)
class RejectionBucket:
    """A named group's rejection outcome rate — used for rejection hotspots.

    Attributes:
        key: The grouping key (a stage name).
        decided_count: The number of decided stages in this group.
        rejected_count: Of those, the number rejected.
        rejection_rate: ``rejected_count / decided_count``, or ``None``
            if ``decided_count`` is zero.
    """

    key: str
    decided_count: int
    rejected_count: int
    rejection_rate: float | None


@dataclass(frozen=True, slots=True)
class BottleneckReport:
    """Bottleneck-identification datasets for a company.

    Every figure here is derived from the same decided/pending stage
    populations ``ApprovalDelayReport``/``SLAMetrics`` already fetch —
    this report reuses those same computations' underlying data rather
    than issuing its own separate queries for an overlapping population.

    Attributes:
        slowest_stages: Stage names ranked by average decision duration,
            slowest first.
        slowest_workflows: Request types ranked by average decision
            duration, slowest first.
        departments_causing_delay: Departments ranked by average decision
            duration, slowest first.
        approver_queue_depth: Approvers/administrators ranked by
            ``pending_assigned_count`` descending — reuses
            ``AnalyticsProvider.get_workload_summary`` directly rather
            than recomputing pending counts.
        frequently_overdue_stages: Stage names ranked by how many
            *currently* overdue pending stages share that name,
            descending.
        rejection_hotspots: Stage names ranked by rejection rate,
            descending, restricted to stages with at least one decision
            in scope.
    """

    slowest_stages: tuple[DurationBucket, ...]
    slowest_workflows: tuple[DurationBucket, ...]
    departments_causing_delay: tuple[DurationBucket, ...]
    approver_queue_depth: tuple[UserMetrics, ...]
    frequently_overdue_stages: tuple[CountBucket, ...]
    rejection_hotspots: tuple[RejectionBucket, ...]


@dataclass(frozen=True, slots=True)
class WorkloadReport:
    """Workload distribution datasets for a company.

    Attributes:
        approvals_per_approver: Reuses
            ``AnalyticsProvider.get_workload_summary`` directly —
            per-approver pending/approved/rejected counts.
        requests_per_department: Reuses
            ``AnalyticsRepository.count_requests_by_department``
            directly.
        requests_per_workflow: Reuses
            ``AnalyticsRepository.count_requests_by_type`` directly.
        completed_today: Requests whose ``completed_at`` falls within
            the current UTC calendar day.
        completed_this_week: Requests whose ``completed_at`` falls within
            the trailing 7 days.
        completed_this_month: Requests whose ``completed_at`` falls
            within the trailing 30 days.
        active_workload: Requests not yet in a terminal status — reuses
            ``AnalyticsProvider.get_dashboard_metrics``'s
            ``active_requests``.
        completed_workload: Reuses ``get_dashboard_metrics``'s
            ``completed_requests``.
        pending_workload: The number of currently pending workflow
            stages in scope (distinct from ``active_workload``, which
            counts requests, not stages).
    """

    approvals_per_approver: tuple[UserMetrics, ...]
    requests_per_department: Mapping[str, int]
    requests_per_workflow: Mapping[str, int]
    completed_today: int
    completed_this_week: int
    completed_this_month: int
    active_workload: int
    completed_workload: int
    pending_workload: int


@dataclass(frozen=True, slots=True)
class TrendReport:
    """Execution trend datasets for a company, over a configurable date range.

    Attributes:
        request_volume: Submission-volume time series — reuses
            ``AnalyticsProvider.get_request_trend`` directly.
        completion_trend: Requests reaching ``COMPLETED``, bucketed by
            their own ``completed_at``.
        approval_trend: ``STAGE_APPROVED`` audit events, bucketed by
            ``created_at``.
        rejection_trend: ``STAGE_REJECTED`` audit events, bucketed by
            ``created_at``.
        average_completion_time_trend: The mean
            ``completed_at - created_at`` of requests completed within
            each bucket.
    """

    request_volume: TimeSeries
    completion_trend: TimeSeries
    approval_trend: TimeSeries
    rejection_trend: TimeSeries
    average_completion_time_trend: TimeSeries


@dataclass(frozen=True, slots=True)
class ExecutiveKPIs:
    """A single-screen composite of the figures an executive dashboard needs.

    Every field is either a direct reuse of an existing
    ``AnalyticsProvider``/``SLAMetrics`` figure, or a small, documented,
    deterministic composite of two such figures (``workflow_efficiency_score``)
    — never an independently invented or estimated number.

    Attributes:
        average_approval_seconds: Reused from ``SLAMetrics``.
        average_workflow_completion_seconds: Reused from ``SLAMetrics``.
        sla_compliance_percentage: Reused from ``SLAMetrics``.
        active_requests: Reused from ``DashboardMetrics``.
        completed_requests: Reused from ``DashboardMetrics``.
        pending_approvals: Reused from ``SLAMetrics.pending_stage_count``.
        overdue_approvals: Reused from ``SLAMetrics.overdue_stage_count``.
        rejection_rate: ``app.analytics.metrics.rejection_rate`` applied
            to the same terminal population ``DashboardMetrics`` already
            counted.
        throughput_per_day: Completed requests per day — exact only when
            the caller supplies both ``created_after`` and
            ``created_before`` explicitly (matching
            ``WorkflowMetrics.throughput_per_day``'s own documented
            condition); ``None`` otherwise.
        workflow_efficiency_score: See
            ``app.analytics.metrics.efficiency_score``'s docstring for
            the exact, deterministic formula.
    """

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


@dataclass(frozen=True, slots=True)
class DepartmentAnalytics:
    """Operational figures scoped to a single department.

    Attributes:
        department: The department these figures describe.
        throughput_per_day: Completed requests per day for this
            department; ``None`` unless both date bounds were supplied
            (same condition as ``ExecutiveKPIs.throughput_per_day``).
        sla_compliance_percentage: This department's SLA compliance rate
            over its own decided stages.
        average_approval_seconds: This department's mean decision
            latency.
        active_workload: This department's requests not yet in a
            terminal status — reused from
            ``AnalyticsProvider.get_department_metrics``'s ``workload``.
        backlog_count: This department's currently overdue pending
            stages.
    """

    department: str
    throughput_per_day: float | None
    sla_compliance_percentage: float | None
    average_approval_seconds: float | None
    active_workload: int
    backlog_count: int
