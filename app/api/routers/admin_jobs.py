"""Routes for the ``admin-jobs``/``admin-scheduled-jobs`` resources: the
job system's operational dashboard surface — job history/status
inspection, dead-letter listing and retry, queue-depth/stats, and
scheduled-job (``escalation_check``/``reminder_dispatch``/
``stuck_job_reaper``/``scheduler_health_check``) management.

Talks directly to ``JobRepository``/``RedisJobQueue``/``SchedulerCoordinator``
via ``ApplicationResources`` — there is no Application Service layer for
this resource (mirroring ``admin_settings.py``'s identical "read
``resources.X`` directly" shape) — so, unlike every ``app.services``-
backed admin router, authorization is enforced inline here via
``rbac.require_role`` as this module's own responsibility, and a
``app.database.exceptions.DatabaseError`` escaping a repository call is
translated explicitly (``translate_database_error``) rather than being an
``app.services``-layer method's job.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_current_identity, get_resources
from app.api.schemas.admin_jobs import JobOut, QueueDepthOut, QueueStatsOut, ScheduledJobOut
from app.auth import rbac
from app.auth.authentication import AuthenticatedIdentity
from app.bootstrap import ApplicationResources
from app.database.exceptions import DatabaseError
from app.database.repositories.base_repository import Page
from app.database.repositories.job_repository import JobRecord
from app.jobs.task_types import TASK_SEND_INVITATION_EMAIL
from app.models.enums import AuditAction, JobPriority, JobStatus, UserRole
from app.scheduler.exceptions import JobRegistrationError
from app.services.exceptions import NotFoundError, ValidationError, translate_database_error
from app.utils.pagination import build_pagination_metadata
from app.utils.response import build_list_response, build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["admin-jobs"])

#: Every ``queue_name`` the reference deployment's two worker roles
#: consume — used only to shape the queue-depth summary; a deployment
#: with custom queue names would need this list extended, matching
#: ROLE_QUEUE_NAMES in app.jobs.worker.
_KNOWN_QUEUE_NAMES = ("default", "escalation")

#: task_types whose payload may contain a sensitive value that must never
#: be returned by this API, even to an authenticated admin — see
#: ``_serialize_job``.
_REDACTED_PAYLOAD_FIELDS: dict[str, tuple[str, ...]] = {
    TASK_SEND_INVITATION_EMAIL: ("token",),
}
_REDACTED_PLACEHOLDER = "***redacted***"


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _serialize_job(record: JobRecord) -> dict[str, Any]:
    """Build a ``JobOut`` from a ``JobRecord``, redacting sensitive payload fields.

    Args:
        record: The job record to serialize.

    Returns:
        The serialized, redaction-applied representation.
    """
    redacted_fields = _REDACTED_PAYLOAD_FIELDS.get(record.task_type, ())
    if redacted_fields and any(field in record.payload for field in redacted_fields):
        payload = dict(record.payload)
        for field in redacted_fields:
            if field in payload:
                payload[field] = _REDACTED_PLACEHOLDER
        record = JobRecord(
            id=record.id,
            task_type=record.task_type,
            queue_name=record.queue_name,
            priority=record.priority,
            status=record.status,
            payload=payload,
            attempts=record.attempts,
            max_attempts=record.max_attempts,
            last_error=record.last_error,
            error_history=record.error_history,
            scheduled_for=record.scheduled_for,
            started_at=record.started_at,
            finished_at=record.finished_at,
            locked_by=record.locked_by,
            request_id=record.request_id,
            actor_id=record.actor_id,
            version=record.version,
            created_at=record.created_at,
        )
    return serialize(JobOut.model_validate(record))


def _scheduled_job_out(name: str, *, resources: ApplicationResources) -> ScheduledJobOut | None:
    """Build a ``ScheduledJobOut`` for one registered scheduled job.

    Args:
        name: The scheduled job's name.
        resources: The application resource bundle.

    Returns:
        ``None`` if no scheduler is active on this instance, or no job
        with this name is registered.
    """
    if resources.scheduler_stats is None:
        return None
    stats = resources.scheduler_stats.get_statistics(name)
    if stats is None:
        return None
    try:
        registration = resources.scheduler_stats.get_registration(name)
    except JobRegistrationError:
        return None
    return ScheduledJobOut(
        name=name,
        interval_seconds=registration.interval_seconds,
        enabled=registration.enabled,
        run_count=stats.run_count,
        success_count=stats.success_count,
        failure_count=stats.failure_count,
        skipped_overlap_count=stats.skipped_overlap_count,
        currently_running=stats.currently_running,
        last_started_at=stats.last_started_at,
        last_finished_at=stats.last_finished_at,
        last_duration_seconds=stats.last_duration_seconds,
        last_error=stats.last_error,
        next_run_time=stats.next_run_time,
    )


@router.get("/admin/jobs/dead-letter")
def list_dead_letter_jobs(
    request: Request,
    task_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """List dead-lettered jobs, newest first. Admin only."""
    rbac.require_role(identity.role, UserRole.ADMIN)
    result = resources.job_repository.list_dead_letter(
        task_type=task_type, page=Page(number=page, size=page_size)
    )
    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    out = [_serialize_job(item) for item in result.items]
    return build_list_response(out, pagination=pagination, request_id=_request_id_of(request))


@router.get("/admin/jobs/stats/summary")
def get_queue_stats(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """Live queue depth (Redis) and dead-letter counts (Postgres). Admin only."""
    rbac.require_role(identity.role, UserRole.ADMIN)

    queue_depth: list[QueueDepthOut] | None = None
    delayed_count: dict[str, int] | None = None
    if resources.redis_job_queue is not None:
        queue_depth = [
            QueueDepthOut(
                queue_name=queue_name,
                priority=priority,
                depth=resources.redis_job_queue.queue_depth(
                    queue_name=queue_name, priority=priority
                ),
            )
            for queue_name in _KNOWN_QUEUE_NAMES
            for priority in JobPriority
        ]
        delayed_count = {
            queue_name: resources.redis_job_queue.delayed_count(queue_name=queue_name)
            for queue_name in _KNOWN_QUEUE_NAMES
        }

    dead_letter_count = resources.job_repository.count_dead_letter_by_queue()
    out = QueueStatsOut(
        queue_depth=queue_depth, delayed_count=delayed_count, dead_letter_count=dead_letter_count
    )
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/admin/jobs/{job_id}")
def get_job(
    request: Request,
    job_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """Fetch a single job's full detail, including its error history. Admin only."""
    rbac.require_role(identity.role, UserRole.ADMIN)
    try:
        job = resources.job_repository.get_by_id(job_id)
    except DatabaseError as exc:
        raise translate_database_error(exc) from exc
    return build_success_response(_serialize_job(job), request_id=_request_id_of(request))


