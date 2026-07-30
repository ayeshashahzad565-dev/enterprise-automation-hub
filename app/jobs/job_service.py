"""``JobService`` — the single choke point every producer enqueues through
when Redis is configured, and ``SynchronousJobDispatcher`` — its
in-process fallback when it is not.

No other code path in this codebase creates a ``jobs`` row or pushes onto
``app.jobs.redis_queue`` directly — every producer (``RedisQueueEmailSender``,
``QueuedInvitationEmailSender``, ``EscalationJob``, ``ReminderJob``,
``StuckJobReaperJob``, the admin retry endpoint) goes through
``JobService``, so "how a job gets from a producer's intent to both
Postgres and Redis" is defined in exactly one place.

``EscalationJob``/``ReminderJob`` are unlike the other producers: before
this job system existed, they ran their action (``ApprovalService.
escalate_stage`` / ``NotificationService.notify_reminder``) synchronously
and unconditionally — with no dependency on Redis at all, since Redis did
not yet exist as a concept for them. Per this codebase's firm "``REDIS_URL``
absent means byte-for-byte the same behavior as before this layer was
introduced" convention (the same rule ``RedisRateLimiter``/``RedisCache``
already follow), those two jobs must keep working exactly as before when
Redis is not configured — so ``app.bootstrap`` wires them a
``JobDispatcher`` that is ``JobService`` (real, async, Redis+Postgres)
when Redis is enabled, or ``SynchronousJobDispatcher`` (executes the
handler immediately, in the calling scheduler thread, no Redis or Postgres
involved) when it is not. Both satisfy the same narrow ``JobDispatcher``
Protocol, so the two scheduled jobs' own code never branches on which one
they were given.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.database.repositories.job_repository import JobRecord, JobRepository
from app.jobs.redis_queue import RedisJobQueue
from app.models.enums import JobPriority

__all__ = ["JobDispatcher", "JobService", "SynchronousJobDispatcher"]

logger = logging.getLogger(__name__)


class JobDispatcher(Protocol):
    """The narrow interface ``EscalationJob``/``ReminderJob`` depend on.

    Satisfied structurally by both ``JobService`` (the real, async,
    Redis+Postgres-backed implementation) and ``SynchronousJobDispatcher``
    (the in-process, no-Redis fallback) — see this module's docstring.
    """

    def enqueue(
        self,
        *,
        task_type: str,
        queue_name: str,
        payload: dict[str, Any],
        priority: JobPriority = ...,
        max_attempts: int | None = ...,
        scheduled_for: datetime | None = ...,
        request_id: UUID | None = ...,
        actor_id: UUID | None = ...,
    ) -> JobRecord | None: ...


class JobService:
    """Enqueues a job durably (Postgres) and for live dispatch (Redis)."""

    def __init__(
        self,
        *,
        job_repository: JobRepository,
        redis_queue: RedisJobQueue,
        default_max_attempts: int,
    ) -> None:
        """Initialize the service.

        Args:
            job_repository: The durable system of record for job status.
            redis_queue: The live dispatch mechanism a worker polls.
            default_max_attempts: The attempt budget used when a caller
                does not pass an explicit ``max_attempts`` override.
        """
        self._job_repository = job_repository
        self._redis_queue = redis_queue
        self._default_max_attempts = default_max_attempts

    def enqueue(
        self,
        *,
        task_type: str,
        queue_name: str,
        payload: dict[str, Any],
        priority: JobPriority = JobPriority.NORMAL,
        max_attempts: int | None = None,
        scheduled_for: datetime | None = None,
        request_id: UUID | None = None,
        actor_id: UUID | None = None,
    ) -> JobRecord:
        """Durably record a new job and make it available for dispatch.

        Args:
            task_type: The handler this job dispatches to (see
                ``app.jobs.handlers.TASK_HANDLERS``).
            queue_name: Which worker role should consume this job
                (``"default"`` or ``"escalation"`` in the reference
                deployment).
            payload: The handler-specific input, JSON-serializable.
            priority: This job's priority tier.
            max_attempts: The attempt budget before dead-lettering.
                Defaults to ``default_max_attempts`` when omitted.
            scheduled_for: When this job becomes eligible, if not
                immediately (``None``, the default, means "as soon as a
                worker is available").
            request_id: The related request, if any.
            actor_id: The user whose action caused this job to be
                enqueued, if any.

        Returns:
            The newly created ``JobRecord``, already durably persisted.
            Its Redis dispatch entry has also been written by the time
            this returns, except in the rare case logged below.
        """
        resolved_max_attempts = (
            max_attempts if max_attempts is not None else self._default_max_attempts
        )
        job = self._job_repository.create_job(
            task_type=task_type,
            queue_name=queue_name,
            priority=priority.value,
            payload=payload,
            max_attempts=resolved_max_attempts,
            scheduled_for=scheduled_for,
            request_id=request_id,
            actor_id=actor_id,
        )

        # The Postgres row (the durable record of intent) is already
        # committed at this point. If the Redis push below fails, the job
        # exists only as a "queued" row with no live dispatch entry —
        # exactly the case app.scheduler.stuck_job_reaper_job.StuckJobReaperJob's
        # list_stuck_queued sweep exists to recover, rather than raising
        # here and leaving the caller to guess whether the durable record
        # was created or not.
        try:
            if scheduled_for is None:
                self._redis_queue.push_ready(
                    queue_name=queue_name, priority=priority, job_id=str(job.id)
                )
            else:
                self._redis_queue.push_delayed(
                    queue_name=queue_name,
                    priority=priority,
                    job_id=str(job.id),
                    ready_at=scheduled_for,
                )
        except Exception:
            logger.exception(
                "Job %s (%s) was durably recorded but its Redis dispatch push failed; "
                "the stuck-queued reaper will recover it.",
                job.id,
                task_type,
                extra={"job_id": str(job.id), "task_type": task_type},
            )

        return job


class SynchronousJobDispatcher:
    """The no-Redis fallback for ``EscalationJob``/``ReminderJob``.

    Executes the requested handler immediately, in the caller's own
    thread — no Postgres row is created and no Redis structure is
    touched, since there is no separate worker process to hand work off
    to. This is deliberately the closest possible equivalent to a direct
    function call, matching exactly what ``EscalationJob``/``ReminderJob``
    did before the job system existed: a job dispatched through this
    class either succeeds or fails synchronously, on the spot, with no
    retry/backoff/dead-letter machinery — that machinery is what having
    Redis configured actually buys a deployment.
    """

    def __init__(self, *, handlers: Mapping[str, Callable[[dict[str, Any]], bool]]) -> None:
        """Initialize the dispatcher.

        Args:
            handlers: A mapping of ``task_type`` to an already-bound
                zero-extra-argument handler (i.e. every collaborator a
                handler in ``app.jobs.handlers`` needs beyond ``payload``
                has already been supplied via ``functools.partial`` by
                the caller, ``app.bootstrap``).
        """
        self._handlers = handlers

    def enqueue(
        self,
        *,
        task_type: str,
        queue_name: str = "default",
        payload: dict[str, Any],
        priority: JobPriority = JobPriority.NORMAL,
        max_attempts: int | None = None,
        scheduled_for: datetime | None = None,
        request_id: UUID | None = None,
        actor_id: UUID | None = None,
    ) -> None:
        """Execute the requested handler immediately.

        Args:
            task_type: Which handler to invoke.
            queue_name: Unused — accepted only so this method's signature
                matches ``JobDispatcher``.
            payload: The handler's input.
            priority: Unused, for the same reason as ``queue_name``.
            max_attempts: Unused — there is no retry loop in this
                implementation; a failure here is simply a failure.
            scheduled_for: Unused — this implementation always executes
                immediately. ``EscalationJob``/``ReminderJob`` (the only
                producers this dispatcher serves) never pass this.
            request_id: Unused.
            actor_id: Unused.
        """
        handler = self._handlers.get(task_type)
        if handler is None:
            logger.warning(
                "SynchronousJobDispatcher has no handler registered for task_type %r; skipping.",
                task_type,
                extra={"task_type": task_type},
            )
            return
        try:
            succeeded = handler(payload)
        except Exception:
            logger.exception(
                "Synchronous execution of task_type %r failed.",
                task_type,
                extra={"task_type": task_type},
            )
            return
        if not succeeded:
            logger.warning(
                "Synchronous execution of task_type %r reported failure.",
                task_type,
                extra={"task_type": task_type},
            )
