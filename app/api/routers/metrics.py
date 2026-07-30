"""``GET /metrics`` — Prometheus scrape endpoint.

Mounted at the application root (not under ``/api/v1``, matching
Prometheus's own ``/metrics`` convention every scrape config expects by
default) and, like ``health``, deliberately excluded from authentication
and rate limiting — a metrics scraper is an internal, trusted caller
(the Docker Compose ``prometheus`` service, or a cluster's own scrape
sidecar), never an end user, and the response contains no
tenant/business data, only aggregate request counts and latencies.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.dependencies import get_resources
from app.bootstrap import ApplicationResources
from app.models.enums import JobPriority
from app.observability.metrics import JOB_DEAD_LETTER_COUNT, JOB_DELAYED_COUNT, JOB_QUEUE_DEPTH

__all__ = ["router"]

router = APIRouter(tags=["metrics"])

#: See app.api.routers.admin_jobs's identical constant/rationale.
_KNOWN_QUEUE_NAMES = ("default", "escalation")


def _refresh_job_queue_metrics(resources: ApplicationResources) -> None:
    """Refresh the job system's external-state gauges from Redis/Postgres.

    Called immediately before ``generate_latest()`` on every scrape — the
    standard Prometheus pattern for a gauge reflecting current state of
    an external system, rather than something incremented from
    request-handling code. A failure here (e.g. Redis briefly
    unreachable) must never break the rest of the scrape, so it is
    swallowed; the gauges simply keep their last-known values.
    """
    try:
        if resources.redis_job_queue is not None:
            for queue_name in _KNOWN_QUEUE_NAMES:
                for priority in JobPriority:
                    JOB_QUEUE_DEPTH.labels(queue_name=queue_name, priority=priority.value).set(
                        resources.redis_job_queue.queue_depth(
                            queue_name=queue_name, priority=priority
                        )
                    )
                JOB_DELAYED_COUNT.labels(queue_name=queue_name).set(
                    resources.redis_job_queue.delayed_count(queue_name=queue_name)
                )
        dead_letter_counts = resources.job_repository.count_dead_letter_by_queue()
        for queue_name in _KNOWN_QUEUE_NAMES:
            JOB_DEAD_LETTER_COUNT.labels(queue_name=queue_name).set(
                dead_letter_counts.get(queue_name, 0)
            )
    except Exception:  # noqa: BLE001 - a scrape must never fail because of this refresh
        pass


@router.get("/metrics", include_in_schema=False)
def get_metrics(resources: ApplicationResources = Depends(get_resources)) -> Response:
    """Return every registered metric in Prometheus's text exposition format.

    Args:
        resources: Used to refresh the job system's queue-depth/dead-
            letter gauges immediately before generating the response.

    Returns:
        The current state of every metric in
        ``app.observability.metrics``, plus the Python process metrics
        ``prometheus_client`` registers by default (GC stats, memory).
    """
    _refresh_job_queue_metrics(resources)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
