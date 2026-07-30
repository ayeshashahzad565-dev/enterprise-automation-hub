"""The job system's consumer process.

Run with ``python -m app.jobs.worker [--role {default,escalation,all}]``.
This is a separate, long-lived process from the API (its own Docker
Compose ``worker-default``/``worker-escalation`` service/container) — it
builds the exact same ``ApplicationResources`` object graph
``app.api.main``'s ``lifespan`` handler does (via
``app.bootstrap.build_application_resources``), so every collaborator a
handler needs (``ApprovalService``, ``NotificationService``, SMTP/
invitation settings) is wired identically to the API process, with zero
duplicated composition logic.

Requires ``REDIS_URL`` to be set; refuses to start otherwise (matching
the earlier ``app.queue.worker``'s identical rule) — a worker process
with nothing to consume from is a misconfiguration, not a
degrade-gracefully case (unlike every *optional* Redis-backed component
elsewhere in this codebase; see ``app.jobs.job_service.SynchronousJobDispatcher``
for how ``EscalationJob``/``ReminderJob`` themselves still work fine with
no Redis at all — that fallback runs inline in the API/scheduler process,
never in a worker).

**Role selection** determines which ``queue_name``(s) this process
consumes (``ROLE_QUEUE_NAMES`` below) — the same worker code runs as
either a general-purpose worker (``send_email``/``send_invitation_email``)
or a dedicated escalation worker (``escalate_stage``/``send_reminder``),
selected via ``--role`` or the ``WORKER_ROLE`` environment variable, so
Docker Compose can run two differently-specialized containers from one
image with zero code duplication.

**Retry/backoff/dead-letter**: on handler failure, this module computes
the next retry delay (``app.jobs.backoff``) and either reschedules the
job (``JobRepository.mark_failed_will_retry`` + a push onto the delayed
set) or, once ``max_attempts`` is exhausted, dead-letters it
(``JobRepository.mark_dead_lettered``) — Postgres is the only place this
state is recorded; nothing goes back to Redis for a dead-lettered job.

**Graceful shutdown**: SIGTERM/SIGINT set a flag checked between
iterations of the main loop; an in-flight job always runs to completion
(its Postgres transition is written) before the process exits. The
promoter thread shares the same shutdown signal.
"""

from __future__ import annotations

import argparse
import logging
import signal
import socket
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from types import FrameType
from uuid import UUID

from prometheus_client import start_http_server

from app.bootstrap import ApplicationResources, build_application_resources
from app.config.constants import VALID_WORKER_ROLES
from app.config.logging_config import configure_logging
from app.config.settings import AppSettings, load_settings
from app.jobs import backoff
from app.jobs.handlers import TASK_HANDLERS
from app.jobs.redis_queue import RedisJobQueue
from app.models.enums import JobPriority
from app.observability.metrics import JOB_DURATION_SECONDS, JOBS_PROCESSED_TOTAL, WORKER_UP

logger = logging.getLogger(__name__)

#: Which ``queue_name``(s) each worker role consumes.
ROLE_QUEUE_NAMES: dict[str, tuple[str, ...]] = {
    "default": ("default",),
    "escalation": ("escalation",),
    "all": ("default", "escalation"),
}

_DEQUEUE_TIMEOUT_SECONDS = 5
_PROMOTE_INTERVAL_SECONDS = 1.0
#: Every Nth loop iteration, the priority poll order is reversed
#: (low-first instead of high-first) so sustained high-priority traffic
#: cannot starve lower-priority jobs indefinitely.
_PRIORITY_REVERSAL_INTERVAL = 8

_shutdown_event = threading.Event()


def _request_shutdown(signum: int, frame: FrameType | None) -> None:
    logger.info("Worker received signal %d; shutting down after the current job.", signum)
    _shutdown_event.set()


