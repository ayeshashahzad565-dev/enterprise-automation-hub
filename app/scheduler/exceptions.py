"""Custom exception hierarchy for the app.scheduler package.

Mirroring the pattern established in every finalized package, every
exception this package can raise is defined here, exactly once.
"""

from __future__ import annotations


class SchedulerError(Exception):
    """Base class for every exception raised by the app.scheduler package.

    Attributes:
        message: A human-readable description of the failure.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{self.__class__.__name__}(message={self.message!r})"


class JobRegistrationError(SchedulerError):
    """Raised when a job cannot be registered, unregistered, enabled, or
    disabled — most commonly a duplicate job name at registration time,
    or a reference to a job name that was never registered.

    Attributes:
        job_name: The job name involved in the failed operation.
    """

    def __init__(self, job_name: str, reason: str) -> None:
        super().__init__(f"Job registration error for '{job_name}': {reason}")
        self.job_name = job_name


class JobExecutionError(SchedulerError):
    """Raised when a scheduled job's execution fails in a way that could
    not be recovered from internally.

    Note: per this package's design, an ordinary job failure (a single
    execution raising) is caught by ``BaseJob.run`` and reported as a
    failed ``ExecutionResult`` rather than propagated as this exception
    — this exception is reserved for failures in the scheduling
    machinery itself (e.g. a job's callable could not be invoked at
    all).

    Attributes:
        job_name: The job that failed.
    """

    def __init__(self, job_name: str, reason: str) -> None:
        super().__init__(f"Execution error for job '{job_name}': {reason}")
        self.job_name = job_name


class JobAlreadyRunningError(SchedulerError):
    """Raised internally when a job's scheduled trigger fires while a
    previous execution of the same job is still in progress.

    This exception is caught immediately at the point it is raised (in
    ``SchedulerCoordinator``'s internal job runner) and never propagates
    to a caller; it exists to give the overlap-prevention control flow a
    precise, named condition rather than an ad hoc boolean check with no
    corresponding exception type.

    Attributes:
        job_name: The job that was still running.
    """

    def __init__(self, job_name: str) -> None:
        super().__init__(f"Job '{job_name}' is already running; skipping this execution.")
        self.job_name = job_name


class NotLeaderError(SchedulerError):
    """Raised internally when a job's scheduled trigger fires on an
    instance that does not currently hold Scheduler leadership.

    Caught immediately at the point it is raised (in
    ``SchedulerCoordinator``'s internal job runner) and never propagates
    to a caller — mirrors ``JobAlreadyRunningError``'s role, giving this
    skip condition a precise, named exception rather than an ad hoc
    boolean check with no corresponding type.

    Attributes:
        job_name: The job whose trigger fired.
    """

    def __init__(self, job_name: str) -> None:
        super().__init__(
            f"This instance is not the Scheduler leader; skipping job '{job_name}'."
        )
        self.job_name = job_name


class JobLockedElsewhereError(SchedulerError):
    """Raised internally when a job's distributed execution lock is
    already held — by another instance, since this instance's own
    ``threading.Lock`` for the same job was just successfully acquired.

    Caught immediately at the point it is raised, exactly like
    ``JobAlreadyRunningError`` and ``NotLeaderError``.

    Attributes:
        job_name: The job whose distributed lock was already held.
    """

    def __init__(self, job_name: str) -> None:
        super().__init__(
            f"Job '{job_name}' is already running on another instance; skipping this execution."
        )
        self.job_name = job_name


class SchedulerStartupError(SchedulerError):
    """Raised when the scheduler backend fails to start."""


class SchedulerShutdownError(SchedulerError):
    """Raised when the scheduler backend fails to shut down cleanly."""
