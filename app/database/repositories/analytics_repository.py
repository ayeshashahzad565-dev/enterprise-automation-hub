"""Read-only aggregation repository supporting ``AnalyticsService``.

Per the ADD's Component Breakdown, ``AnalyticsService`` (src/analytics)
queries aggregated data via repository methods and prepares it for
visualization with Plotly; the aggregation itself is a persistence-level
concern (shaping already-stored data), while chart rendering is not. This
repository performs simple, filtered aggregate reads against ``requests``
and ``workflow_stages`` — no dedicated aggregation table exists in the DSD,
so every method here computes its result from the same tables the rest of
this package already operates on, never from a separate analytics-only
data store.

Every method in this class is read-only. None of them insert, update, or
delete a row.

Every aggregate below is computed inside Postgres (``group by``/``count``/
``avg``, via a function called through PostgREST's RPC endpoint —
``self._client.rpc(...)``), not by fetching every matching row and
grouping in Python. The functions themselves live in
``app/database/migrations/versions/0022_analytics_aggregation_functions.py``,
whose docstring explains why: each of these queries used to transfer one
row per matching request (or per matching workflow stage) to produce, at
most, a handful of grouped counts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.repositories.base_repository import BaseRepository
from app.database.repositories.request_repository import RequestStatus

logger = logging.getLogger(__name__)


def _iso(value: datetime | None) -> str | None:
    """Render an optional timestamp as an ISO-8601 string, or ``None``.

    RPC parameters are sent as JSON, unlike ``.gte()``/``.lte()`` on a
    table query builder (which accept ``.isoformat()`` directly too) —
    kept as a tiny shared helper purely so every method below passes
    timestamps the same way, not because the two are ever actually
    different in shape.
    """
    return value.isoformat() if value is not None else None


@dataclass(frozen=True, slots=True)
class StatusBreakdown:
    """A count of requests grouped by lifecycle status.

    Attributes:
        counts: A mapping from each ``RequestStatus`` value present in the
            queried data to its count. Statuses with zero matching
            requests are omitted rather than included with a zero count.
        total: The total number of requests counted across all statuses.
    """

    counts: dict[RequestStatus, int]
    total: int


@dataclass(frozen=True, slots=True)
class VolumeByKey:
    """A count of requests grouped by an arbitrary string key (request
    type or department).

    Attributes:
        counts: A mapping from each distinct key value present in the
            queried data to its count.
        total: The total number of requests counted across all keys.
    """

    counts: dict[str, int]
    total: int


@dataclass(frozen=True, slots=True)
class ApprovalThroughput:
    """Aggregate approval-latency and completion-rate figures for a
    population of decided stages/requests.

    Attributes:
        average_decision_seconds: The average number of seconds between a
            stage's ``created_at`` and its ``decided_at``, across every
            decided (approved or rejected) stage considered, or ``None``
            if no decided stage was found in the queried population.
        completed_count: The number of requests that reached
            ``RequestStatus.COMPLETED``.
        rejected_count: The number of requests that reached
            ``RequestStatus.REJECTED``.
        completion_rate: ``completed_count / (completed_count +
            rejected_count)``, or ``None`` if neither occurred in the
            queried population (avoiding a division by zero).
    """

    average_decision_seconds: float | None
    completed_count: int
    rejected_count: int
    completion_rate: float | None


class AnalyticsRepository(BaseRepository[dict[str, Any]]):
    """Read-only aggregation queries supporting analytics dashboards.

    This repository's ``table_name`` is set to ``"requests"`` — the table
    most of these aggregates are over — purely so ``BaseRepository``'s own
    error messages can name it; every method here calls a Postgres
    function via ``self._client.rpc(...)`` directly rather than
    ``self._query()``, which is scoped to a single table and cannot
    express a ``group by`` or a cross-table join in one round trip.
    """

    table_name = "requests"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def count_requests_by_status(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> StatusBreakdown:
        """Count requests grouped by lifecycle status, within a company.

        Args:
            company_id: Restricts results to this company (tenant) —
                required, never optional, so a caller can never
                accidentally issue an unscoped, cross-tenant aggregate.
            department: Restrict to this department, if provided.
            request_type: Restrict to this request type, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.

        Returns:
            A ``StatusBreakdown`` summarizing the matching population.
        """
        response = self._execute(
            self._client.rpc(
                "analytics_count_requests_by_status",
                {
                    "p_company_id": str(company_id),
                    "p_department": department,
                    "p_request_type": request_type,
                    "p_created_after": _iso(created_after),
                    "p_created_before": _iso(created_before),
                },
            ),
            operation="count_requests_by_status",
        )
        rows = self._rows(response)
        counts = {RequestStatus(row["status"]): row["request_count"] for row in rows}
        return StatusBreakdown(counts=counts, total=sum(counts.values()))

    def count_requests_by_type(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> VolumeByKey:
        """Count requests grouped by request type, within a company.

        Args:
            company_id: Restricts results to this company (tenant) —
                required, never optional.
            department: Restrict to this department, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.

        Returns:
            A ``VolumeByKey`` summarizing request volume per type.
        """
        response = self._execute(
            self._client.rpc(
                "analytics_count_requests_by_type",
                {
                    "p_company_id": str(company_id),
                    "p_department": department,
                    "p_created_after": _iso(created_after),
                    "p_created_before": _iso(created_before),
                },
            ),
            operation="count_requests_by_type",
        )
        rows = self._rows(response)
        counts = {row["request_type"]: row["request_count"] for row in rows}
        return VolumeByKey(counts=counts, total=sum(counts.values()))

    def count_requests_by_department(
        self,
        *,
        company_id: UUID,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> VolumeByKey:
        """Count requests grouped by department, within a company.

        Requests with no department set are grouped under the key
        ``"unspecified"``.

        Args:
            company_id: Restricts results to this company (tenant) —
                required, never optional.
            request_type: Restrict to this request type, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.

        Returns:
            A ``VolumeByKey`` summarizing request volume per department.
        """
        response = self._execute(
            self._client.rpc(
                "analytics_count_requests_by_department",
                {
                    "p_company_id": str(company_id),
                    "p_request_type": request_type,
                    "p_created_after": _iso(created_after),
                    "p_created_before": _iso(created_before),
                },
            ),
            operation="count_requests_by_department",
        )
        rows = self._rows(response)
        counts = {row["department"]: row["request_count"] for row in rows}
        return VolumeByKey(counts=counts, total=sum(counts.values()))

    def approval_throughput(
        self,
        *,
        company_id: UUID,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> ApprovalThroughput:
        """Compute average decision latency and completion rate, within a company.

        Average decision latency is computed from ``workflow_stages``
        rows with a terminal status (``approved`` or ``rejected``),
        scoped to requests matching the given filters. Completion rate is
        computed from the ``requests`` table's own terminal statuses.

        Args:
            company_id: Restricts results to this company (tenant) —
                required, never optional.
            request_type: Restrict to this request type, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.

        Returns:
            An ``ApprovalThroughput`` summarizing the matching population.
        """
        response = self._execute(
            self._client.rpc(
                "analytics_approval_throughput",
                {
                    "p_company_id": str(company_id),
                    "p_request_type": request_type,
                    "p_created_after": _iso(created_after),
                    "p_created_before": _iso(created_before),
                },
            ),
            operation="approval_throughput",
        )
        # The function always returns exactly one row (it cross-joins two
        # single-row CTEs, never a `group by` that could yield zero) —
        # `_single_row` communicates that invariant and gives a clear
        # error if it's ever violated, rather than a bare `rows[0]`.
        row = self._single_row(response, identifier=company_id)
        completed_count = row["completed_count"]
        rejected_count = row["rejected_count"]
        completion_rate: float | None = None
        terminal_total = completed_count + rejected_count
        if terminal_total > 0:
            completion_rate = completed_count / terminal_total

        return ApprovalThroughput(
            average_decision_seconds=row["average_decision_seconds"],
            completed_count=completed_count,
            rejected_count=rejected_count,
            completion_rate=completion_rate,
        )