def _priority_order(iteration: int) -> list[JobPriority]:
    """The priority poll order for this loop iteration.

    Args:
        iteration: The current loop iteration count.

    Returns:
        ``[HIGH, NORMAL, LOW]`` normally, reversed to
        ``[LOW, NORMAL, HIGH]`` every ``_PRIORITY_REVERSAL_INTERVAL``th
        iteration.
    """
    order = [JobPriority.HIGH, JobPriority.NORMAL, JobPriority.LOW]
    if iteration % _PRIORITY_REVERSAL_INTERVAL == 0:
        order.reverse()
    return order


def _run_promoter(redis_queue: RedisJobQueue, queue_names: tuple[str, ...]) -> None:
    """Background thread: periodically promote due delayed jobs onto their ready lists."""
    while not _shutdown_event.is_set():
        for queue_name in queue_names:
            try:
                redis_queue.promote_due(queue_name=queue_name, now=datetime.now(UTC))
            except Exception:
                logger.exception("Promoter failed for queue %r", queue_name)
        _shutdown_event.wait(_PROMOTE_INTERVAL_SECONDS)


def _build_handler_kwargs(resources: ApplicationResources) -> dict[str, dict[str, object]]:
    """Resolve each ``task_type``'s extra keyword arguments from ``resources``."""
    settings: AppSettings = resources.settings
    return {
        "send_email": {"smtp_settings": settings.smtp},
        "send_invitation_email": {
            "smtp_settings": settings.smtp,
            "invitation_settings": settings.invitation,
        },
        "escalate_stage": {"approval_service": resources.approval_service},
        "send_reminder": {"notification_service": resources.notification_service},
    }


def _process_one(
    job_id: str,
    *,
    resources: ApplicationResources,
    redis_queue: RedisJobQueue,
    handler_kwargs: dict[str, dict[str, object]],
    hostname: str,
) -> None:
    """Fetch, execute, and record the outcome of a single dequeued job."""
    try:
        job = resources.job_repository.get_by_id(UUID(job_id))
    except Exception:
        logger.exception("Failed to load job %s; dropping it (nothing to retry against).", job_id)
        return

    job = resources.job_repository.mark_running(
        job.id, expected_version=job.version, locked_by=hostname
    )

    handler = TASK_HANDLERS.get(job.task_type)
    extra_kwargs = handler_kwargs.get(job.task_type, {})
    outcome: bool
    error_message: str | None = None
    started_at = time.monotonic()
    if handler is None:
        outcome = False
        error_message = f"No handler registered for task_type {job.task_type!r}."
        logger.warning(error_message, extra={"job_id": job_id, "task_type": job.task_type})
    else:
        try:
            outcome = handler(job.payload, **extra_kwargs)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - any handler failure is a retryable outcome
            outcome = False
            error_message = f"{type(exc).__name__}: {exc}"
            logger.exception("Job %s (%s) raised", job.id, job.task_type)
    JOB_DURATION_SECONDS.labels(task_type=job.task_type).observe(time.monotonic() - started_at)

    if outcome:
        resources.job_repository.mark_succeeded(job.id, expected_version=job.version)
        JOBS_PROCESSED_TOTAL.labels(task_type=job.task_type, outcome="succeeded").inc()
        logger.info(
            "Job %s (%s) succeeded",
            job.id,
            job.task_type,
            extra={"job_id": str(job.id), "task_type": job.task_type, "outcome": "succeeded"},
        )
        return

    new_attempts = job.attempts + 1
    if new_attempts < job.max_attempts:
        delay = backoff.compute_delay_seconds(new_attempts)
        next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
        resources.job_repository.mark_failed_will_retry(
            job.id,
            expected_version=job.version,
            attempts=new_attempts,
            error=error_message or "handler reported failure",
            current_error_history=job.error_history,
            next_attempt_scheduled_for=next_attempt_at,
        )
        redis_queue.push_delayed(
            queue_name=job.queue_name,
            priority=JobPriority(job.priority),
            job_id=str(job.id),
            ready_at=next_attempt_at,
        )
        JOBS_PROCESSED_TOTAL.labels(task_type=job.task_type, outcome="retrying").inc()
        logger.warning(
            "Job %s (%s) failed (attempt %d/%d); retrying at %s",
            job.id,
            job.task_type,
            new_attempts,
            job.max_attempts,
            next_attempt_at.isoformat(),
            extra={"job_id": str(job.id), "task_type": job.task_type, "outcome": "retrying"},
        )
    else:
        resources.job_repository.mark_dead_lettered(
            job.id,
            expected_version=job.version,
            attempts=new_attempts,
            error=error_message or "handler reported failure",
            current_error_history=job.error_history,
        )
        JOBS_PROCESSED_TOTAL.labels(task_type=job.task_type, outcome="dead_lettered").inc()
        logger.error(
            "Job %s (%s) dead-lettered after %d attempts",
            job.id,
            job.task_type,
            new_attempts,
            extra={"job_id": str(job.id), "task_type": job.task_type, "outcome": "dead_lettered"},
        )


