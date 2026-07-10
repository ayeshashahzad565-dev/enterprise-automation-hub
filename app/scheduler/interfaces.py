"""Protocols, ABCs, and shared value objects for app.scheduler.

Per this package's design brief, this module defines the abstractions
that keep ``SchedulerCoordinator`` independent of any specific
scheduling library: ``SchedulerBackend`` is the only surface a concrete
scheduling library's adapter must satisfy, and ``ScheduledJob`` is the
only surface a concrete job class must satisfy. ``ExecutionContext`` and
``ExecutionResult`` are the plain, immutable data objects passed between
a job and its caller on every run; they are defined as frozen
dataclasses here (rather than as Protocols) because they carry no
behavior of their own — Protocols would add no value in the same way
they do for the callable-shaped abstractions and would only obscure the
one thing that matters about them, which is their fixed field shape.

``JobStatistics`` and ``SchedulerStatisticsProvider`` are also defined
here, since they are the shared contract between ``SchedulerCoordinator``
(the producer of execution statistics) and ``HealthCheckJob`` (a
consumer of them) — keeping this contract in ``interfaces.py`` rather
than in ``scheduler.py`` or ``health_check_job.py`` avoids either module
depending on the other's internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping, Protocol, runtime_checkable

__all__ = [
    "ExecutionContext",
    "ExecutionResult",
    "ScheduledJob",
    "SchedulerBackend",
    "JobRegistryProtocol",
    "JobStatistics",
    "SchedulerStatisticsProvider",
]


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """The context passed to a job on a single execution.

    Attributes:
        job_name: The name of the job being executed.
        scheduled_time: The timestamp this execution began.
        run_id: A short, unique identifier for this specific execution,
            useful for correlating structured log lines belonging to the
            same run.
    """

    job_name: str
    scheduled_time: datetime
    run_id: str


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """The outcome of a single job execution.

    A job's ``run`` method always returns one of these — even when the
    job's own logic fails internally — so that ``SchedulerCoordinator``
    never needs to catch an exception escaping a job in the ordinary
    case; a job reports its own failure as data, not as a raised
    exception.

    Attributes:
        job_name: The name of the job that produced this result.
        started_at: When this execution began.
        finished_at: When this execution ended.
        success: Whether the execution completed without a job-level
            failure. Per-item failures within a batch (e.g. one overdue
            stage out of twenty failing to escalate) do not, by
            themselves, make ``success`` ``False`` — they are instead
            reflected in ``items_failed``; ``success`` is ``False`` only
            when the job's overall execution could not complete (for
            example, the initial discovery query itself failed).
        items_processed: The number of individual work items (e.g.
            overdue stages, stages needing a reminder) successfully
            processed during this execution.
        items_failed: The number of individual work items that failed
            during this execution, without aborting the remaining items.
        error_message: A human-readable description of the job-level
            failure, populated only when ``success`` is ``False``.
    """

    job_name: str
    started_at: datetime
    finished_at: datetime
    success: bool
    items_processed: int = 0
    items_failed: int = 0
    error_message: str | None = None

    @property
    def duration_seconds(self) -> float:
        """The execution's wall-clock duration, in seconds."""
        return (self.finished_at - self.started_at).total_seconds()


@runtime_checkable
class ScheduledJob(Protocol):
    """Structural interface every scheduled job in this package satisfies."""

    @property
    def name(self) -> str:
        """A short, stable, unique identifier for this job."""
        ...

    @property
    def interval_seconds(self) -> int:
        """The interval, in seconds, this job should be executed at."""
        ...

    def run(self, context: ExecutionContext) -> ExecutionResult:
        """Execute this job once.

        Args:
            context: The execution context for this run.

        Returns:
            The outcome of this execution. Implementations are expected
            never to raise for an ordinary job-logic failure — such
            failures are reported via a returned ``ExecutionResult`` with
            ``success=False`` instead, per this protocol's documented
            contract.
        """
        ...


@runtime_checkable
class SchedulerBackend(Protocol):
    """Structural interface for a pluggable scheduling library adapter.

    ``SchedulerCoordinator`` depends only on this protocol, never on a
    specific scheduling library's own API, which is what makes the
    coordinator scheduler-library agnostic: substituting APScheduler for
    a different backend means writing a new class satisfying this
    protocol, with no change to ``SchedulerCoordinator`` itself.
    """

    @property
    def is_running(self) -> bool:
        """Whether the backend is currently started and dispatching jobs."""
        ...

    def add_job(self, job_id: str, func: Callable[[], None], *, interval_seconds: int) -> None:
        """Register a callable to be invoked on a fixed interval.

        Args:
            job_id: A unique identifier for this scheduled callable.
            func: A zero-argument callable to invoke on each tick. The
                backend is expected to invoke this callable directly; it
                is the caller's responsibility (in practice,
                ``SchedulerCoordinator``) to ensure ``func`` itself never
                raises, since backend implementations are not required
                to handle an escaping exception gracefully.
            interval_seconds: The interval, in seconds, between
                invocations.
        """
        ...

    def remove_job(self, job_id: str) -> None:
        """Remove a previously added scheduled callable.

        Args:
            job_id: The identifier passed to ``add_job``. Removing a job
                id that is not currently scheduled is not an error.
        """
        ...

    def get_next_run_time(self, job_id: str) -> datetime | None:
        """Return the next scheduled invocation time for a job.

        Args:
            job_id: The job identifier.

        Returns:
            The next scheduled run time, or ``None`` if the job is not
            currently scheduled or the backend cannot determine one.
        """
        ...

    def start(self) -> None:
        """Start dispatching scheduled callables.

        Raises:
            Exception: Implementations may raise any exception on
                failure; ``SchedulerCoordinator`` is responsible for
                translating it into ``SchedulerStartupError``.
        """
        ...

    def shutdown(self, *, wait: bool) -> None:
        """Stop dispatching scheduled callables.

        Args:
            wait: Whether to block until any currently executing
                callable completes before returning (a graceful
                shutdown) or return immediately.

        Raises:
            Exception: Implementations may raise any exception on
                failure; ``SchedulerCoordinator`` is responsible for
                translating it into ``SchedulerShutdownError``.
        """
        ...


