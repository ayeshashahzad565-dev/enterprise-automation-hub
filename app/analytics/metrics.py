"""Reusable, independent, pure metric calculations.

Per this package's design brief, every metric here is independent
(depends only on its own explicit arguments, never on hidden state) and
composable (a metric may be built from the result of another, expressed
as a plain function call, never by re-deriving the same underlying
computation). None of these functions perform I/O; every value they need
is supplied by the caller (``analytics_engine.AnalyticsEngine``), which
is the only component in this package that talks to a repository.

Every function here returns ``None`` when its inputs do not permit an
accurate result (an empty population, a missing period length) rather
than substituting a default or estimated value.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, TypeVar

from app.analytics.exceptions import MetricCalculationError
from app.analytics.interfaces import MetricCalculator
from app.models.enums import RequestStatus
from app.utils.datetime_utils import seconds_between

__all__ = [
    "average",
    "median",
    "total_requests",
    "active_requests",
    "completed_requests",
    "rejected_requests",
    "completion_rate",
    "rejection_rate",
    "average_approval_time_seconds",
    "average_stage_duration_seconds",
    "approval_latency_seconds",
    "workflow_throughput_per_day",
    "compliance_rate",
    "efficiency_score",
    "period_days",
    "CallableMetricCalculator",
    "MetricRegistry",
]

ResultT = TypeVar("ResultT")

#: The set of ``RequestStatus`` values considered "active" — not yet
#: terminal. ``RequestStatus.APPROVED`` is deliberately excluded, per
#: WEDD Section 20.1's note that it is reserved for forward compatibility
#: and unreachable in the current baseline.
_ACTIVE_STATUSES: frozenset[RequestStatus] = frozenset(
    {RequestStatus.PENDING, RequestStatus.IN_REVIEW}
)


def average(values: Sequence[float]) -> float | None:
    """Compute the arithmetic mean of a sequence of numbers.

    Args:
        values: The values to average.

    Returns:
        The mean, or ``None`` if ``values`` is empty (avoiding a
        division-by-zero rather than raising, since an empty population
        is a normal, expected outcome for many scoped queries).
    """
    materialized = list(values)
    if not materialized:
        return None
    return sum(materialized) / len(materialized)


def median(values: Sequence[float]) -> float | None:
    """Compute the median of a sequence of numbers.

    Args:
        values: The values to find the median of.

    Returns:
        The median, or ``None`` if ``values`` is empty (the same
        empty-population convention ``average`` uses, for the same
        reason — an empty population is a normal, expected outcome for
        many scoped queries, not an error).
    """
    materialized = list(values)
    if not materialized:
        return None
    return statistics.median(materialized)


def total_requests(status_breakdown: Mapping[RequestStatus, int]) -> int:
    """Compute the total request count from a per-status breakdown.

    Args:
        status_breakdown: A mapping from status to count, as produced by
            ``app.models.StatusBreakdown.counts``.

    Returns:
        The sum of every count in ``status_breakdown``.
    """
    return sum(status_breakdown.values())


def active_requests(status_breakdown: Mapping[RequestStatus, int]) -> int:
    """Compute the number of requests not yet in a terminal status.

    Args:
        status_breakdown: A mapping from status to count.

    Returns:
        The sum of counts for ``pending`` and ``in_review``.
    """
    return sum(count for status, count in status_breakdown.items() if status in _ACTIVE_STATUSES)


def completed_requests(status_breakdown: Mapping[RequestStatus, int]) -> int:
    """Compute the number of requests that reached ``completed``.

    Args:
        status_breakdown: A mapping from status to count.

    Returns:
        The count for ``RequestStatus.COMPLETED``, or ``0`` if absent
        (an absent key genuinely means zero matching requests, which is
        distinct from "unavailable").
    """
    return status_breakdown.get(RequestStatus.COMPLETED, 0)


def rejected_requests(status_breakdown: Mapping[RequestStatus, int]) -> int:
    """Compute the number of requests that reached ``rejected``.

    Args:
        status_breakdown: A mapping from status to count.

    Returns:
        The count for ``RequestStatus.REJECTED``, or ``0`` if absent.
    """
    return status_breakdown.get(RequestStatus.REJECTED, 0)


def completion_rate(completed_count: int, rejected_count: int) -> float | None:
    """Compute the fraction of terminal requests that completed successfully.

    Args:
        completed_count: The number of completed requests.
        rejected_count: The number of rejected requests.

    Returns:
        ``completed_count / (completed_count + rejected_count)``, or
        ``None`` if neither occurred (avoiding a division by zero).
    """
    terminal_total = completed_count + rejected_count
    if terminal_total == 0:
        return None
    return completed_count / terminal_total


def rejection_rate(completed_count: int, rejected_count: int) -> float | None:
    """Compute the fraction of terminal requests that were rejected.

    The complement of ``completion_rate`` over the same terminal
    population (``1 - completion_rate``), exposed as its own named
    function because "rejection rate" is a distinct term in this
    system's reporting vocabulary, used directly rather than requiring
    every caller to re-derive it from ``completion_rate``.

    Args:
        completed_count: The number of completed requests.
        rejected_count: The number of rejected requests.

    Returns:
        ``rejected_count / (completed_count + rejected_count)``, or
        ``None`` if neither occurred (avoiding a division by zero).
    """
    terminal_total = completed_count + rejected_count
    if terminal_total == 0:
        return None
    return rejected_count / terminal_total


def average_approval_time_seconds(average_decision_seconds: float | None) -> float | None:
    """Return the average time between a stage's creation and its decision.

    This is a pass-through of a value already computed by
    ``app.database.repositories.analytics_repository.AnalyticsRepository.approval_throughput``
    — it is not recomputed here. It is exposed under this name because
    "average approval time" is the throughput-reporting vocabulary term
    for this quantity; see ``average_stage_duration_seconds`` and
    ``approval_latency_seconds`` for the same underlying value exposed
    under two other reporting vocabularies.

    Args:
        average_decision_seconds: The value already computed by the
            Repository Layer, or ``None`` if unavailable for the
            requested scope.

    Returns:
        ``average_decision_seconds``, unchanged.
    """
    return average_decision_seconds


def average_stage_duration_seconds(average_decision_seconds: float | None) -> float | None:
    """Return the average time a workflow stage remains pending before being decided.

    With the current data model, this measures the identical quantity as
    ``average_approval_time_seconds`` — the time between a stage's
    ``created_at`` and its ``decided_at``. It is exposed as its own named
    function because "stage duration" is a distinct term in this
    system's reporting vocabulary from "approval time."

    Args:
        average_decision_seconds: The value already computed by the
            Repository Layer, or ``None`` if unavailable for the
            requested scope.

    Returns:
        ``average_decision_seconds``, unchanged.
    """
    return average_decision_seconds


def approval_latency_seconds(average_decision_seconds: float | None) -> float | None:
    """Return the average decision latency, in the SLA-reporting vocabulary.

    See ``average_stage_duration_seconds``'s docstring for the full
    rationale: this is the same underlying quantity, exposed under the
    term used in SLA-focused reporting contexts.

    Args:
        average_decision_seconds: The value already computed by the
            Repository Layer, or ``None`` if unavailable for the
            requested scope.

    Returns:
        ``average_decision_seconds``, unchanged.
    """
    return average_decision_seconds


def workflow_throughput_per_day(completed_count: int, period_days: float | None) -> float | None:
    """Compute the average number of requests completed per day over a period.

    Args:
        completed_count: The number of requests completed during the
            period.
        period_days: The length of the period, in days, or ``None`` if
            no explicit period could be determined (see
            ``analytics_engine.AnalyticsEngine._period_days``, which
            returns ``None`` unless the caller supplied both an explicit
            lower and upper date bound — no default period is assumed).

    Returns:
        ``completed_count / period_days``, or ``None`` if ``period_days``
        is ``None`` or not positive.
    """
    if period_days is None or period_days <= 0:
        return None
    return completed_count / period_days


def compliance_rate(in_sla_count: int, breached_count: int) -> float | None:
    """Compute the fraction of a decided/evaluated population that met its SLA.

    Used by the Operational Analytics Layer's SLA Engine (Milestone 12)
    to turn a raw breach count into the "SLA compliance percentage"
    figure: the fraction of stages decided at-or-before their own
    configured ``escalation_hours`` threshold, over every stage evaluated
    (decided or currently overdue-and-pending).

    Args:
        in_sla_count: The number of items that met their threshold.
        breached_count: The number of items that missed their threshold.

    Returns:
        ``in_sla_count / (in_sla_count + breached_count)``, or ``None``
        if no item was evaluated at all (avoiding a division by zero).
    """
    evaluated_total = in_sla_count + breached_count
    if evaluated_total == 0:
        return None
    return in_sla_count / evaluated_total


def efficiency_score(
    completion_rate_value: float | None, sla_compliance_value: float | None
) -> float | None:
    """Compute a single, deterministic "workflow efficiency" composite score.

    Defined transparently as the product of two already-computed, real
    fractions — ``completion_rate`` (terminal requests that succeeded
    rather than being rejected) and SLA compliance (decisions made within
    their configured threshold) — so the result is always explainable
    from its two real inputs, never a fabricated or estimated figure.
    Both inputs already lie in ``[0, 1]``, so the product does too.

    Args:
        completion_rate_value: The population's completion rate, or
            ``None`` if unavailable.
        sla_compliance_value: The population's SLA compliance rate, or
            ``None`` if unavailable.

    Returns:
        ``completion_rate_value * sla_compliance_value``, or ``None`` if
        either input is unavailable — never a partial or estimated score
        computed from only one of the two.
    """
    if completion_rate_value is None or sla_compliance_value is None:
        return None
    return completion_rate_value * sla_compliance_value


def period_days(created_after: datetime | None, created_before: datetime | None) -> float | None:
    """Compute the length, in days, of a caller-supplied date range.

    Shared by every engine in this package that computes a "per day"
    throughput figure (``AnalyticsEngine``, ``OperationalAnalyticsEngine``),
    so this one rule — no default period is ever assumed, and a
    sub-daily range is treated as one day rather than a fraction, to
    keep a throughput calculation meaningful — is expressed exactly once.

    Args:
        created_after: The lower bound, if provided.
        created_before: The upper bound, if provided.

    Returns:
        The number of days between the two bounds (never less than one)
        if both are provided; ``None`` if either bound is missing.
    """
    if created_after is not None and created_before is not None:
        days = seconds_between(created_after, created_before) / 86400.0
        return days if days >= 1.0 else 1.0
    return None


@dataclass(frozen=True, slots=True)
class CallableMetricCalculator(Generic[ResultT]):
    """Adapts any zero-argument callable to the ``MetricCalculator`` protocol.

    Useful for registering an ad hoc computation (a closure over
    already-fetched data) as a named metric in a ``MetricRegistry``,
    without needing to write a dedicated class for every metric.

    Attributes:
        fn: The zero-argument callable performing the computation.
    """

    fn: Callable[[], ResultT]

    def compute(self) -> ResultT:
        """Invoke the wrapped callable.

        Returns:
            The callable's result.

        Raises:
            MetricCalculationError: If the wrapped callable raises.
        """
        try:
            return self.fn()
        except Exception as exc:  # noqa: BLE001 - translated into a typed error below
            raise MetricCalculationError(f"Metric calculation failed: {exc}") from exc


class MetricRegistry:
    """A named registry of deferred metric calculators.

    Provides a uniform, name-based way to evaluate a set of metrics —
    useful for a future export or ad hoc reporting feature that needs to
    enumerate "every metric currently available" without hard-coding a
    list of method calls.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._calculators: dict[str, MetricCalculator[Any]] = {}

    def register(self, name: str, calculator: MetricCalculator[Any]) -> None:
        """Register a named metric calculator.

        Args:
            name: A unique name for this metric.
            calculator: Any object satisfying the ``MetricCalculator``
                protocol.

        Raises:
            MetricCalculationError: If a metric with this name is
                already registered.
        """
        if name in self._calculators:
            raise MetricCalculationError(f"A metric named '{name}' is already registered.")
        self._calculators[name] = calculator

    def compute(self, name: str) -> Any:
        """Evaluate a single registered metric by name.

        Args:
            name: The metric's registered name.

        Returns:
            The computed value.

        Raises:
            MetricCalculationError: If no metric with this name is
                registered, or the metric's own computation fails.
        """
        calculator = self._calculators.get(name)
        if calculator is None:
            raise MetricCalculationError(f"No metric named '{name}' is registered.")
        return calculator.compute()

    def compute_all(self) -> dict[str, Any]:
        """Evaluate every registered metric.

        Returns:
            A mapping from metric name to its computed value.

        Raises:
            MetricCalculationError: If any registered metric's
                computation fails.
        """
        return {name: calculator.compute() for name, calculator in self._calculators.items()}
