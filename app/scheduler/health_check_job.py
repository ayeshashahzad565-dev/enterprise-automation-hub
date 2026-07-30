"""The Scheduler Health Check job.

Per this package's design brief, this job collects scheduler health
information — last execution time, next scheduled run, execution
duration, success/failure count, and currently-running state — for every
registered job, and makes it available in memory for a future health
endpoint or operator tool to read. It performs no persistence and no UI
rendering of any kind.
"""

from __future__ import annotations

import logging
import threading

from app.scheduler.interfaces import (
    ExecutionContext,
    ExecutionResult,
    JobStatistics,
    SchedulerStatisticsProvider,
)
from app.utils.datetime_utils import utc_now

__all__ = ["JobHealthStatus", "SchedulerHealthSnapshot", "HealthCheckJob"]


class JobHealthStatus:
    """A single job's health status, derived from its ``JobStatistics``.

    This is a thin, read-only view over ``JobStatistics`` — it exists
    separately so that the health snapshot's shape is decoupled from the
    coordinator's own internal statistics representation, even though,
    in the current implementation, every field is a direct copy.
    """

    __slots__ = (
        "job_name",
        "last_execution_time",
        "next_run_time",
        "last_duration_seconds",
        "success_count",
        "failure_count",
        "currently_running",
    )

    def __init__(self, statistics: JobStatistics) -> None:
        """Construct a health status view from a job's statistics.

        Args:
            statistics: The job's current ``JobStatistics``.
        """
        self.job_name = statistics.job_name
        self.last_execution_time = statistics.last_finished_at
        self.next_run_time = statistics.next_run_time
        self.last_duration_seconds = statistics.last_duration_seconds
        self.success_count = statistics.success_count
        self.failure_count = statistics.failure_count
        self.currently_running = statistics.currently_running

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"JobHealthStatus(job_name={self.job_name!r}, "
            f"currently_running={self.currently_running}, "
            f"success_count={self.success_count}, failure_count={self.failure_count})"
        )


class SchedulerHealthSnapshot:
    """A point-in-time snapshot of every registered job's health.

    Attributes:
        collected_at: When this snapshot was assembled.
        scheduler_running: Whether the scheduler backend is currently
            running at all.
        jobs: The health status of every job known to the statistics
            provider at the time this snapshot was built.
    """

    __slots__ = ("collected_at", "scheduler_running", "jobs")

    def __init__(self, *, scheduler_running: bool, jobs: tuple[JobHealthStatus, ...]) -> None:
        """Construct a snapshot.

        Args:
            scheduler_running: Whether the scheduler backend is running.
            jobs: The health status of every known job.
        """
        self.collected_at = utc_now()
        self.scheduler_running = scheduler_running
        self.jobs = jobs

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"SchedulerHealthSnapshot(collected_at={self.collected_at!r}, "
            f"scheduler_running={self.scheduler_running}, job_count={len(self.jobs)})"
        )


class HealthCheckJob:
    """Periodically collects and logs a scheduler-wide health snapshot.

    Unlike ``EscalationJob`` and ``ReminderJob``, this job depends on no
    repository and performs no database access at all — it only reads
    the in-memory statistics ``SchedulerCoordinator`` already tracks
    (via the narrow ``SchedulerStatisticsProvider`` protocol, avoiding a
    direct dependency on the coordinator class itself).

    This class implements the ``ScheduledJob`` protocol directly, rather
    than extending ``BaseJob``: its "processing" is a single, atomic
    snapshot construction with no natural notion of individual work
    items to process-and-continue-past, so ``BaseJob``'s
    ``(items_processed, items_failed)`` batch-oriented contract does not
    fit as cleanly here as a direct, minimal implementation does.
    """

    def __init__(self, *, statistics_provider: SchedulerStatisticsProvider) -> None:
        """Initialize the job with an injected statistics provider.

        Args:
            statistics_provider: Any object satisfying the
                ``SchedulerStatisticsProvider`` protocol — in production,
                the same ``SchedulerCoordinator`` this job is itself
                registered with.
        """
        self._statistics_provider = statistics_provider
        self._latest_snapshot: SchedulerHealthSnapshot | None = None
        self._snapshot_lock = threading.Lock()
        self._logger = logging.getLogger(f"{__name__}.HealthCheckJob")

    @property
    def name(self) -> str:
        """This job's stable identifier, ``"scheduler_health_check"``."""
        return "scheduler_health_check"

    @property
    def interval_seconds(self) -> int:
        """The interval, in seconds, this job runs at.

        Fixed at 5 minutes: frequent enough to give a timely picture of
        scheduler health without adding meaningful overhead, since this
        job performs no I/O beyond reading already-in-memory statistics.
        """
        return 300

    def run(self, context: ExecutionContext) -> ExecutionResult:
        """Collect and log a fresh scheduler health snapshot.

        Args:
            context: The execution context for this run.

        Returns:
            An ``ExecutionResult`` describing this execution. This
            method never raises: any failure while assembling the
            snapshot is caught and reported as a failed result, matching
            the same contract ``BaseJob.run`` provides for the other
            jobs in this package.
        """
        started_at = utc_now()
        try:
            snapshot = self.collect_snapshot()
        except Exception as exc:  # noqa: BLE001 - translated into a failed ExecutionResult
            finished_at = utc_now()
            self._logger.error(
                "Health check failed: %s", exc, exc_info=exc, extra={"job_name": self.name}
            )
            return ExecutionResult(
                job_name=self.name,
                started_at=started_at,
                finished_at=finished_at,
                success=False,
                error_message=str(exc),
            )

        finished_at = utc_now()
        self._logger.info(
            "Scheduler health snapshot: running=%s, jobs=%d",
            snapshot.scheduler_running,
            len(snapshot.jobs),
            extra={
                "job_name": self.name,
                "scheduler_running": snapshot.scheduler_running,
                "job_count": len(snapshot.jobs),
            },
        )
        for job_status in snapshot.jobs:
            self._logger.debug(
                "Job health: name=%s, currently_running=%s, success_count=%d, "
                "failure_count=%d, last_duration=%s, next_run_time=%s",
                job_status.job_name,
                job_status.currently_running,
                job_status.success_count,
                job_status.failure_count,
                job_status.last_duration_seconds,
                job_status.next_run_time,
                extra={"job_name": job_status.job_name},
            )

        return ExecutionResult(
            job_name=self.name,
            started_at=started_at,
            finished_at=finished_at,
            success=True,
            items_processed=len(snapshot.jobs),
            items_failed=0,
        )

    def collect_snapshot(self) -> SchedulerHealthSnapshot:
        """Assemble a fresh health snapshot from the statistics provider.

        Returns:
            The assembled ``SchedulerHealthSnapshot``. Also stored
            internally, retrievable via ``get_latest_snapshot`` without
            waiting for this job's next scheduled run.
        """
        all_stats = self._statistics_provider.get_all_statistics()
        job_statuses = tuple(JobHealthStatus(stats) for stats in all_stats.values())
        snapshot = SchedulerHealthSnapshot(
            scheduler_running=self._statistics_provider.is_running, jobs=job_statuses
        )
        with self._snapshot_lock:
            self._latest_snapshot = snapshot
        return snapshot

    def get_latest_snapshot(self) -> SchedulerHealthSnapshot | None:
        """Return the most recently collected snapshot, if any.

        Returns:
            The latest ``SchedulerHealthSnapshot``, or ``None`` if this
            job has not yet executed.
        """
        with self._snapshot_lock:
            return self._latest_snapshot
