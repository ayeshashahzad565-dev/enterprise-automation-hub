"""Job registration and lifecycle management.

Per this package's design brief, ``JobRegistry`` is responsible for
registering jobs, enabling/disabling them, retrieving them, and
validating that job names are unique. It holds no execution logic of its
own — ``SchedulerCoordinator`` consults this registry to determine which
jobs to schedule and at what interval, but actually invoking a job is
entirely the coordinator's responsibility.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from app.scheduler.exceptions import JobRegistrationError
from app.scheduler.interfaces import ScheduledJob

__all__ = ["JobRegistration", "JobRegistry"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class JobRegistration:
    """A single registered job, together with its scheduling metadata.

    Attributes:
        job: The registered job instance.
        interval_seconds: The interval, in seconds, this job is
            scheduled at.
        enabled: Whether this job is currently eligible to run.
    """

    job: ScheduledJob
    interval_seconds: int
    enabled: bool


class JobRegistry:
    """A thread-safe registry of scheduled jobs.

    This class performs no scheduling itself; it is a pure bookkeeping
    component that ``SchedulerCoordinator`` depends on via dependency
    injection.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._registrations: dict[str, JobRegistration] = {}
        self._lock = threading.RLock()
        self._logger = logging.getLogger(f"{__name__}.JobRegistry")

    def register(
        self, job: ScheduledJob, *, interval_seconds: int | None = None, enabled: bool = True
    ) -> None:
        """Register a new job.

        Args:
            job: The job to register. ``job.name`` must be unique across
                every currently registered job.
            interval_seconds: The interval, in seconds, to schedule this
                job at. Defaults to ``job.interval_seconds`` when
                ``None``, allowing a job to declare its own default
                interval while still permitting an override at
                registration time (for example, a shorter interval in a
                test environment).
            enabled: Whether the job starts enabled. A disabled job
                remains registered and retrievable but is never
                scheduled for execution.

        Raises:
            JobRegistrationError: If a job with this name is already
                registered.
        """
        with self._lock:
            if job.name in self._registrations:
                raise JobRegistrationError(job.name, "a job with this name is already registered.")
            resolved_interval = (
                interval_seconds if interval_seconds is not None else job.interval_seconds
            )
            self._registrations[job.name] = JobRegistration(
                job=job, interval_seconds=resolved_interval, enabled=enabled
            )
        self._logger.info(
            "Registered job '%s' (interval=%ds, enabled=%s)",
            job.name,
            resolved_interval,
            enabled,
            extra={"job_name": job.name, "interval_seconds": resolved_interval},
        )

    def unregister(self, job_name: str) -> None:
        """Remove a registered job.

        Args:
            job_name: The job's name.

        Raises:
            JobRegistrationError: If no job with this name is registered.
        """
        with self._lock:
            self._require_registered(job_name)
            del self._registrations[job_name]
        self._logger.info("Unregistered job '%s'", job_name, extra={"job_name": job_name})

    def enable(self, job_name: str) -> None:
        """Enable a registered job.

        Args:
            job_name: The job's name.

        Raises:
            JobRegistrationError: If no job with this name is registered.
        """
        with self._lock:
            self._require_registered(job_name)
            self._registrations[job_name].enabled = True
        self._logger.info("Enabled job '%s'", job_name, extra={"job_name": job_name})

    def disable(self, job_name: str) -> None:
        """Disable a registered job.

        A disabled job remains registered; ``SchedulerCoordinator`` is
        expected to skip disabled jobs when scheduling.

        Args:
            job_name: The job's name.

        Raises:
            JobRegistrationError: If no job with this name is registered.
        """
        with self._lock:
            self._require_registered(job_name)
            self._registrations[job_name].enabled = False
        self._logger.info("Disabled job '%s'", job_name, extra={"job_name": job_name})

    def get(self, job_name: str) -> ScheduledJob:
        """Retrieve a registered job by name.

        Args:
            job_name: The job's name.

        Returns:
            The registered ``ScheduledJob``.

        Raises:
            JobRegistrationError: If no job with this name is registered.
        """
        with self._lock:
            self._require_registered(job_name)
            return self._registrations[job_name].job

    def get_registration(self, job_name: str) -> JobRegistration:
        """Retrieve a job's full registration record, including its
        interval and enabled state.

        Args:
            job_name: The job's name.

        Returns:
            The ``JobRegistration``.

        Raises:
            JobRegistrationError: If no job with this name is registered.
        """
        with self._lock:
            self._require_registered(job_name)
            return self._registrations[job_name]

    def is_registered(self, job_name: str) -> bool:
        """Return whether a job with this name is currently registered.

        Args:
            job_name: The job's name.

        Returns:
            ``True`` if registered, ``False`` otherwise.
        """
        with self._lock:
            return job_name in self._registrations

    def list_jobs(self, *, enabled_only: bool = False) -> list[JobRegistration]:
        """List every registered job.

        Args:
            enabled_only: If ``True``, only currently enabled jobs are
                returned.

        Returns:
            A list of ``JobRegistration`` instances, in registration
            order.
        """
        with self._lock:
            registrations = list(self._registrations.values())
        if enabled_only:
            return [r for r in registrations if r.enabled]
        return registrations

    def _require_registered(self, job_name: str) -> None:
        """Raise if a job name is not currently registered.

        Args:
            job_name: The job's name.

        Raises:
            JobRegistrationError: If no job with this name is registered.
        """
        if job_name not in self._registrations:
            raise JobRegistrationError(job_name, "no job with this name is registered.")
