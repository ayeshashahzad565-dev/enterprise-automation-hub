"""HTTP schemas for the ``admin-jobs``/``admin-scheduled-jobs`` resources.

``JobOut`` wraps ``app.database.repositories.job_repository.JobRecord``
directly (``from_attributes=True`` validates against the dataclass's
attributes, the same "reuse, don't re-derive" technique
``InvitationOut``/``WorkflowDefinitionOut`` already use for their own
repository records) rather than routing through ``app.models.job.Job`` —
there is no Application Service layer between the router and
``JobRepository`` for this resource (mirroring how ``admin_settings.py``
reads ``resources.settings`` directly), so validating straight from the
repository record avoids an unnecessary intermediate translation step.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ConfigDict

from app.models.base import EAHBaseModel, UTCDatetime
from app.models.enums import JobPriority, JobStatus

__all__ = [
    "JobOut",
    "ScheduledJobOut",
    "QueueDepthOut",
    "QueueStatsOut",
]


class JobOut(EAHBaseModel):
    """Wraps ``app.database.repositories.job_repository.JobRecord``.

    ``payload`` is redacted by the router (not this schema) for
    ``task_type == "send_invitation_email"`` before validation — see
    ``app.api.routers.admin_jobs._serialize_job`` — so the raw invitation
    token is never returned by this API even to an authenticated admin.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    id: UUID
    task_type: str
    queue_name: str
    priority: JobPriority
    status: JobStatus
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    last_error: str | None
    error_history: list[dict[str, Any]]
    scheduled_for: UTCDatetime | None
    started_at: UTCDatetime | None
    finished_at: UTCDatetime | None
    locked_by: str | None
    request_id: UUID | None
    actor_id: UUID | None
    created_at: UTCDatetime


class ScheduledJobOut(EAHBaseModel):
    """A single scheduled job's registration + live execution statistics."""

    name: str
    interval_seconds: int
    enabled: bool
    run_count: int
    success_count: int
    failure_count: int
    skipped_overlap_count: int
    currently_running: bool
    last_started_at: UTCDatetime | None
    last_finished_at: UTCDatetime | None
    last_duration_seconds: float | None
    last_error: str | None
    next_run_time: UTCDatetime | None


class QueueDepthOut(EAHBaseModel):
    """The number of ready jobs waiting for one ``(queue_name, priority)`` pair."""

    queue_name: str
    priority: JobPriority
    depth: int


class QueueStatsOut(EAHBaseModel):
    """Live queue depth/delayed/dead-letter counts, read directly from Redis/Postgres.

    ``None`` for ``queue_depth``/``delayed_count`` specifically (not an
    empty list/dict) when Redis is not configured on this instance — the
    job system's live dispatch layer is simply inactive, distinct from
    "every count happens to be zero."
    """

    queue_depth: list[QueueDepthOut] | None
    delayed_count: dict[str, int] | None
    dead_letter_count: dict[str, int]
