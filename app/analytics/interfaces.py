"""Protocols and shared type variables for app.analytics.

Per this package's design brief, four abstractions are defined here:
``MetricCalculator`` (a single, named, deferred computation),
``AggregationProvider`` (a reusable bucketing strategy over a sequence of
items), ``AnalyticsProvider`` (the facade ``AnalyticsEngine`` implements),
and ``ReportingProvider`` (the facade ``ReportingEngine`` implements).
Depending on these protocols, rather than on the concrete
``AnalyticsEngine``/``ReportingEngine`` classes directly, is what keeps
``reporting.py`` decoupled from ``analytics_engine.py``'s internals.

Milestone 12 adds a fifth: ``OperationalAnalyticsProvider``, the facade
``operational_engine.OperationalAnalyticsEngine`` implements — built on
top of, and depending on, ``AnalyticsProvider`` itself (composition, not
a parallel hierarchy), so SLA/bottleneck/workload/trend/executive/
department intelligence reuses every figure ``AnalyticsEngine`` already
computes rather than re-deriving it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol, TypeVar, runtime_checkable
from uuid import UUID

from app.analytics.dto import (
    AnalyticsSummary,
    ApprovalMetrics,
    DashboardMetrics,
    DepartmentMetrics,
    TimeGranularity,
    TimeSeries,
    UserMetrics,
    WorkflowMetrics,
)
from app.analytics.operational_dto import (
    ApprovalDelayReport,
    BottleneckReport,
    DepartmentAnalytics,
    ExecutiveKPIs,
    SLAMetrics,
    TrendReport,
    WorkloadReport,
)
from app.database.repositories.workflow_repository import WorkflowStageRecord

__all__ = [
    "MetricCalculator",
    "AggregationProvider",
    "AnalyticsProvider",
    "ReportingProvider",
    "OperationalAnalyticsProvider",
]

#: Appears only in MetricCalculator.compute's return position, so it must
#: be declared covariant to satisfy Protocol variance rules.
ResultT = TypeVar("ResultT", covariant=True)
#: Appears only in AggregationProvider.aggregate's parameter position, so
#: it must be declared contravariant to satisfy Protocol variance rules.
ItemT = TypeVar("ItemT", contravariant=True)
KeyT = TypeVar("KeyT")


@runtime_checkable
class MetricCalculator(Protocol[ResultT]):
    """Structural interface for a single, named, deferred metric computation.

    Every concrete metric in ``metrics.py`` is a plain, pure function;
    this protocol exists for the cases where a metric needs to be held,
    passed around, or registered by name before being evaluated (see
    ``metrics.MetricRegistry``), rather than invoked immediately.
    """

    def compute(self) -> ResultT:
        """Evaluate this metric.

        Returns:
            The computed metric value.

        Raises:
            MetricCalculationError: If computation fails.
        """
        ...


@runtime_checkable
class AggregationProvider(Protocol[ItemT, KeyT]):
    """Structural interface for a reusable, key-based bucketing strategy."""

    def aggregate(self, items: Sequence[ItemT]) -> Mapping[KeyT, int]:
        """Group a sequence of items by key, counting occurrences per key.

        Args:
            items: The items to group.

        Returns:
            A mapping from each distinct key present in ``items`` to the
            number of items sharing that key.
        """
        ...


@runtime_checkable
class AnalyticsProvider(Protocol):
    """Structural interface the analytics engine satisfies.

    Every method here is read-only and performs no state mutation of any
    kind, per this package's design brief. Every returned DTO may carry
    ``None`` in a given field where that value cannot be computed
    accurately for the requested scope — see ``dto.py`` for the precise
    conditions under which each such field is unavailable.
    """

    def get_dashboard_metrics(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> DashboardMetrics:
        """Return a company's dashboard figures, optionally further scoped.

        ``company_id`` is required on every method of this protocol: every
        figure this package computes is scoped to exactly one company
        (tenant), never the whole platform, and never client-suppliable —
        callers must derive it from the caller's own
        ``AuthenticatedIdentity.company_id``. There is no "unscoped" or
        "all companies" mode; a platform administrator who needs a
        cross-company view uses a separate, dedicated platform API, never
        this one (see ``app.api.routers.platform``).
        """
        ...

    def get_approval_metrics(
        self,
        *,
        company_id: UUID,
        request_type: str | None = None,
        department: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> ApprovalMetrics:
        """Return a company's approval-related metrics, optionally further scoped."""
        ...

    def get_workflow_metrics(
        self,
        request_type: str,
        *,
        company_id: UUID,
        department: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> WorkflowMetrics:
        """Return a company's metrics scoped to a single request type."""
        ...

    def get_department_metrics(
        self,
        department: str,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> DepartmentMetrics:
        """Return a company's metrics scoped to a single department."""
        ...

    def get_user_metrics(self, user_id: UUID, *, company_id: UUID) -> UserMetrics:
        """Return metrics scoped to a single user within a company.

        ``user_id`` must resolve to a profile belonging to ``company_id``;
        a user_id belonging to a different company is treated identically
        to a user_id that does not exist at all (never distinguished),
        per this codebase's established not-found-vs-forbidden
        convention for out-of-scope resources.
        """
        ...

    def get_workload_summary(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        pending_stages: Sequence[WorkflowStageRecord] | None = None,
    ) -> tuple[UserMetrics, ...]:
        """Return per-user metrics for every approver/administrator in a company.

        Args:
            company_id: Restricts every figure to this company (tenant).
            department: Restrict to approvers/administrators in this
                department, if provided.
            pending_stages: An already-fetched, company-wide (unfiltered
                by department) pending-stage population, if the caller
                has already performed this exact exhaustive fetch itself
                — skips this method's own equivalent internal fetch,
                avoiding a second full scan of the same rows within one
                request. ``None`` (the default) preserves this method's
                original, fully self-contained behavior.
        """
        ...

    def get_request_trend(
        self,
        *,
        company_id: UUID,
        granularity: TimeGranularity,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> TimeSeries:
        """Return a company's time series of request submission volume, bucketed by granularity."""
        ...


@runtime_checkable
class ReportingProvider(Protocol):
    """Structural interface the reporting engine satisfies."""

    def build_executive_summary(
        self,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> AnalyticsSummary:
        """Build a high-level, company-wide summary.

        ``company_id`` is required on every method of this protocol, for
        the same reason as ``AnalyticsProvider`` — see that protocol's
        own docstring.
        """
        ...

    def build_operational_summary(
        self,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> AnalyticsSummary:
        """Build a day-to-day operational summary for a company."""
        ...

    def build_workflow_summary(
        self,
        request_type: str,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> AnalyticsSummary:
        """Build a summary scoped to a single request type within a company."""
        ...

    def build_department_summary(
        self,
        department: str,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> AnalyticsSummary:
        """Build a summary scoped to a single department within a company."""
        ...

    def build_user_summary(self, user_id: UUID, *, company_id: UUID) -> AnalyticsSummary:
        """Build a summary scoped to a single user within a company."""
        ...


@runtime_checkable
class OperationalAnalyticsProvider(Protocol):
    """Structural interface the Operational Analytics Layer's engine
    satisfies (Milestone 12).

    Every method requires ``company_id``, for the same tenant-isolation
    reason as ``AnalyticsProvider`` — see that protocol's own docstring.
    ``department``/``request_type``/date-range filters are supported
    wherever the underlying figures can be meaningfully scoped by them,
    matching ``AnalyticsProvider``'s own filter surface exactly rather
    than introducing a new filtering convention.
    """

    def get_sla_metrics(
        self,
        *,
        company_id: UUID,
        sla_hours_override: float | None = None,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> SLAMetrics:
        """Return a company's SLA compliance snapshot, optionally further scoped."""
        ...

    def get_approval_delays(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 10,
    ) -> ApprovalDelayReport:
        """Return a company's approval-delay datasets, optionally further scoped."""
        ...

    def get_bottlenecks(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 10,
    ) -> BottleneckReport:
        """Return a company's bottleneck-identification datasets, optionally further scoped."""
        ...

    def get_workload_report(
        self, *, company_id: UUID, department: str | None = None
    ) -> WorkloadReport:
        """Return a company's workload distribution, optionally scoped to a department."""
        ...

    def get_trends(
        self,
        *,
        company_id: UUID,
        granularity: TimeGranularity,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> TrendReport:
        """Return a company's execution trends, optionally further scoped."""
        ...

    def get_executive_kpis(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> ExecutiveKPIs:
        """Return a company's single-screen executive KPI composite."""
        ...

    def get_department_analytics(
        self,
        department: str,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> DepartmentAnalytics:
        """Return operational figures scoped to a single department."""
        ...
