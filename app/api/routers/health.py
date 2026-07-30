"""``GET /health``, ``GET /health/live``, ``GET /health/ready`` — liveness,
readiness, and (legacy) combined health checks.

Per ``docs/deployment.md`` Section 15.2, ``GET /health`` returns ``200
{"status": "ok"}`` when the instance can reach its Supabase connection,
and ``503`` otherwise, so the load balancer can remove an unreachable
instance from rotation. Section 15.5 additionally documents an
instance-level Scheduler status field (``scheduler_active``), included
here too, giving operators a way to confirm exactly one instance in a
fleet reports ``true`` at any time without a separate monitoring surface.
With Redis-backed Scheduler leader election active
(``docs/scheduler_distributed_coordination.md``), this reflects live,
self-correcting leadership rather than a static designation — an
accompanying ``scheduler_leader_election`` field (``"redis"`` or
``"static"``) makes which mode is active explicit.

``/health/live`` and ``/health/ready`` (production infrastructure layer)
give a container orchestrator (Docker Compose, Kubernetes) the standard
two-probe split those platforms expect:

- **Liveness** (``/health/live``): "is this process fundamentally broken
  and should be restarted?" Performs no dependency check at all — a
  transient Supabase or Redis outage should not cause a healthy process
  to be killed and restarted (that would not fix the outage, and churns
  the fleet for no benefit), so liveness only ever reports the process
  itself is running.
- **Readiness** (``/health/ready``): "should this instance currently
  receive traffic?" Performs the same Supabase-reachability check
  ``GET /health`` always has, plus a Redis ping when Redis is configured
  (``AppSettings.redis.enabled``) — a Redis outage degrades rate
  limiting/caching/queued-email delivery, so an instance that depends on
  Redis being reachable is reported not-ready until it recovers.

``GET /health`` itself is unchanged (delegates to the same readiness
logic it always has) so no existing consumer or documentation reference
breaks.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.dependencies import get_database_client, get_resources
from app.bootstrap import ApplicationResources
from app.database.client import DatabaseClient

__all__ = ["router", "build_readiness_body"]

router = APIRouter(tags=["health"])


def build_readiness_body(
    database_client: DatabaseClient, resources: ApplicationResources
) -> tuple[dict[str, object], int]:
    """Build the readiness response body and status code.

    Args:
        database_client: Used for the Supabase reachability check —
            ``health_check()`` never raises, only reports ``True``/``False``.
        resources: Used to read ``scheduler_stats``/``leader_election``
            and, if configured, ping Redis.

    Returns:
        A ``(body, status_code)`` pair.
    """
    database_reachable = database_client.health_check()

    redis_reachable: bool | None = None
    if resources.redis_client is not None:
        try:
            redis_reachable = bool(resources.redis_client.ping())
        except Exception:  # noqa: BLE001 - any client/connection error means "not reachable"
            redis_reachable = False

    ready = database_reachable and redis_reachable is not False
    if resources.leader_election is not None:
        # Redis-backed dynamic election: every instance registers jobs,
        # so `scheduler_stats is not None` alone no longer distinguishes
        # "leading" from "merely competing" — `is_leader` reflects this
        # instance's own current belief, fail-safe toward `False` (see
        # `app.scheduler.leader_election.LeaderElection`).
        scheduler_active = resources.leader_election.is_leader
        scheduler_leader_election = "redis"
    else:
        scheduler_active = resources.scheduler_stats is not None
        scheduler_leader_election = "static"
    body: dict[str, object] = {
        "status": "ok" if ready else "degraded",
        "database": "ok" if database_reachable else "unreachable",
        "scheduler_active": scheduler_active,
        "scheduler_leader_election": scheduler_leader_election,
    }
    if redis_reachable is not None:
        body["redis"] = "ok" if redis_reachable else "unreachable"
        # Informational only — the job system's live dispatch layer rides
        # on the same Redis connection just checked above; no separate
        # pass/fail semantics of its own (worker liveness is each
        # worker's own Docker healthcheck's job, not this instance's).
        body["job_queue"] = "ok" if redis_reachable else "unreachable"
    return body, (200 if ready else 503)


@router.get("/health/live")
def get_liveness() -> JSONResponse:
    """Report whether this process is up.

    Performs no dependency check — see this module's docstring for why
    liveness must never fail merely because a downstream dependency is
    temporarily unreachable.

    Returns:
        ``200 {"status": "alive"}`` unconditionally (if this handler can
        run at all, the process is, by definition, alive).
    """
    return JSONResponse(content={"status": "alive"}, status_code=200)


@router.get("/health/ready")
def get_readiness(
    database_client: DatabaseClient = Depends(get_database_client),
    resources: ApplicationResources = Depends(get_resources),
) -> JSONResponse:
    """Report whether this instance should currently receive traffic.

    Args:
        database_client: Used for the reachability check itself.
        resources: Used to read ``scheduler_stats``/``leader_election`` and,
            if configured, ping Redis.

    Returns:
        ``200`` if every configured dependency is reachable; ``503``
        otherwise (see ``build_readiness_body``).
    """
    body, status_code = build_readiness_body(database_client, resources)
    return JSONResponse(content=body, status_code=status_code)


@router.get("/health")
def get_health(
    database_client: DatabaseClient = Depends(get_database_client),
    resources: ApplicationResources = Depends(get_resources),
) -> JSONResponse:
    """Return this instance's liveness, Supabase reachability, and Scheduler status.

    Kept for backward compatibility with existing consumers/load-balancer
    configuration — identical to ``GET /health/ready`` (see this module's
    docstring for why the two are the same check under different names).

    Args:
        database_client: Used for the reachability check itself —
            ``health_check()`` never raises, only reports ``True``/``False``.
        resources: Used to read ``scheduler_stats``/``leader_election`` and,
            if configured, ping Redis.

    Returns:
        ``200 {"status": "ok", "database": "ok", "scheduler_active": bool}``
        if every configured dependency is reachable; ``503`` with
        ``"status": "degraded"`` otherwise. Deliberately not wrapped in
        the general ``app.utils.response`` envelope: a load balancer's
        health check is conventionally the one endpoint kept as small
        and dependency-free as possible.
    """
    body, status_code = build_readiness_body(database_client, resources)
    return JSONResponse(content=body, status_code=status_code)
