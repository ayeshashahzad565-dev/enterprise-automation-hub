"""The Analytics Layer for the Enterprise Automation Hub.

Per this package's design brief, this package is responsible for
computing metrics, KPIs, summaries, and reporting data used by
dashboards and administrative views. It is entirely read-only: no
method anywhere in this package writes to the database, performs a
workflow decision, or renders a chart.

Every DTO this package returns may carry ``None`` in a field that cannot
be computed accurately from the finalized Repository Layer for the
requested scope, rather than a sampled, estimated, or default value —
see ``dto.py`` for the precise condition documented on each such field.

This package contains:

- ``exceptions``: the typed exception hierarchy for metric, aggregation,
  and reporting failures.
- ``dto``: the immutable dataclasses this package produces, reusing
  ``app.models.StatusBreakdown`` and ``app.models.ApprovalThroughput``
  directly rather than redefining them.
- ``interfaces``: the protocols (``MetricCalculator``,
  ``AggregationProvider``, ``AnalyticsProvider``, ``ReportingProvider``)
  keeping this package's components decoupled from each other.
- ``metrics``: independent, pure, composable metric calculations.
- ``aggregations``: reusable, pure key-based and time-based bucketing
  logic.
- ``analytics_engine``: ``AnalyticsEngine``, the central orchestration
  component coordinating repository queries and metric/aggregation
  calculations.
- ``reporting``: ``ReportingEngine``, which assembles structured
  ``AnalyticsSummary`` report DTOs from an injected ``AnalyticsProvider``.

This module re-exports the public surface of every submodule so that
calling code can import from ``app.analytics`` directly.
"""

from __future__ import annotations

from app.analytics.aggregations import (
    CountAggregator,
    build_time_series,
    by_actor,
    by_assignee,
    by_decider,
    by_department,
    by_request_type,
    by_requester,
    by_workflow_definition,
)
from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.dto import (
    AnalyticsSummary,
    ApprovalMetrics,
    DashboardMetrics,
    DepartmentMetrics,
    TimeGranularity,
    TimeSeries,
    TrendPoint,
    UserMetrics,
    WorkflowMetrics,
)
from app.analytics.exceptions import (
    AggregationError,
    AnalyticsError,
    InvalidTimeRangeError,
    MetricCalculationError,
    ReportingError,
)
from app.analytics.interfaces import (
    AggregationProvider,
    AnalyticsProvider,
    MetricCalculator,
    ReportingProvider,
)
from app.analytics.metrics import (
    CallableMetricCalculator,
    MetricRegistry,
    active_requests,
    approval_latency_seconds,
    average,
    average_approval_time_seconds,
    average_stage_duration_seconds,
    completed_requests,
    completion_rate,
    rejected_requests,
    total_requests,
    workflow_throughput_per_day,
)
from app.analytics.reporting import ReportingEngine

__all__ = [
    # aggregations
    "CountAggregator",
    "build_time_series",
    "by_actor",
    "by_assignee",
    "by_decider",
    "by_department",
    "by_request_type",
    "by_requester",
    "by_workflow_definition",
    # analytics_engine
    "AnalyticsEngine",
    # dto
    "AnalyticsSummary",
    "ApprovalMetrics",
    "DashboardMetrics",
    "DepartmentMetrics",
    "TimeGranularity",
    "TimeSeries",
    "TrendPoint",
    "UserMetrics",
    "WorkflowMetrics",
    # exceptions
    "AggregationError",
    "AnalyticsError",
    "InvalidTimeRangeError",
    "MetricCalculationError",
    "ReportingError",
    # interfaces
    "AggregationProvider",
    "AnalyticsProvider",
    "MetricCalculator",
    "ReportingProvider",
    # metrics
    "CallableMetricCalculator",
    "MetricRegistry",
    "active_requests",
    "approval_latency_seconds",
    "average",
    "average_approval_time_seconds",
    "average_stage_duration_seconds",
    "completed_requests",
    "completion_rate",
    "rejected_requests",
    "total_requests",
    "workflow_throughput_per_day",
    # reporting
    "ReportingEngine",
]