@runtime_checkable
class JobRegistryProtocol(Protocol):
    """Structural interface a job registry satisfies.

    Defined here per this package's design brief; ``registry.JobRegistry``
    is this package's concrete implementation and satisfies this protocol
    structurally, with no explicit inheritance required.
    """

    def register(
        self, job: ScheduledJob, *, interval_seconds: int | None = None, enabled: bool = True
    ) -> None:
        """Register a new job.

        Args:
            job: The job to register.
            interval_seconds: The interval to schedule this job at.
                Defaults to ``job.interval_seconds`` when ``None``.
            enabled: Whether the job starts enabled.

        Raises:
            JobRegistrationError: If a job with this name is already
                registered.
        """
        ...

    def unregister(self, job_name: str) -> None:
        """Remove a registered job.

        Args:
            job_name: The job's name.

        Raises:
            JobRegistrationError: If no job with this name is registered.
        """
        ...

    def enable(self, job_name: str) -> None:
        """Enable a registered job.

        Args:
            job_name: The job's name.

        Raises:
            JobRegistrationError: If no job with this name is registered.
        """
        ...

    def disable(self, job_name: str) -> None:
        """Disable a registered job.

        Args:
            job_name: The job's name.

        Raises:
            JobRegistrationError: If no job with this name is registered.
        """
        ...

    def get(self, job_name: str) -> ScheduledJob:
        """Retrieve a registered job by name.

        Args:
            job_name: The job's name.

        Returns:
            The registered ``ScheduledJob``.

        Raises:
            JobRegistrationError: If no job with this name is registered.
        """
        ...

    def is_registered(self, job_name: str) -> bool:
        """Return whether a job with this name is currently registered.

        Args:
            job_name: The job's name.

        Returns:
            ``True`` if registered, ``False`` otherwise.
        """
        ...


@dataclass(slots=True)
class JobStatistics:
    """Execution statistics tracked for a single registered job.

    Instances are mutated in place by ``SchedulerCoordinator`` as
    executions occur; callers reading statistics (in particular,
    ``HealthCheckJob``) should treat a retrieved instance as a snapshot
    at the moment it was read, not a live view.

    Attributes:
        job_name: The job this statistics record belongs to.
        run_count: The total number of times this job has been executed.
        success_count: The number of executions that completed with
            ``ExecutionResult.success = True``.
        failure_count: The number of executions that completed with
            ``ExecutionResult.success = False``.
        skipped_overlap_count: The number of times this job's trigger
            fired while a previous execution was still running, and was
            therefore skipped.
        currently_running: Whether an execution of this job is in
            progress right now.
        last_started_at: The start time of the most recent execution.
        last_finished_at: The end time of the most recent execution.
        last_duration_seconds: The duration of the most recent execution.
        last_error: The error message of the most recent failed
            execution, if any.
        next_run_time: The next scheduled execution time, as reported by
            the scheduler backend.
    """

    job_name: str
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    skipped_overlap_count: int = 0
    currently_running: bool = False
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_duration_seconds: float | None = None
    last_error: str | None = None
    next_run_time: datetime | None = None


@runtime_checkable
class SchedulerStatisticsProvider(Protocol):
    """Structural interface exposing execution statistics for every registered job.

    ``SchedulerCoordinator`` satisfies this protocol; ``HealthCheckJob``
    depends only on this narrow protocol, rather than on
    ``SchedulerCoordinator`` directly, avoiding a circular dependency
    between ``scheduler.py`` and ``health_check_job.py``.
    """

    @property
    def is_running(self) -> bool:
        """Whether the scheduler backend is currently running."""
        ...

    def get_statistics(self, job_name: str) -> JobStatistics | None:
        """Return the current statistics for a single job.

        Args:
            job_name: The job's name.

        Returns:
            The job's current ``JobStatistics``, or ``None`` if no job
            with this name is registered.
        """
        ...

    def get_all_statistics(self) -> Mapping[str, JobStatistics]:
        """Return the current statistics for every registered job.

        Returns:
            A mapping from job name to its current ``JobStatistics``.
        """
        ...