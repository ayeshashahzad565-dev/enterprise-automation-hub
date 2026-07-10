"""Protocols and shared type variables for app.analytics.

Per this package's design brief, four abstractions are defined here:
``MetricCalculator`` (a single, named, deferred computation),
``AggregationProvider`` (a reusable bucketing strategy over a sequence of
items), ``AnalyticsProvider`` (the facade ``AnalyticsEngine`` implements),
and ``ReportingProvider`` (the facade ``ReportingEngine`` implements).
Depending on these protocols, rather than on the concrete
``AnalyticsEngine``/``ReportingEngine`` classes directly, is what keeps
``reporting.py`` decoupled from ``analytics_engine.py``'s internals.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Protocol, Sequence, TypeVar, runtime_checkable
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

__all__ = ["MetricCalculator", "AggregationProvider", "AnalyticsProvider", "ReportingProvider"]

ResultT = TypeVar("ResultT")
ItemT = TypeVar("ItemT")
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
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> DashboardMetrics:
        """Return organization-wide dashboard figures, optionally scoped."""
        ...

    def get_approval_metrics(
        self,
        *,
        request_type: str | None = None,
        department: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> ApprovalMetrics:
        """Return approval-related metrics, optionally scoped."""
        ...

    def get_workflow_metrics(
        self,
        request_type: str,
        *,
        department: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> WorkflowMetrics:
        """Return metrics scoped to a single request type."""
        ...

    def get_department_metrics(
        self,
        department: str,
        *,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> DepartmentMetrics:
        """Return metrics scoped to a single department."""
        ...

    def get_user_metrics(self, user_id: UUID) -> UserMetrics:
        """Return metrics scoped to a single user."""
        ...

    def get_workload_summary(
        self, *, department: str | None = None
    ) -> tuple[UserMetrics, ...]:
        """Return per-user metrics for every approver/administrator in scope."""
        ...

    def get_request_trend(
        self,
        *,
        granularity: TimeGranularity,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> TimeSeries:
        """Return a time series of request submission volume, bucketed by granularity."""
        ...


@runtime_checkable
class ReportingProvider(Protocol):
    """Structural interface the reporting engine satisfies."""

    def build_executive_summary(
        self, *, created_after: datetime | None = None, created_before: datetime | None = None
    ) -> AnalyticsSummary:
        """Build a high-level, organization-wide summary."""
        ...

    def build_operational_summary(
        self, *, created_after: datetime | None = None, created_before: datetime | None = None
    ) -> AnalyticsSummary:
        """Build a day-to-day operational summary."""
        ...

    def build_workflow_summary(
        self,
        request_type: str,
        *,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> AnalyticsSummary:
        """Build a summary scoped to a single request type."""
        ...

    def build_department_summary(
        self,
        department: str,
        *,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> AnalyticsSummary:
        """Build a summary scoped to a single department."""
        ...

    def build_user_summary(self, user_id: UUID) -> AnalyticsSummary:
        """Build a summary scoped to a single user."""
        ...