@router.post("/admin/jobs/{job_id}/retry")
def retry_job(
    request: Request,
    job_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """Retry a dead-lettered job: reset its attempt budget and re-queue it. Admin only."""
    rbac.require_role(identity.role, UserRole.ADMIN)
    if resources.job_service is None or resources.redis_job_queue is None:
        raise ValidationError("The job system is not active on this instance (Redis is not configured).")

    try:
        job = resources.job_repository.get_by_id(job_id)
    except DatabaseError as exc:
        raise translate_database_error(exc) from exc
    if job.status != JobStatus.DEAD_LETTERED.value:
        raise ValidationError(
            f"Job {job_id} is not dead-lettered (current status: {job.status!r}); only a "
            "dead-lettered job can be retried."
        )

    try:
        retried = resources.job_repository.retry_dead_letter(job_id, expected_version=job.version)
    except DatabaseError as exc:
        raise translate_database_error(exc) from exc
    resources.redis_job_queue.push_ready(
        queue_name=retried.queue_name, priority=JobPriority(retried.priority), job_id=str(retried.id)
    )
    resources.audit_repo.record_event(
        action=AuditAction.JOB_RETRIED,
        actor_id=identity.user_id,
        request_id=retried.request_id,
        metadata={"job_id": str(job_id), "task_type": retried.task_type},
    )
    return build_success_response(_serialize_job(retried), request_id=_request_id_of(request))


@router.get("/admin/jobs")
def list_jobs(
    request: Request,
    status: JobStatus | None = Query(None),
    task_type: str | None = Query(None),
    queue_name: str | None = Query(None),
    priority: JobPriority | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """List jobs, newest first, filtered by any combination of fields. Admin only."""
    rbac.require_role(identity.role, UserRole.ADMIN)
    result = resources.job_repository.list_jobs(
        status=status.value if status is not None else None,
        task_type=task_type,
        queue_name=queue_name,
        priority=priority.value if priority is not None else None,
        page=Page(number=page, size=page_size),
    )
    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    out = [_serialize_job(item) for item in result.items]
    return build_list_response(out, pagination=pagination, request_id=_request_id_of(request))


#: The fixed set of scheduled jobs this instance may register (see
#: ``app.bootstrap``'s ``SCHEDULER_LEADER`` block) — used only to shape
#: ``GET /admin/scheduled-jobs``'s response; a job not currently
#: registered (e.g. ``stuck_job_reaper`` when Redis is not configured) is
#: simply omitted, not reported as an error.
_KNOWN_SCHEDULED_JOB_NAMES = (
    "escalation_check",
    "reminder_dispatch",
    "stuck_job_reaper",
    "scheduler_health_check",
)


@router.get("/admin/scheduled-jobs")
def list_scheduled_jobs(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """List every scheduled job's registration and live statistics. Admin only.

    Returns an empty list (not an error) when no scheduler is active on
    this instance (``SCHEDULER_LEADER=false``) — the operator should
    check another instance's ``/admin/scheduled-jobs`` in that case.
    """
    rbac.require_role(identity.role, UserRole.ADMIN)
    jobs = [
        _scheduled_job_out(name, resources=resources) for name in _KNOWN_SCHEDULED_JOB_NAMES
    ]
    out = [serialize(job) for job in jobs if job is not None]
    return build_success_response(out, request_id=_request_id_of(request))


@router.post("/admin/scheduled-jobs/{job_name}/enable")
def enable_scheduled_job(
    request: Request,
    job_name: str,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """Enable a scheduled job. Admin only."""
    rbac.require_role(identity.role, UserRole.ADMIN)
    if resources.scheduler_stats is None:
        raise ValidationError("No scheduler is active on this instance.")
    try:
        resources.scheduler_stats.enable_job(job_name)
    except JobRegistrationError as exc:
        raise NotFoundError("scheduled_job", job_name) from exc
    resources.audit_repo.record_event(
        action=AuditAction.SCHEDULED_JOB_ENABLED,
        actor_id=identity.user_id,
        metadata={"job_name": job_name},
    )
    job = _scheduled_job_out(job_name, resources=resources)
    return build_success_response(
        serialize(job) if job is not None else None, request_id=_request_id_of(request)
    )


@router.post("/admin/scheduled-jobs/{job_name}/disable")
def disable_scheduled_job(
    request: Request,
    job_name: str,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """Disable a scheduled job. Admin only."""
    rbac.require_role(identity.role, UserRole.ADMIN)
    if resources.scheduler_stats is None:
        raise ValidationError("No scheduler is active on this instance.")
    try:
        resources.scheduler_stats.disable_job(job_name)
    except JobRegistrationError as exc:
        raise NotFoundError("scheduled_job", job_name) from exc
    resources.audit_repo.record_event(
        action=AuditAction.SCHEDULED_JOB_DISABLED,
        actor_id=identity.user_id,
        metadata={"job_name": job_name},
    )
    job = _scheduled_job_out(job_name, resources=resources)
    return build_success_response(
        serialize(job) if job is not None else None, request_id=_request_id_of(request)
    )


@router.post("/admin/scheduled-jobs/{job_name}/trigger-now", status_code=202)
def trigger_scheduled_job_now(
    request: Request,
    job_name: str,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """Trigger a scheduled job to run immediately, out of band from its interval. Admin only.

    Returns as soon as the run has been triggered — not once it has
    finished; poll ``GET /admin/scheduled-jobs`` to observe the outcome.
    """
    rbac.require_role(identity.role, UserRole.ADMIN)
    if resources.scheduler_stats is None:
        raise ValidationError("No scheduler is active on this instance.")
    try:
        resources.scheduler_stats.trigger_now(job_name)
    except JobRegistrationError as exc:
        raise NotFoundError("scheduled_job", job_name) from exc
    resources.audit_repo.record_event(
        action=AuditAction.SCHEDULED_JOB_TRIGGERED,
        actor_id=identity.user_id,
        metadata={"job_name": job_name},
    )
    return build_success_response({"triggered": True}, request_id=_request_id_of(request))
