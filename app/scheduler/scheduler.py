"""The scheduler coordinator and its default APScheduler-backed implementation.

Per this package's design brief, ``SchedulerCoordinator`` is the single
entry point that registers jobs, starts and stops cleanly (including
graceful shutdown), executes jobs on their configured intervals,
prevents overlapping execution of the same job, and records execution
statistics — all expressed purely in terms of the ``SchedulerBackend``
protocol (``app.scheduler.interfaces``), never in terms of a specific
scheduling library. ``APSchedulerBackend``, defined in this same module,
is the concrete adapter satisfying that protocol using APScheduler — the
fixed scheduling technology named in the ADD and Deployment Guide — but
it is not the only implementation ``SchedulerCoordinator`` could be
given; substituting a different backend requires only a new class
satisfying ``SchedulerBackend``.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.scheduler.exceptions import (
    JobAlreadyRunningError,
    SchedulerShutdownError,
    SchedulerStartupError,
)
from app.scheduler.interfaces import ExecutionContext, JobStatistics
from app.scheduler.registry import JobRegistry
from app.utils.datetime_utils import utc_now
from app.utils.id_generator import generate_uuid_str

__all__ = ["APSchedulerBackend", "SchedulerCoordinator"]

logger = logging.getLogger(__name__)


class APSchedulerBackend:
    """A ``SchedulerBackend`` implementation backed by APScheduler's ``BackgroundScheduler``.

    This is the default, production backend for ``SchedulerCoordinator``,
    consistent with the fixed technology stack (ADD, Deployment Guide
    Section 13), running fully in-process alongside the rest of the
    application per the ADD's in-process Scheduler design.
    """

    def __init__(self) -> None:
        """Initialize the backend with a fresh, not-yet-started APScheduler instance."""
        self._scheduler = BackgroundScheduler()

    @property
    def is_running(self) -> bool:
        """Whether the underlying APScheduler instance is currently running."""
        return bool(self._scheduler.running)

    def add_job(self, job_id: str, func, *, interval_seconds: int) -> None:
        """Register a callable with APScheduler on a fixed interval trigger.

        Args:
            job_id: A unique identifier for this scheduled callable.
            func: The zero-argument callable to invoke on each tick.
            interval_seconds: The interval, in seconds, between
                invocations.
        """
        self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=interval_seconds),
            id=job_id,
            replace_existing=True,
            # max_instances=1 is APScheduler's own defense against
            # overlapping execution of the same job id; SchedulerCoordinator
            # additionally enforces this itself (per this package's design
            # brief) so the guarantee does not depend solely on this
            # backend-specific setting.
            max_instances=1,
            coalesce=True,
        )

    def remove_job(self, job_id: str) -> None:
        """Remove a previously added job from APScheduler.

        Args:
            job_id: The job identifier passed to ``add_job``.
        """
        try:
            self._scheduler.remove_job(job_id)
        except Exception:  # noqa: BLE001 - APScheduler raises JobLookupError; absence is not an error here
            logger.debug("No scheduled job '%s' to remove.", job_id, extra={"job_name": job_id})

    def get_next_run_time(self, job_id: str) -> datetime | None:
        """Return APScheduler's recorded next run time for a job.

        Args:
            job_id: The job identifier.

        Returns:
            The next scheduled run time, or ``None`` if the job is not
            currently scheduled.
        """
        job = self._scheduler.get_job(job_id)
        return job.next_run_time if job is not None else None

    def start(self) -> None:
        """Start APScheduler's background thread.

        Raises:
            Exception: Propagated from APScheduler on failure;
                ``SchedulerCoordinator`` translates this into
                ``SchedulerStartupError``.
        """
        self._scheduler.start()

    def shutdown(self, *, wait: bool) -> None:
        """Stop APScheduler's background thread.

        Args:
            wait: Whether to block until any currently executing job
                completes.

        Raises:
            Exception: Propagated from APScheduler on failure;
                ``SchedulerCoordinator`` translates this into
                ``SchedulerShutdownError``.
        """
        self._scheduler.shutdown(wait=wait)


class SchedulerCoordinator:
    """Coordinates job registration, execution, overlap prevention, and statistics.

    This class depends only on ``SchedulerBackend`` and ``JobRegistry``,
    both injected, making it fully substitutable and independently unit
    testable with fake implementations of either (TSD Section 3.1).
    """

    def __init__(self, *, backend, registry: JobRegistry) -> None:
        """Initialize the coordinator with its injected collaborators.

        Args:
            backend: Any object satisfying the ``SchedulerBackend``
                protocol.
            registry: The job registry to schedule jobs from.
        """
        self._backend = backend
        self._registry = registry
        self._stats: dict[str, JobStatistics] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._stats_lock = threading.RLock()
        self._logger = logging.getLogger(f"{__name__}.SchedulerCoordinator")

    @property
    def is_running(self) -> bool:
        """Whether the backend is currently started."""
        return self._backend.is_running

    def register_job(
        self, job, *, interval_seconds: int | None = None, enabled: bool = True
    ) -> None:
        """Register a job with this coordinator's registry.

        If the backend is already running, the job is also immediately
        scheduled; otherwise it will be scheduled the next time
        ``start`` is called.

        Args:
            job: The job to register.
            interval_seconds: The interval to schedule this job at.
                Defaults to ``job.interval_seconds`` when ``None``.
            enabled: Whether the job starts enabled.

        Raises:
            JobRegistrationError: If a job with this name is already
                registered.
        """
        self._registry.register(job, interval_seconds=interval_seconds, enabled=enabled)
        with self._stats_lock:
            self._stats[job.name] = JobStatistics(job_name=job.name)
            self._locks[job.name] = threading.Lock()

        if self.is_running and enabled:
            registration = self._registry.get_registration(job.name)
            self._backend.add_job(
                job.name,
                self._make_runner(job.name),
                interval_seconds=registration.interval_seconds,
            )

    def start(self) -> None:
        """Schedule every enabled registered job and start the backend.

        Raises:
            SchedulerStartupError: If the backend fails to start.
        """
        for registration in self._registry.list_jobs(enabled_only=True):
            self._backend.add_job(
                registration.job.name,
                self._make_runner(registration.job.name),
                interval_seconds=registration.interval_seconds,
            )

        try:
            self._backend.start()
        except Exception as exc:  # noqa: BLE001 - translated into a typed error below
            self._logger.error("Scheduler backend failed to start: %s", exc, exc_info=exc)
            raise SchedulerStartupError(str(exc)) from exc

        self._logger.info(
            "Scheduler started with %d enabled job(s).",
            len(self._registry.list_jobs(enabled_only=True)),
        )

    def stop(self, *, wait: bool = True) -> None:
        """Stop the backend, optionally waiting for in-progress executions.

        Args:
            wait: Whether to block until any currently executing job
                completes before returning (a graceful shutdown).

        Raises:
            SchedulerShutdownError: If the backend fails to shut down
                cleanly.
        """
        try:
            self._backend.shutdown(wait=wait)
        except Exception as exc:  # noqa: BLE001 - translated into a typed error below
            self._logger.error("Scheduler backend failed to shut down: %s", exc, exc_info=exc)
            raise SchedulerShutdownError(str(exc)) from exc

        self._logger.info("Scheduler stopped (graceful=%s).", wait)

    def get_statistics(self, job_name: str) -> JobStatistics | None:
        """Return the current statistics for a single job.

        Args:
            job_name: The job's name.

        Returns:
            A snapshot copy of the job's ``JobStatistics``, with
            ``next_run_time`` refreshed from the backend, or ``None`` if
            no job with this name is registered.
        """
        with self._stats_lock:
            stats = self._stats.get(job_name)
            if stats is None:
                return None
            return self._snapshot_with_next_run_time(stats)

    def get_all_statistics(self) -> dict[str, JobStatistics]:
        """Return the current statistics for every registered job.

        Returns:
            A mapping from job name to a snapshot copy of its
            ``JobStatistics``, each with ``next_run_time`` refreshed from
            the backend.
        """
        with self._stats_lock:
            return {
                name: self._snapshot_with_next_run_time(stats)
                for name, stats in self._stats.items()
            }

    def _snapshot_with_next_run_time(self, stats: JobStatistics) -> JobStatistics:
        """Return a copy of a job's statistics with ``next_run_time`` refreshed.

        Args:
            stats: The live, internally mutated statistics record.

        Returns:
            A detached copy safe for a caller to hold without risk of it
            changing underneath them.
        """
        next_run_time = self._backend.get_next_run_time(stats.job_name)
        return JobStatistics(
            job_name=stats.job_name,
            run_count=stats.run_count,
            success_count=stats.success_count,
            failure_count=stats.failure_count,
            skipped_overlap_count=stats.skipped_overlap_count,
            currently_running=stats.currently_running,
            last_started_at=stats.last_started_at,
            last_finished_at=stats.last_finished_at,
            last_duration_seconds=stats.last_duration_seconds,
            last_error=stats.last_error,
            next_run_time=next_run_time,
        )

    def _make_runner(self, job_name: str):
        """Build the zero-argument callable the backend will invoke on each tick.

        Args:
            job_name: The job's name, used to look up the job and its
                lock/statistics at invocation time (rather than at
                registration time), so that a job re-registered after
                being unregistered is always invoked correctly.

        Returns:
            A zero-argument callable suitable for ``SchedulerBackend.add_job``.
        """

        def _run() -> None:
            lock = self._locks.get(job_name)
            if lock is None:
                self._logger.warning(
                    "No lock found for job '%s'; it may have been unregistered.",
                    job_name,
                    extra={"job_name": job_name},
                )
                return

            acquired = lock.acquire(blocking=False)
            if not acquired:
                try:
                    raise JobAlreadyRunningError(job_name)
                except JobAlreadyRunningError as exc:
                    self._logger.warning(str(exc), extra={"job_name": job_name})
                    with self._stats_lock:
                        stats = self._stats.get(job_name)
                        if stats is not None:
                            stats.skipped_overlap_count += 1
                    return

            try:
                with self._stats_lock:
                    stats = self._stats[job_name]
                    stats.currently_running = True

                try:
                    job = self._registry.get(job_name)
                except Exception:  # noqa: BLE001 - job was unregistered between tick and invocation
                    self._logger.warning(
                        "Job '%s' fired but is no longer registered; skipping.",
                        job_name,
                        extra={"job_name": job_name},
                    )
                    return

                context = ExecutionContext(
                    job_name=job_name, scheduled_time=utc_now(), run_id=generate_uuid_str()
                )
                result = job.run(context)

                with self._stats_lock:
                    stats = self._stats[job_name]
                    stats.run_count += 1
                    if result.success:
                        stats.success_count += 1
                        stats.last_error = None
                    else:
                        stats.failure_count += 1
                        stats.last_error = result.error_message
                    stats.last_started_at = result.started_at
                    stats.last_finished_at = result.finished_at
                    stats.last_duration_seconds = result.duration_seconds
            finally:
                with self._stats_lock:
                    stats = self._stats.get(job_name)
                    if stats is not None:
                        stats.currently_running = False
                lock.release()

        return _run