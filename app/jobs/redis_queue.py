"""The Redis-backed live dispatch layer for the job system.

Holds no independent meaning of its own — every key here is an ephemeral
pointer (``{"job_id", "priority"}``) into the durable ``jobs`` table
(``app.database.repositories.job_repository``). Three kinds of Redis
structure, per ``queue_name`` (``"default"``, ``"escalation"`` in the
reference deployment):

- **Ready lists**, one per ``(queue_name, priority)`` pair
  (``eah:jobs:ready:{queue_name}:{priority}``) — plain Redis lists,
  LPUSH/BRPOP, giving FIFO order within a priority tier.
- **A delayed sorted set**, one per ``queue_name``
  (``eah:jobs:delayed:{queue_name}``) — used both for a job explicitly
  enqueued for the future and for a failed job's scheduled retry. Scored
  by the Unix timestamp the job becomes eligible; promoted back onto its
  ready list by ``promote_due`` (an atomic Lua script), which
  ``app.jobs.worker`` runs from a lightweight background thread roughly
  once a second.
- **A heartbeat key**, one per worker hostname
  (``eah:jobs:heartbeat:{hostname}``) — a short-TTL string a worker
  refreshes every loop iteration, read by ``app.jobs.healthcheck`` (the
  Docker ``HEALTHCHECK`` command).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

import redis

from app.models.enums import JobPriority

__all__ = ["RedisJobQueue"]

#: Redundant execution of the promoter script across every worker of the
#: same ``queue_name`` is intentional and harmless: the script's own
#: atomicity (a single Redis command) means only one execution actually
#: moves a given delayed member, so no coordination beyond "every worker
#: just runs it" is needed.
_PROMOTE_DUE_SCRIPT = """
local delayed_key = KEYS[1]
local now = tonumber(ARGV[1])
local ready_prefix = ARGV[2]

local due = redis.call('ZRANGEBYSCORE', delayed_key, '-inf', now)
local promoted = 0
for _, member in ipairs(due) do
    local ok, decoded = pcall(cjson.decode, member)
    if ok and decoded.priority then
        redis.call('LPUSH', ready_prefix .. decoded.priority, member)
        redis.call('ZREM', delayed_key, member)
        promoted = promoted + 1
    end
end
return promoted
"""

_HEARTBEAT_TTL_SECONDS = 30


def _ready_key(queue_name: str, priority: str) -> str:
    return f"eah:jobs:ready:{queue_name}:{priority}"


def _ready_key_prefix(queue_name: str) -> str:
    return f"eah:jobs:ready:{queue_name}:"


def _delayed_key(queue_name: str) -> str:
    return f"eah:jobs:delayed:{queue_name}"


def _heartbeat_key(hostname: str) -> str:
    return f"eah:jobs:heartbeat:{hostname}"


class RedisJobQueue:
    """The live-dispatch primitives every worker and producer share.

    Args:
        client: A connected Redis client (``app.utils.redis_client.create_redis_client``).
    """

    def __init__(self, *, client: redis.Redis) -> None:
        self._client = client
        self._promote_due_script = client.register_script(_PROMOTE_DUE_SCRIPT)

    def push_ready(self, *, queue_name: str, priority: JobPriority, job_id: str) -> None:
        """Push a job directly onto its ready list, eligible immediately.

        Args:
            queue_name: Which worker role should consume this job.
            priority: The job's priority tier.
            job_id: The job's ``jobs.id``, as a string.
        """
        envelope = json.dumps({"job_id": job_id, "priority": priority.value})
        self._client.lpush(_ready_key(queue_name, priority.value), envelope)

    def push_delayed(
        self, *, queue_name: str, priority: JobPriority, job_id: str, ready_at: datetime
    ) -> None:
        """Schedule a job to become eligible at a future time.

        Used both for an explicitly delayed enqueue and for a failed
        job's backoff-computed retry time.

        Args:
            queue_name: Which worker role should consume this job.
            priority: The job's priority tier, applied when it is later
                promoted onto its ready list.
            job_id: The job's ``jobs.id``, as a string.
            ready_at: When this job becomes eligible for dequeue.
        """
        envelope = json.dumps({"job_id": job_id, "priority": priority.value})
        self._client.zadd(_delayed_key(queue_name), {envelope: ready_at.timestamp()})

    def promote_due(self, *, queue_name: str, now: datetime) -> int:
        """Move every delayed job whose time has come onto its ready list.

        Args:
            queue_name: Which queue's delayed set to sweep.
            now: The current time; every delayed member scored at or
                before this instant is promoted.

        Returns:
            The number of jobs promoted.
        """
        result = self._promote_due_script(
            keys=[_delayed_key(queue_name)],
            args=[now.timestamp(), _ready_key_prefix(queue_name)],
        )
        return int(result)

    def dequeue(
        self,
        *,
        queue_names: Sequence[str],
        priority_order: Sequence[JobPriority],
        timeout_seconds: int = 5,
    ) -> str | None:
        """Block (up to ``timeout_seconds``) for the next ready job.

        Args:
            queue_names: Which worker role(s)' ready lists to poll —
                more than one only for the ``"all"`` worker role
                (``app.jobs.worker``'s development-convenience mode that
                consumes every queue from a single process).
            priority_order: The priority tiers to check, in the order to
                check them, applied across every queue in
                ``queue_names`` before moving to the next priority tier
                (i.e. every queue's ``HIGH`` list is checked before any
                queue's ``NORMAL`` list) — ``BRPOP``'s multi-key
                semantics return from the first *listed* key with data,
                giving strict priority for free. The caller
                (``app.jobs.worker``) is responsible for periodically
                reversing this order to bound lower-priority starvation
                under sustained load; this method applies no ordering
                logic of its own.
            timeout_seconds: How long to block before returning ``None``.

        Returns:
            The dequeued job's ``jobs.id`` (as a string), or ``None`` if
            the timeout elapsed with nothing ready.
        """
        keys = [
            _ready_key(queue_name, priority.value)
            for priority in priority_order
            for queue_name in queue_names
        ]
        # See app.queue.redis_task_queue's identical comment: this
        # codebase only ever constructs the synchronous redis-py client,
        # so BRPOP's result is always a plain tuple or None.
        result: tuple[str, str] | None = self._client.brpop(  # type: ignore[assignment]
            keys, timeout=timeout_seconds
        )
        if result is None:
            return None
        _, raw = result
        envelope = json.loads(raw)
        return str(envelope["job_id"])

    def queue_depth(self, *, queue_name: str, priority: JobPriority) -> int:
        """The number of jobs currently ready (not delayed) for one priority tier."""
        # See dequeue's identical comment: always a plain int for this
        # codebase's synchronous-only redis-py client.
        length: int = self._client.llen(_ready_key(queue_name, priority.value))  # type: ignore[assignment]
        return length

    def delayed_count(self, *, queue_name: str) -> int:
        """The number of jobs currently waiting in the delayed set."""
        count: int = self._client.zcard(_delayed_key(queue_name))  # type: ignore[assignment]
        return count

    def record_heartbeat(self, *, hostname: str) -> None:
        """Refresh this worker's heartbeat key, read by ``app.jobs.healthcheck``.

        Args:
            hostname: This worker process's hostname (``socket.gethostname()``).
        """
        self._client.set(_heartbeat_key(hostname), "1", ex=_HEARTBEAT_TTL_SECONDS)

    def heartbeat_exists(self, *, hostname: str) -> bool:
        """Whether ``hostname``'s heartbeat key is currently present (not expired)."""
        return bool(self._client.exists(_heartbeat_key(hostname)))
