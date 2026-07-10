"""The Scheduling Subsystem for the Enterprise Automation Hub.

Per this package's design brief, this package is responsible only for
*executing* periodic background jobs — discovering work, invoking
Application Services, recording execution metadata, and handling
failures. It contains no workflow decision logic; every decision (what a
stage's escalation threshold is, whether an approval action succeeds) is
delegated to ``app.workflow`` and ``app.services`` respectively.

This package contains:

- ``exceptions``: the typed exception hierarchy for registration,
  execution, overlap, startup, and shutdown failures.
- ``interfaces``: the protocols and shared value objects
  (``SchedulerBackend``, ``ScheduledJob``, ``JobRegistryProtocol``,
  ``ExecutionContext``, ``ExecutionResult``, ``JobStatistics``,
  ``SchedulerStatisticsProvider``) that keep this package's components
  decoupled from any specific scheduling library or from each other.
- ``registry``: ``JobRegistry``, the concrete job bookkeeping component.
- ``jobs``: ``BaseJob``, the shared execution-timing and error-handling
  discipline every concrete job extends, plus the discovery helpers
  shared by ``EscalationJob`` and ``ReminderJob``.
- ``escalation_job``: the Escalation Check job (WEDD Section 8.3).
- ``reminder_job``: the Reminder Dispatch job (WEDD Section 8.3).
- ``health_check_job``: the in-memory scheduler health reporting job.
- ``scheduler``: ``SchedulerCoordinator``, the single entry point tying
  every component above together, and ``APSchedulerBackend``, the
  default APScheduler-backed ``SchedulerBackend`` implementation.

This module re-exports the public surface of every submodule so that
calling code (in particular, whatever process bootstraps the application
at startup, per the Deployment Guide's ``SCHEDULER_LEADER`` convention)
can import from ``app.scheduler`` directly.
"""

from __future__ import annotations

from app.scheduler.escalation_job import EscalationJob
from app.scheduler.exceptions import (
    JobAlreadyRunningError,
    JobExecutionError,
    JobRegistrationError,
    SchedulerError,
    SchedulerShutdownError,
    SchedulerStartupError,
)
from app.scheduler.health_check_job import HealthCheckJob, JobHealthStatus, SchedulerHealthSnapshot
from app.scheduler.interfaces import (
    ExecutionContext,
    ExecutionResult,
    JobRegistryProtocol,
    JobStatistics,
    ScheduledJob,
    SchedulerBackend,
    SchedulerStatisticsProvider,
)
from app.scheduler.jobs import BaseJob, ItemBatchResult, StageContext, iter_pending_stages, load_stage_context
from app.scheduler.registry import JobRegistration, JobRegistry
from app.scheduler.reminder_job import ReminderJob
from app.scheduler.scheduler import APSchedulerBackend, SchedulerCoordinator

__all__ = [
    # escalation_job
    "EscalationJob",
    # exceptions
    "JobAlreadyRunningError",
    "JobExecutionError",
    "JobRegistrationError",
    "SchedulerError",
    "SchedulerShutdownError",
    "SchedulerStartupError",
    # health_check_job
    "HealthCheckJob",
    "JobHealthStatus",
    "SchedulerHealthSnapshot",
    # interfaces
    "ExecutionContext",
    "ExecutionResult",
    "JobRegistryProtocol",
    "JobStatistics",
    "ScheduledJob",
    "SchedulerBackend",
    "SchedulerStatisticsProvider",
    # jobs
    "BaseJob",
    "ItemBatchResult",
    "StageContext",
    "iter_pending_stages",
    "load_stage_context",
    # registry
    "JobRegistration",
    "JobRegistry",
    # reminder_job
    "ReminderJob",
    # scheduler
    "APSchedulerBackend",
    "SchedulerCoordinator",
]