"""Reusable, pure aggregation and time-bucketing logic.

Per this package's design brief, this module provides two families of
reusable aggregation: key-based counting (grouping an already-fetched
sequence of records by department, request type, requester, decider,
actor, or assignee) and time-bucketing (grouping a sequence of
timestamps into day/week/month buckets for trend reporting). Every
function and class here is pure — it operates only on data already
passed in by the caller and performs no I/O.

These functions are the building blocks ``analytics_engine.AnalyticsEngine``
uses to compute a "group by" result client-side after a single,
exhaustive fetch of the relevant records — never by issuing one query
per group, which would be an N+1 pattern this package does not
introduce.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Generic, TypeVar
from uuid import UUID

from app.analytics.dto import TimeGranularity, TimeSeries, TrendPoint
from app.analytics.exceptions import AggregationError
from app.utils.datetime_utils import ensure_timezone_aware

__all__ = [
    "CountAggregator",
    "by_department",
    "by_request_type",
    "by_requester",
    "by_workflow_definition",
    "by_decider",
    "by_actor",
    "by_assignee",
    "build_time_series",
    "build_average_time_series",
]

ItemT = TypeVar("ItemT")
KeyT = TypeVar("KeyT")


@dataclass(slots=True)
class CountAggregator(Generic[ItemT, KeyT]):
    """A generic, reusable key-based counting aggregator.

    Attributes:
        key_fn: A callable extracting the grouping key from a single
            item.
    """

    key_fn: Callable[[ItemT], KeyT]

    def aggregate(self, items: Sequence[ItemT]) -> dict[KeyT, int]:
        """Group items by key, counting occurrences per key.

        Args:
            items: The items to group.

        Returns:
            A mapping from each distinct key present in ``items`` to the
            number of items sharing that key, in first-seen order.
        """
        result: dict[KeyT, int] = {}
        for item in items:
            key = self.key_fn(item)
            result[key] = result.get(key, 0) + 1
        return result


def by_department(requests: Sequence[object]) -> dict[str, int]:
    """Group a sequence of request-like records by department.

    Args:
        requests: A sequence of objects exposing a ``department``
            attribute. Records with no department set are grouped under
            ``"unspecified"``.

    Returns:
        A mapping from department name to request count.
    """
    return CountAggregator[object, str](
        key_fn=lambda r: getattr(r, "department", None) or "unspecified"
    ).aggregate(requests)


def by_request_type(requests: Sequence[object]) -> dict[str, int]:
    """Group a sequence of request-like records by request type.

    Args:
        requests: A sequence of objects exposing a ``request_type``
            attribute.

    Returns:
        A mapping from request type to request count.
    """
    return CountAggregator[object, str](key_fn=lambda r: getattr(r, "request_type")).aggregate(
        requests
    )


def by_requester(requests: Sequence[object]) -> dict[UUID, int]:
    """Group a sequence of request-like records by requester.

    Args:
        requests: A sequence of objects exposing a ``requester_id``
            attribute.

    Returns:
        A mapping from requester id to request count.
    """
    return CountAggregator[object, UUID](key_fn=lambda r: getattr(r, "requester_id")).aggregate(
        requests
    )


def by_workflow_definition(requests: Sequence[object]) -> dict[UUID, int]:
    """Group a sequence of request-like records by the specific workflow
    definition version governing them.

    Args:
        requests: A sequence of objects exposing a
            ``workflow_definition_id`` attribute.

    Returns:
        A mapping from workflow definition id to request count.
    """
    return CountAggregator[object, UUID](
        key_fn=lambda r: getattr(r, "workflow_definition_id")
    ).aggregate(requests)


def by_decider(stages: Sequence[object]) -> dict[UUID, int]:
    """Group a sequence of decided-stage-like records by the approver who decided them.

    Args:
        stages: A sequence of objects exposing a ``decided_by``
            attribute. Stages with no ``decided_by`` set (still pending)
            are excluded.

    Returns:
        A mapping from approver id to decision count.
    """
    decided_only = [s for s in stages if getattr(s, "decided_by", None) is not None]
    return CountAggregator[object, UUID](key_fn=lambda s: getattr(s, "decided_by")).aggregate(
        decided_only
    )


def by_actor(entries: Sequence[object]) -> dict[UUID, int]:
    """Group a sequence of audit-log-like records by the acting user.

    Args:
        entries: A sequence of objects exposing an ``actor_id``
            attribute (e.g.
            ``app.database.repositories.audit_repository.AuditLogRecord``).
            Entries with ``actor_id=None`` (system-initiated actions)
            are excluded.

    Returns:
        A mapping from actor id to entry count.
    """
    with_actor = [e for e in entries if getattr(e, "actor_id", None) is not None]
    return CountAggregator[object, UUID](key_fn=lambda e: getattr(e, "actor_id")).aggregate(
        with_actor
    )


def by_assignee(stages: Sequence[object]) -> dict[UUID, int]:
    """Group a sequence of pending-stage-like records by their specific assignee.

    Args:
        stages: A sequence of objects exposing an ``assigned_to``
            attribute. Stages with no specific assignee (``assigned_to``
            is ``None`` — a role-eligible pool stage, per WEDD Section
            7.3's ``department_queue`` strategy) are excluded.

    Returns:
        A mapping from assignee id to stage count.
    """
    assigned_only = [s for s in stages if getattr(s, "assigned_to", None) is not None]
    return CountAggregator[object, UUID](key_fn=lambda s: getattr(s, "assigned_to")).aggregate(
        assigned_only
    )


def _period_bounds(dt: datetime, granularity: TimeGranularity) -> tuple[str, datetime, datetime]:
    """Compute the bucket label and inclusive/exclusive bounds for a timestamp.

    Args:
        dt: The timestamp to bucket.
        granularity: The bucket size.

    Returns:
        A tuple of ``(label, period_start, period_end)``.
    """
    normalized = ensure_timezone_aware(dt)

    if granularity is TimeGranularity.DAY:
        start = normalized.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        label = start.strftime("%Y-%m-%d")
        return label, start, end

    if granularity is TimeGranularity.WEEK:
        start_of_week = normalized - timedelta(days=normalized.weekday())
        start = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        iso_year, iso_week, _ = start.isocalendar()
        label = f"{iso_year}-W{iso_week:02d}"
        return label, start, end

    # TimeGranularity.MONTH
    start = normalized.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    label = start.strftime("%Y-%m")
    return label, start, end


def build_time_series(timestamps: Sequence[datetime], granularity: TimeGranularity) -> TimeSeries:
    """Bucket a sequence of timestamps into a time series of counts.

    Args:
        timestamps: The timestamps to bucket (e.g. every matching
            request's ``created_at``, from an exhaustive fetch — not a
            sample).
        granularity: The bucket size.

    Returns:
        A ``TimeSeries`` with one ``TrendPoint`` per distinct bucket
        that contains at least one timestamp, ordered by
        ``period_start`` ascending. Buckets with no matching timestamps
        are omitted, not included with a zero value.

    Raises:
        AggregationError: If any value in ``timestamps`` is not a
            ``datetime`` instance.
    """
    bucket_counts: dict[str, int] = {}
    bucket_starts: dict[str, datetime] = {}
    bucket_ends: dict[str, datetime] = {}

    for ts in timestamps:
        if not isinstance(ts, datetime):
            raise AggregationError(f"Expected a datetime value to bucket, got {ts!r}.")
        label, start, end = _period_bounds(ts, granularity)
        bucket_counts[label] = bucket_counts.get(label, 0) + 1
        bucket_starts[label] = start
        bucket_ends[label] = end

    points = [
        TrendPoint(
            label=label,
            period_start=bucket_starts[label],
            period_end=bucket_ends[label],
            value=float(count),
        )
        for label, count in bucket_counts.items()
    ]
    points.sort(key=lambda point: point.period_start)
    return TimeSeries(granularity=granularity, points=tuple(points))


def build_average_time_series(
    entries: Sequence[tuple[datetime, float]], granularity: TimeGranularity
) -> TimeSeries:
    """Bucket a sequence of ``(timestamp, value)`` pairs into a time series of averages.

    The averaging counterpart to ``build_time_series``: used by the
    Operational Analytics Layer (Milestone 12) for trends where each
    bucket's point should be a mean of some per-item quantity (for
    example, average workflow completion duration per day) rather than a
    raw item count. Shares ``build_time_series``'s exact bucketing rule
    (via the same private ``_period_bounds`` helper) and its "omit empty
    buckets, never a zero-value placeholder" convention, so a caller
    switching between the two gets identical bucket boundaries.

    Args:
        entries: The ``(timestamp, value)`` pairs to bucket — for
            example, one ``(request.completed_at, duration_seconds)``
            pair per completed request, from an exhaustive fetch (no
            page cap), so the result reflects the complete matching
            population, not a sample.
        granularity: The bucket size.

    Returns:
        A ``TimeSeries`` with one ``TrendPoint`` per distinct bucket that
        contains at least one entry, ordered by ``period_start``
        ascending, each point's ``value`` the mean of that bucket's
        entries.

    Raises:
        AggregationError: If any timestamp in ``entries`` is not a
            ``datetime`` instance.
    """
    bucket_values: dict[str, list[float]] = {}
    bucket_starts: dict[str, datetime] = {}
    bucket_ends: dict[str, datetime] = {}

    for ts, value in entries:
        if not isinstance(ts, datetime):
            raise AggregationError(f"Expected a datetime value to bucket, got {ts!r}.")
        label, start, end = _period_bounds(ts, granularity)
        bucket_values.setdefault(label, []).append(value)
        bucket_starts[label] = start
        bucket_ends[label] = end

    points = [
        TrendPoint(
            label=label,
            period_start=bucket_starts[label],
            period_end=bucket_ends[label],
            value=sum(values) / len(values),
        )
        for label, values in bucket_values.items()
    ]
    points.sort(key=lambda point: point.period_start)
    return TimeSeries(granularity=granularity, points=tuple(points))
