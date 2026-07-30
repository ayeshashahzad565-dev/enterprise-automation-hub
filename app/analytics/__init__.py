"""The Analytics Layer for the Enterprise Automation Hub.

Per this package's design brief, this package is responsible for
computing metrics, KPIs, summaries, and reporting data used by
dashboards and administrative views. It is entirely read-only: no
method anywhere in this package writes to the database, performs a
workflow decision, or renders a chart.

Every DTO this package returns may carry ``None`` in a field that cannot
be computed accurately from the finalized Repository Layer for the
requested scope, rather than a sampled, estimated, or default value —
see ``dto.py``/``operational_dto.py`` for the precise condition
documented on each such field.

This package contains:

- ``exceptions``: the typed exception hierarchy for metric, aggregation,
  and reporting failures.
- ``dto``: the immutable dataclasses this package produces, reusing
  ``app.models.StatusBreakdown`` and ``app.models.ApprovalThroughput``
  directly rather than redefining them.
- ``operational_dto``: the immutable dataclasses the Operational
  Analytics Layer (Milestone 12) produces — SLA, approval-delay,
  bottleneck, workload, trend, executive-KPI, and department datasets.
- ``interfaces``: the protocols (``MetricCalculator``,
  ``AggregationProvider``, ``AnalyticsProvider``, ``ReportingProvider``,
  ``OperationalAnalyticsProvider``) keeping this package's components
  decoupled from each other.
- ``metrics``: independent, pure, composable metric calculations.
- ``aggregations``: reusable, pure key-based and time-based bucketing
  logic.
- ``analytics_engine``: ``AnalyticsEngine``, the central orchestration
  component coordinating repository queries and metric/aggregation
  calculations.
- ``reporting``: ``ReportingEngine``, which assembles structured
  ``AnalyticsSummary`` report DTOs from an injected ``AnalyticsProvider``.
- ``operational_engine``: ``OperationalAnalyticsEngine``, the Operational
  Analytics Layer's orchestration component, built on top of
  ``AnalyticsProvider`` rather than duplicating it.

This module re-exports the public surface of every submodule so that
calling code can import from ``app.analytics`` directly.
"""

from __future__ import annotations

from app.analytics.aggregations import (
    CountAggregator,
    build_average_time_series,
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
    validate_date_range,
)
from app.analytics.interfaces import (
    AggregationProvider,
    AnalyticsProvider,
    MetricCalculator,
    OperationalAnalyticsProvider,
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
    compliance_rate,
    efficiency_score,
    median,
    period_days,
    rejected_requests,
    rejection_rate,
    total_requests,
    workflow_throughput_per_day,
)
from app.analytics.operational_dto import (
    ApprovalDelayReport,
    BottleneckReport,
    CountBucket,
    DepartmentAnalytics,
    DurationBucket,
    ExecutiveKPIs,
    PendingApprovalAge,
    RejectionBucket,
    SLAMetrics,
    TrendReport,
    WorkloadReport,
)
from app.analytics.operational_engine import OperationalAnalyticsEngine
from app.analytics.reporting import ReportingEngine

__all__ = [
    # aggregations
    "CountAggregator",
    "build_average_time_series",
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
    "validate_date_range",
    # interfaces
    "AggregationProvider",
    "AnalyticsProvider",
    "MetricCalculator",
    "OperationalAnalyticsProvider",
    "ReportingProvider",
    # metrics
    "CallableMetricCalculator",
    "MetricRegistry",
    "active_requests",
    "approval_latency_seconds",
    "average",
    "average_approval_time_seconds",
    "average_stage_duration_seconds",
    "compliance_rate",
    "completed_requests",
    "completion_rate",
    "efficiency_score",
    "median",
    "period_days",
    "rejected_requests",
    "rejection_rate",
    "total_requests",
    "workflow_throughput_per_day",
    # operational_dto
    "ApprovalDelayReport",
    "BottleneckReport",
    "CountBucket",
    "DepartmentAnalytics",
    "DurationBucket",
    "ExecutiveKPIs",
    "PendingApprovalAge",
    "RejectionBucket",
    "SLAMetrics",
    "TrendReport",
    "WorkloadReport",
    # operational_engine
    "OperationalAnalyticsEngine",
    # reporting
    "ReportingEngine",
]
