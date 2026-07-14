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
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.repositories.base_repository import BaseRepository
from app.database.repositories.request_repository import RequestStatus
from app.database.repositories.workflow_repository import StageStatus

logger = logging.getLogger(__name__)


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

    This repository's ``table_name`` is set to ``"requests"`` because that
    is the table most of its methods query directly; methods that need
    ``workflow_stages`` instead query it explicitly via ``self._client``
    rather than through ``self._query()``, which is scoped to
    ``table_name``.
    """

    table_name = "requests"

    def __init__(self, client: DatabaseClient) -> None:
        super().__init__(client)

    def count_requests_by_status(
        self,
        *,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> StatusBreakdown:
        """Count requests grouped by lifecycle status.

        Args:
            department: Restrict to this department, if provided.
            request_type: Restrict to this request type, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.

        Returns:
            A ``StatusBreakdown`` summarizing the matching population.
        """
        builder = self._query().select("status").is_("deleted_at", "null")
        builder = self._apply_common_filters(
            builder,
            department=department,
            request_type=request_type,
            created_after=created_after,
            created_before=created_before,
        )
        response = self._execute(builder, operation="count_requests_by_status")
        rows = self._rows(response)
        tally: Counter[str] = Counter(row["status"] for row in rows)
        counts = {RequestStatus(status): count for status, count in tally.items()}
        return StatusBreakdown(counts=counts, total=sum(counts.values()))

    def count_requests_by_type(
        self,
        *,
        department: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> VolumeByKey:
        """Count requests grouped by request type.

        Args:
            department: Restrict to this department, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.

        Returns:
            A ``VolumeByKey`` summarizing request volume per type.
        """
        builder = self._query().select("request_type").is_("deleted_at", "null")
        builder = self._apply_common_filters(
            builder,
            department=department,
            request_type=None,
            created_after=created_after,
            created_before=created_before,
        )
        response = self._execute(builder, operation="count_requests_by_type")
        rows = self._rows(response)
        tally: Counter[str] = Counter(row["request_type"] for row in rows)
        return VolumeByKey(counts=dict(tally), total=sum(tally.values()))

    def count_requests_by_department(
        self,
        *,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> VolumeByKey:
        """Count requests grouped by department.

        Requests with no department set are grouped under the key
        ``"unspecified"``.

        Args:
            request_type: Restrict to this request type, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.

        Returns:
            A ``VolumeByKey`` summarizing request volume per department.
        """
        builder = self._query().select("department").is_("deleted_at", "null")
        builder = self._apply_common_filters(
            builder,
            department=None,
            request_type=request_type,
            created_after=created_after,
            created_before=created_before,
        )
        response = self._execute(builder, operation="count_requests_by_department")
        rows = self._rows(response)
        tally: Counter[str] = Counter(row.get("department") or "unspecified" for row in rows)
        return VolumeByKey(counts=dict(tally), total=sum(tally.values()))

    def approval_throughput(
        self,
        *,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> ApprovalThroughput:
        """Compute average decision latency and completion rate.

        Average decision latency is computed from ``workflow_stages``
        rows with a terminal status (``approved`` or ``rejected``),
        scoped to requests matching the given filters. Completion rate is
        computed from the ``requests`` table's own terminal statuses.

        Args:
            request_type: Restrict to this request type, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.

        Returns:
            An ``ApprovalThroughput`` summarizing the matching population.
        """
        request_builder = self._query().select("id, status").is_("deleted_at", "null")
        request_builder = self._apply_common_filters(
            request_builder,
            department=None,
            request_type=request_type,
            created_after=created_after,
            created_before=created_before,
        )
        request_response = self._execute(request_builder, operation="approval_throughput_requests")
        request_rows = self._rows(request_response)
        request_ids = [row["id"] for row in request_rows]
        completed_count = sum(
            1 for row in request_rows if row["status"] == RequestStatus.COMPLETED.value
        )
        rejected_count = sum(
            1 for row in request_rows if row["status"] == RequestStatus.REJECTED.value
        )
        completion_rate: float | None = None
        terminal_total = completed_count + rejected_count
        if terminal_total > 0:
            completion_rate = completed_count / terminal_total

        average_decision_seconds: float | None = None
        if request_ids:
            stage_response = self._execute(
                self._client.table("workflow_stages")
                .select("created_at, decided_at, status")
                .in_("request_id", request_ids)
                .in_(
                    "status",
                    [StageStatus.APPROVED.value, StageStatus.REJECTED.value],
                ),
                operation="approval_throughput_stages",
            )
            stage_rows = self._rows(stage_response)
            durations: list[float] = []
            for row in stage_rows:
                if row.get("decided_at") is None:
                    continue
                created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                decided = datetime.fromisoformat(row["decided_at"].replace("Z", "+00:00"))
                durations.append((decided - created).total_seconds())
            if durations:
                average_decision_seconds = sum(durations) / len(durations)

        return ApprovalThroughput(
            average_decision_seconds=average_decision_seconds,
            completed_count=completed_count,
            rejected_count=rejected_count,
            completion_rate=completion_rate,
        )

    def _apply_common_filters(
        self,
        builder: Any,
        *,
        department: str | None,
        request_type: str | None,
        created_after: datetime | None,
        created_before: datetime | None,
    ) -> Any:
        """Apply the filter set shared by every aggregate method above.

        Args:
            builder: A query builder already scoped with a ``.select(...)``.
            department: Restrict to this department, if provided.
            request_type: Restrict to this request type, if provided.
            created_after: Restrict to rows created at or after this
                timestamp, if provided.
            created_before: Restrict to rows created at or before this
                timestamp, if provided.

        Returns:
            The same builder, with filters applied.
        """
        if department is not None:
            builder = builder.eq("department", department)
        if request_type is not None:
            builder = builder.eq("request_type", request_type)
        if created_after is not None:
            builder = builder.gte("created_at", created_after.isoformat())
        if created_before is not None:
            builder = builder.lte("created_at", created_before.isoformat())
        return builder