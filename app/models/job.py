"""Domain models for the ``jobs`` table.

``jobs`` is the durable system of record for the background job system
(migration ``0015_jobs``): every unit of asynchronous work — an email
send, an invitation dispatch, a stage escalation, a reminder — is
represented by exactly one row here for its entire lifecycle, from
``queued`` through however many ``retrying`` attempts to a terminal
``succeeded`` or ``dead_lettered`` state. Redis (``app.jobs.redis_queue``)
only ever holds an ephemeral ``{"job_id", "priority"}`` pointer into this
table; this module's ``Job`` model is the authoritative shape of a job's
state, matching this codebase's existing "Postgres is truth, Redis is
acceleration" convention (see ``docs/deployment.md`` Section 16.5).

Like ``app.models.audit``, this module defines no generic update model —
every status transition is a specific, named operation
(``JobRepository.mark_running``, ``.mark_succeeded``, and so on), never a
free-form PATCH.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.models.base import EAHBaseModel, IdentifiedModel, TimestampedModel, UTCDatetime
from app.models.enums import JobPriority, JobStatus

__all__ = ["Job", "JobCreate"]


class Job(IdentifiedModel, TimestampedModel):
    """A fully validated, persisted representation of a ``jobs`` row.

    Attributes:
        task_type: The handler this job dispatches to (e.g.
            ``"send_email"``, ``"escalate_stage"``) — see
            ``app.jobs.handlers.TASK_HANDLERS``.
        queue_name: Which worker role consumes this job (``"default"`` or
            ``"escalation"`` in the reference deployment).
        priority: This job's priority tier.
        status: The job's current lifecycle state.
        payload: The handler-specific input, JSON-serializable.
        attempts: How many times a worker has attempted this job so far.
        max_attempts: The attempt budget before this job is dead-lettered.
        last_error: The most recent failure's message, if any.
        error_history: Up to the last 20 ``{"attempt", "error", "at"}``
            entries, oldest first.
        scheduled_for: When this job becomes eligible for dequeue, for a
            job currently waiting in the delayed/retry set. ``None`` for
            a job already sitting in a ready queue.
        started_at: When the current (or most recent) attempt began.
        finished_at: When this job most recently reached a terminal
            per-attempt outcome (success, or moved to retrying/dead
            letter).
        locked_by: The worker hostname currently (or most recently)
            processing this job.
        request_id: The related request, if any — lets an operator find
            every job associated with a given request.
        actor_id: The user whose action caused this job to be enqueued,
            or ``None`` for a system-initiated job (e.g. from
            ``EscalationJob``).
        version: The optimistic-locking version (DSD Section 3.9
            pattern), incremented on every status transition.
    """

    task_type: str
    queue_name: str
    priority: JobPriority
    status: JobStatus
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    last_error: str | None = None
    error_history: list[dict[str, Any]] = []
    scheduled_for: UTCDatetime | None = None
    started_at: UTCDatetime | None = None
    finished_at: UTCDatetime | None = None
    locked_by: str | None = None
    request_id: UUID | None = None
    actor_id: UUID | None = None
    version: int


class JobCreate(EAHBaseModel):
    """Input model for enqueuing a new job.

    Constructed exclusively by ``app.jobs.job_service.JobService.enqueue``
    — no other code path creates a ``jobs`` row.

    Attributes:
        task_type: The handler this job dispatches to.
        queue_name: Which worker role should consume this job.
        priority: This job's priority tier.
        payload: The handler-specific input, JSON-serializable.
        max_attempts: The attempt budget before dead-lettering.
        scheduled_for: When this job becomes eligible, for a job enqueued
            directly into the delayed set rather than a ready queue.
            ``None`` means "eligible immediately."
        request_id: The related request, if any.
        actor_id: The user whose action caused this job to be enqueued,
            if any.
    """

    task_type: str
    queue_name: str
    priority: JobPriority
    payload: dict[str, Any]
    max_attempts: int
    scheduled_for: UTCDatetime | None = None
    request_id: UUID | None = None
    actor_id: UUID | None = None
