"""The Docker ``HEALTHCHECK`` command for an ``app.jobs.worker`` container.

Run with ``python -m app.jobs.healthcheck``. Workers have no HTTP server
of their own to probe (unlike the backend, which exposes
``/api/v1/health/live``) — see ``docker-compose.production.yml``'s
``worker-default``/``worker-escalation`` services — so liveness is
instead determined by whether this worker's heartbeat key
(``RedisJobQueue.record_heartbeat``, refreshed once per loop iteration)
is still present in Redis: a hung or crashed worker stops refreshing it,
and it expires after 30 seconds.

Exits ``0`` (healthy) if the heartbeat is present, ``1`` otherwise —
including if Redis itself cannot be reached, or if ``REDIS_URL`` is not
configured at all (a worker process without Redis configured is already a
misconfiguration ``app.jobs.worker`` itself refuses to start under, so
this script reports it as unhealthy rather than vacuously healthy).
"""

from __future__ import annotations

import socket
import sys

import redis

from app.config.settings import load_settings
from app.jobs.redis_queue import RedisJobQueue
from app.utils.redis_client import create_redis_client


def check() -> bool:
    """Return whether this worker's heartbeat is currently present."""
    settings = load_settings()
    if not settings.redis.enabled:
        return False
    try:
        client = create_redis_client(settings.redis.url)  # type: ignore[arg-type]
        redis_queue = RedisJobQueue(client=client)
        return redis_queue.heartbeat_exists(hostname=socket.gethostname())
    except redis.RedisError:
        return False


if __name__ == "__main__":
    sys.exit(0 if check() else 1)
