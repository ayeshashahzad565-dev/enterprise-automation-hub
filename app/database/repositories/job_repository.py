"""Repository for the ``jobs`` table.

Per migration ``0015_jobs``, ``jobs`` is the durable system of record for
the background job system: Redis (``app.jobs.redis_queue``) only ever
holds an ephemeral ``{"job_id", "priority"}`` pointer, this repository is
where a job's actual status and history live. Every status-transition
method below is a specific, named operation under optimistic-locking
control (``BaseRepository.update_with_optimistic_lock``) — there is no
generic "update a job" method, mirroring ``AuditRepository``'s "no
update/delete of any kind beyond the fixed named operations" discipline.

This repository performs no retry/backoff decision-making of its own
(that is ``app.jobs.worker``'s and ``app.jobs.backoff``'s responsibility,
per the Repository Layer's "persistence only, no business rules" rule) —
callers pass the already-computed ``attempts``/``error_history``/
``scheduled_for`` values in; this repository only knows how to write them
under a version check and translate failures.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.repositories.base_repository import (
    BaseRepository,
    Page,
    PagedResult,
    parse_datetime,
    parse_uuid,
)

logger = logging.getLogger(__name__)

#: The most error-history entries retained per job, oldest evicted first —
#: bounds ``error_history`` jsonb column growth for a job that is retried
#: many times.
_MAX_ERROR_HISTORY_ENTRIES = 20

#: The largest single batch this repository will read into memory for an
#: in-process aggregation (``count_dead_letter_by_queue``) rather than a
#: paginated query — this table is bounded operational state, not
#: tenant-scaled data, so this ceiling is generous.
_AGGREGATION_SCAN_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class JobRecord:
    """An immutable, persistence-level representation of one ``jobs`` row.

    Mirrors ``app.models.job.Job`` field-for-field; see that model's
    docstring for what each field means.
    """

    id: UUID
    task_type: str
    queue_name: str
    priority: str
    status: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    last_error: str | None
    error_history: list[dict[str, Any]]
    scheduled_for: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    locked_by: str | None
    request_id: UUID | None
    actor_id: UUID | None
    version: int
    created_at: datetime


def _map_job_row(row: dict[str, Any]) -> JobRecord:
    """Map a raw Supabase row dict into a ``JobRecord``."""
    return JobRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        task_type=row["task_type"],
        queue_name=row["queue_name"],
        priority=row["priority"],
        status=row["status"],
        payload=row["payload"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        last_error=row.get("last_error"),
        error_history=row.get("error_history") or [],
        scheduled_for=parse_datetime(row.get("scheduled_for")),
        started_at=parse_datetime(row.get("started_at")),
        finished_at=parse_datetime(row.get("finished_at")),
        locked_by=row.get("locked_by"),
        request_id=parse_uuid(row.get("request_id")),
        actor_id=parse_uuid(row.get("actor_id")),
        version=row["version"],
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


def _append_error_history(
    current: list[dict[str, Any]], *, attempt: int, error: str
) -> list[dict[str, Any]]:
    """Append one failure entry, keeping only the most recent entries.

    Args:
        current: The job's current ``error_history``, oldest first.
        attempt: The attempt number this failure occurred on.
        error: The failure's message.

    Returns:
        A new list with the entry appended, truncated to the most recent
        ``_MAX_ERROR_HISTORY_ENTRIES``.
    """
    entry = {"attempt": attempt, "error": error, "at": datetime.now(UTC).isoformat()}
    return [*current, entry][-_MAX_ERROR_HISTORY_ENTRIES:]


class JobRepository(BaseRepository[JobRecord]):
    """Persistence operations for the ``jobs`` table."""

    table_name = "jobs"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def get_by_id(self, job_id: UUID) -> JobRecord:  # type: ignore[override]
        """Fetch a single job by its id.

        Args:
            job_id: The job's ``id``.

        Returns:
            The matching ``JobRecord``.

        Raises:
            RecordNotFoundError: If no job with this id exists.
        """
        return super().get_by_id(job_id, mapper=_map_job_row)

    def create_job(
        self,
        *,
        task_type: str,
        queue_name: str,
        priority: str,
        payload: dict[str, Any],
        max_attempts: int,
        scheduled_for: datetime | None = None,
        request_id: UUID | None = None,
        actor_id: UUID | None = None,
    ) -> JobRecord:
        """Insert a new job row in ``queued`` status.

        Args:
            task_type: The handler this job dispatches to.
            queue_name: Which worker role should consume this job.
            priority: This job's priority tier value.
            payload: The handler-specific input.
            max_attempts: The attempt budget before dead-lettering.
            scheduled_for: When this job becomes eligible, if not
                immediately.
            request_id: The related request, if any.
            actor_id: The user whose action caused this job to be
                enqueued, if any.

        Returns:
            The newly created ``JobRecord``.
        """
        values: dict[str, Any] = {
            "task_type": task_type,
            "queue_name": queue_name,
            "priority": priority,
            "payload": payload,
            "max_attempts": max_attempts,
            "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
            "request_id": str(request_id) if request_id else None,
            "actor_id": str(actor_id) if actor_id else None,
        }
        return self.insert(values, mapper=_map_job_row)

    def mark_running(self, job_id: UUID, *, expected_version: int, locked_by: str) -> JobRecord:
        """Transition a job to ``running``, recording which worker owns it.

        Args:
            job_id: The job's ``id``.
            expected_version: The version last observed by the caller.
            locked_by: The worker hostname now processing this job.

        Returns:
            The updated ``JobRecord``.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` is stale.
        """
        return self.update_with_optimistic_lock(
            job_id,
            expected_version=expected_version,
            values={
                "status": "running",
                "started_at": datetime.now(UTC).isoformat(),
                "locked_by": locked_by,
            },
            mapper=_map_job_row,
        )

    def mark_succeeded(self, job_id: UUID, *, expected_version: int) -> JobRecord:
        """Transition a job to its terminal ``succeeded`` status.

        Args:
            job_id: The job's ``id``.
            expected_version: The version last observed by the caller.

        Returns:
            The updated ``JobRecord``.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` is stale.
        """
        return self.update_with_optimistic_lock(
            job_id,
            expected_version=expected_version,
            values={"status": "succeeded", "finished_at": datetime.now(UTC).isoformat()},
            mapper=_map_job_row,
        )

    def mark_failed_will_retry(
        self,
        job_id: UUID,
        *,
        expected_version: int,
        attempts: int,
        error: str,
        current_error_history: list[dict[str, Any]],
        next_attempt_scheduled_for: datetime,
    ) -> JobRecord:
        """Record a failed attempt and schedule the next retry.

        Args:
            job_id: The job's ``id``.
            expected_version: The version last observed by the caller.
            attempts: The attempt count after this failure (the caller's
                responsibility to increment — see module docstring).
            error: This attempt's failure message.
            current_error_history: The job's ``error_history`` as
                observed by the caller before this attempt.
            next_attempt_scheduled_for: When this job becomes eligible
                for its next attempt (``app.jobs.backoff``'s output).

        Returns:
            The updated ``JobRecord``, now ``status="retrying"``.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` is stale.
        """
        return self.update_with_optimistic_lock(
            job_id,
            expected_version=expected_version,
            values={
                "status": "retrying",
                "attempts": attempts,
                "last_error": error,
                "error_history": _append_error_history(
                    current_error_history, attempt=attempts, error=error
                ),
                "scheduled_for": next_attempt_scheduled_for.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
            },
            mapper=_map_job_row,
        )

    def mark_dead_lettered(
        self,
        job_id: UUID,
        *,
        expected_version: int,
        attempts: int,
        error: str,
        current_error_history: list[dict[str, Any]],
    ) -> JobRecord:
        """Transition a job to its terminal ``dead_lettered`` status.

        Args:
            job_id: The job's ``id``.
            expected_version: The version last observed by the caller.
            attempts: The attempt count after this final failure.
            error: The final attempt's failure message.
            current_error_history: The job's ``error_history`` as
                observed by the caller before this attempt.

        Returns:
            The updated ``JobRecord``.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` is stale.
        """
        return self.update_with_optimistic_lock(
            job_id,
            expected_version=expected_version,
            values={
                "status": "dead_lettered",
                "attempts": attempts,
                "last_error": error,
                "error_history": _append_error_history(
                    current_error_history, attempt=attempts, error=error
                ),
                "finished_at": datetime.now(UTC).isoformat(),
            },
            mapper=_map_job_row,
        )

    def retry_dead_letter(self, job_id: UUID, *, expected_version: int) -> JobRecord:
        """Reset a dead-lettered job back to ``queued`` with a fresh attempt budget.

        Called only from an explicit operator action
        (``POST /admin/jobs/{id}/retry``) — an operator retry implies the
        underlying cause is believed fixed, so this resets ``attempts``
        to zero rather than resuming a nearly-exhausted budget.

        Args:
            job_id: The job's ``id``.
            expected_version: The version last observed by the caller.

        Returns:
            The updated ``JobRecord``, now ``status="queued"``.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` is stale.
        """
        return self.update_with_optimistic_lock(
            job_id,
            expected_version=expected_version,
            values={
                "status": "queued",
                "attempts": 0,
                "last_error": None,
                "scheduled_for": None,
                "locked_by": None,
                "finished_at": None,
            },
            mapper=_map_job_row,
        )

    def list_jobs(
        self,
        *,
        status: str | None = None,
        task_type: str | None = None,
        queue_name: str | None = None,
        priority: str | None = None,
        page: Page = Page(),
    ) -> PagedResult[JobRecord]:
        """List jobs, newest first, filtered by any combination of fields.

        Args:
            status: Restrict to this status, if provided.
            task_type: Restrict to this task type, if provided.
            queue_name: Restrict to this queue, if provided.
            priority: Restrict to this priority, if provided.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching jobs.
        """
        builder = self._select("*", count="exact")
        if status is not None:
            builder = builder.eq("status", status)
        if task_type is not None:
            builder = builder.eq("task_type", task_type)
        if queue_name is not None:
            builder = builder.eq("queue_name", queue_name)
        if priority is not None:
            builder = builder.eq("priority", priority)
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_job_row)

    def list_dead_letter(
        self, *, task_type: str | None = None, page: Page = Page()
    ) -> PagedResult[JobRecord]:
        """List dead-lettered jobs, newest first.

        Args:
            task_type: Restrict to this task type, if provided.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of dead-lettered jobs.
        """
        return self.list_jobs(status="dead_lettered", task_type=task_type, page=page)

    def list_stuck_running(self, *, older_than: datetime) -> list[JobRecord]:
        """List jobs stuck in ``running`` since before ``older_than``.

        A job in this state has no corresponding Redis entry — its worker
        crashed (or was killed ungracefully) mid-execution. Used by
        ``app.scheduler.stuck_job_reaper_job.StuckJobReaperJob`` to
        recover them via the normal retry-or-dead-letter path.

        Args:
            older_than: Jobs whose ``started_at`` is before this instant
                are considered stuck.

        Returns:
            The matching jobs, oldest ``started_at`` first.
        """
        builder = (
            self._select("*")
            .eq("status", "running")
            .lt("started_at", older_than.isoformat())
            .order("started_at")
        )
        response = self._execute(builder, operation="list_stuck_running")
        return [_map_job_row(row) for row in self._rows(response)]

    def list_stuck_queued(self, *, older_than: datetime) -> list[JobRecord]:
        """List jobs stuck in ``queued`` since before ``older_than``.

        A ``queued`` job with no ``scheduled_for`` is expected to already
        be sitting in a Redis ready list — if it has been ``queued`` for
        longer than a worker should ever take to pick it up, the most
        likely explanation is that ``JobService.enqueue``'s Redis push
        failed *after* its Postgres insert already committed (a rarer,
        but real, sibling of ``list_stuck_running``'s "worker crashed
        mid-execution" case). Used by the same
        ``StuckJobReaperJob`` that recovers stuck-``running`` jobs.

        Args:
            older_than: Jobs whose ``created_at`` is before this instant
                are considered stuck.

        Returns:
            The matching jobs, oldest first.
        """
        builder = (
            self._select("*")
            .eq("status", "queued")
            .is_("scheduled_for", "null")
            .lt("created_at", older_than.isoformat())
            .order("created_at")
        )
        response = self._execute(builder, operation="list_stuck_queued")
        return [_map_job_row(row) for row in self._rows(response)]

    def count_dead_letter_by_queue(self) -> dict[str, int]:
        """Count dead-lettered jobs, grouped by ``queue_name``.

        Feeds the ``eah_job_dead_letter_count`` metrics gauge. Aggregates
        in-process over a single bounded scan rather than a PostgREST
        aggregate query (the installed postgrest-py client has no
        group-by support) — appropriate here since ``jobs`` is bounded
        operational state, not tenant-scaled data.

        Returns:
            A mapping of ``queue_name`` to the number of dead-lettered
            jobs currently in that queue.
        """
        builder = (
            self._select("queue_name")
            .eq("status", "dead_lettered")
            .range(0, _AGGREGATION_SCAN_LIMIT - 1)
        )
        response = self._execute(builder, operation="count_dead_letter_by_queue")
        return dict(Counter(row["queue_name"] for row in self._rows(response)))