def run(role: str | None = None) -> None:
    """Run the worker loop until interrupted.

    Args:
        role: Which worker role to run as (``"default"``, ``"escalation"``,
            or ``"all"``). Defaults to ``AppSettings.jobs.worker_role``
            (the ``WORKER_ROLE`` environment variable) when not passed
            explicitly, which is how the ``--role``-less Docker Compose
            invocation is configured.
    """
    settings = load_settings()
    configure_logging(settings.logging.level)

    if not settings.redis.enabled:
        logger.error("app.jobs.worker requires REDIS_URL to be configured; exiting.")
        sys.exit(1)

    resolved_role = (role or settings.jobs.worker_role).lower()
    if resolved_role not in VALID_WORKER_ROLES:
        logger.error("Unrecognized worker role %r; exiting.", resolved_role)
        sys.exit(1)
    queue_names = ROLE_QUEUE_NAMES[resolved_role]

    resources = build_application_resources(settings)
    redis_queue = RedisJobQueue(client=resources.redis_client)  # type: ignore[arg-type]
    handler_kwargs = _build_handler_kwargs(resources)
    hostname = socket.gethostname()

    # This process's own tiny Prometheus HTTP server — workers have no
    # other HTTP server, so their local metrics (jobs processed,
    # duration, this gauge) can't go through the backend's /metrics; see
    # app.observability.metrics's module comment.
    start_http_server(settings.jobs.worker_metrics_port)
    WORKER_UP.labels(worker_id=hostname, role=resolved_role).set(1)

    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    promoter_thread = threading.Thread(
        target=_run_promoter, args=(redis_queue, queue_names), daemon=True, name="job-promoter"
    )
    promoter_thread.start()

    logger.info(
        "Worker started (role=%s, queues=%s); waiting for jobs.", resolved_role, queue_names
    )
    iteration = 0
    while not _shutdown_event.is_set():
        redis_queue.record_heartbeat(hostname=hostname)
        job_id = redis_queue.dequeue(
            queue_names=queue_names,
            priority_order=_priority_order(iteration),
            timeout_seconds=_DEQUEUE_TIMEOUT_SECONDS,
        )
        iteration += 1
        if job_id is None:
            continue

        _process_one(
            job_id,
            resources=resources,
            redis_queue=redis_queue,
            handler_kwargs=handler_kwargs,
            hostname=hostname,
        )

    promoter_thread.join(timeout=_PROMOTE_INTERVAL_SECONDS * 2)
    WORKER_UP.labels(worker_id=hostname, role=resolved_role).set(0)
    logger.info("Worker shut down cleanly.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the job system's worker process.")
    parser.add_argument(
        "--role",
        choices=sorted(VALID_WORKER_ROLES),
        default=None,
        help="Which queue(s) to consume; defaults to the WORKER_ROLE environment variable.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(role=args.role)
