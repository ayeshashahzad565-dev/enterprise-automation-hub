"""The Stuck Job Reaper — recovers orphaned rows in the ``jobs`` table.

Closes a gap the job system would otherwise have: a job's Redis footprint
(``app.jobs.redis_queue``) is the only thing that ever causes a worker to
pick it up, but Redis holds no independent history — if a worker crashes
mid-execution (its process is killed, its container is OOM-killed, the
host reboots), the corresponding Postgres row is left stuck
``status="running"`` forever, with no Redis entry left to ever revive it.
A rarer sibling case: ``JobService.enqueue``'s Postgres insert can commit
while its immediately-following Redis push fails (see that method's own
docstring), leaving a row stuck ``status="queued"`` with nothing in Redis
to promote or dequeue it either.

This job finds both kinds of orphan (``JobRepository.list_stuck_running``
/ ``.list_stuck_queued``, both scoped by an age threshold — a job only
just marked ``running``/``queued`` moments ago is not stuck, merely
in-flight) and recovers each one through the exact same retry-or-dead-
letter path a worker itself uses on an ordinary handler failure
(``app.jobs.backoff``, ``JobRepository.mark_failed_will_retry`` /
``.mark_dead_lettered``, a push onto the delayed set) — from the job's
own perspective, "its worker vanished" and "its handler raised" are
indistinguishable failure modes.

Only registered when Redis is configured (``app.bootstrap``) — with no
Redis, the job system's only active path is
``app.jobs.job_service.SynchronousJobDispatcher``, which never leaves a
row in this table at all (see that class's docstring), so there is
nothing for this job to ever find.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from app.database.exceptions import ConcurrentUpdateError
from app.database.repositories.job_repository import JobRecord, JobRepository
from app.jobs import backoff
from app.jobs.redis_queue import RedisJobQueue
from app.models.enums import JobPriority
from app.scheduler.interfaces import ExecutionContext
from app.scheduler.jobs import BaseJob, run_over_items
from app.utils.datetime_utils import utc_now

__all__ = ["StuckJobReaperJob"]

_RECOVERY_ERROR_MESSAGE = "Recovered by StuckJobReaperJob: job made no progress within the stuck threshold."


class StuckJobReaperJob(BaseJob):
    """Recovers ``jobs`` rows stuck ``running``/``queued`` with no live Redis entry."""

    def __init__(
        self,
        *,
        job_repository: JobRepository,
        redis_queue: RedisJobQueue,
        threshold_minutes: int = 10,
        interval_seconds: int = 300,
    ) -> None:
        """Initialize the job with its injected collaborators.

        Args:
            job_repository: The durable system of record to query and
                recover rows in.
            redis_queue: Used to push a recovered-and-retried job back
                onto its delayed set.
            threshold_minutes: How long a job may sit ``running`` or
                ``queued`` before being considered stuck.
            interval_seconds: The default interval this job runs at.
        """
        self._job_repository = job_repository
        self._redis_queue = redis_queue
        self._threshold_minutes = threshold_minutes
        self._interval_seconds = interval_seconds
        self._logger = logging.getLogger(f"{__name__}.StuckJobReaperJob")

    @property
    def name(self) -> str:
        """This job's stable identifier, ``"stuck_job_reaper"``."""
        return "stuck_job_reaper"

    @property
    def interval_seconds(self) -> int:
        """The configured interval, in seconds, this job runs at."""
        return self._interval_seconds

    def _execute(self, context: ExecutionContext) -> tuple[int, int]:
        """Find and recover every currently orphaned job.

        Args:
            context: The execution context for this run.

        Returns:
            A tuple of ``(items_processed, items_failed)``.
        """
        cutoff = utc_now() - timedelta(minutes=self._threshold_minutes)
        stuck = [
            *self._job_repository.list_stuck_running(older_than=cutoff),
            *self._job_repository.list_stuck_queued(older_than=cutoff),
        ]
        result = run_over_items(stuck, self._recover, job_logger=self._logger)
        return result.processed_count, result.failed_count

    def _recover(self, job: JobRecord) -> None:
        """Recover a single orphaned job via the ordinary retry-or-dead-letter path.

        Args:
            job: The stuck job.
        """
        new_attempts = job.attempts + 1
        try:
            if new_attempts < job.max_attempts:
                delay = backoff.compute_delay_seconds(new_attempts)
                next_attempt_at = utc_now() + timedelta(seconds=delay)
                self._job_repository.mark_failed_will_retry(
                    job.id,
                    expected_version=job.version,
                    attempts=new_attempts,
                    error=_RECOVERY_ERROR_MESSAGE,
                    current_error_history=job.error_history,
                    next_attempt_scheduled_for=next_attempt_at,
                )
                self._redis_queue.push_delayed(
                    queue_name=job.queue_name,
                    priority=JobPriority(job.priority),
                    job_id=str(job.id),
                    ready_at=next_attempt_at,
                )
            else:
                self._job_repository.mark_dead_lettered(
                    job.id,
                    expected_version=job.version,
                    attempts=new_attempts,
                    error=_RECOVERY_ERROR_MESSAGE,
                    current_error_history=job.error_history,
                )
        except ConcurrentUpdateError:
            # The job was not actually orphaned — a live worker
            # transitioned it between this job's discovery query and this
            # recovery attempt. Expected under normal operation, not a
            # failure; matches EscalationJob's identical race-tolerance
            # rationale for ApprovalService.escalate_stage's own
            # optimistic-lock conflicts.
            pass
