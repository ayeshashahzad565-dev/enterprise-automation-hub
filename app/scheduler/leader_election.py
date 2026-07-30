"""Redis-backed dynamic leader election for multi-instance deployments.

Per ``docs/scheduler_distributed_coordination.md``, this replaces the old
purely-static ``SCHEDULER_LEADER`` designation (still the fallback when
Redis is not configured — see ``app.bootstrap``) with a real, self-healing
leadership protocol: every backend instance runs a ``LeaderElection`` on a
background thread, all continuously contending for the same Redis lock
(``app.scheduler.distributed_lock.DistributedLock``). Whichever instance
holds the lock renews it periodically; if that instance crashes or is
partitioned from Redis, its renewal simply stops happening, the lock's TTL
expires on its own, and another instance's next tick acquires it — leader
failover with no manual step, unlike the static designation it replaces.
"""

from __future__ import annotations

import logging
import threading

from app.scheduler.distributed_lock import DistributedLock

__all__ = ["LeaderElection"]

logger = logging.getLogger(__name__)


class LeaderElection:
    """Continuously contends for leadership of a single, named Redis lock.

    Construct one per backend instance, pointed at the same
    ``DistributedLock`` key across every instance in the deployment;
    ``start()`` begins a background thread that repeatedly attempts to
    acquire the lock (if not currently leader) or renew it (if currently
    leader), and ``is_leader`` reflects this instance's current belief
    about its own leadership at any moment — always fail-safe toward
    "not leader" (see this class's docstring and ``_tick``).
    """

    def __init__(
        self,
        *,
        lock: DistributedLock,
        renewal_interval_seconds: float,
        instance_id: str,
    ) -> None:
        """Initialize the election with its injected lock and timing.

        Args:
            lock: The ``DistributedLock`` this instance contends for.
                Typically a ``RedisDistributedLock`` bound to a shared
                key (``eah:scheduler:leader``) and a TTL
                (``SchedulerSettings.leader_lock_ttl_seconds``); every
                instance in the deployment must be constructed against
                the *same* key for election to mean anything.
            renewal_interval_seconds: How often the background thread
                ticks — attempting to acquire when not leader, or renew
                when leader. Should be meaningfully shorter than the
                lock's own TTL (this package uses ``ttl / 3``) so a
                transient single missed renewal, due to ordinary
                scheduling jitter, does not by itself cause a spurious
                leadership loss.
            instance_id: A human-readable identifier for this instance
                (hostname/pid/short-uuid), used only in log messages to
                make multi-instance troubleshooting legible.
        """
        self._lock = lock
        self._renewal_interval_seconds = renewal_interval_seconds
        self._instance_id = instance_id
        self._is_leader = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._logger = logging.getLogger(f"{__name__}.LeaderElection")

    @property
    def is_leader(self) -> bool:
        """Whether this instance currently believes it holds leadership.

        Reflects only the outcome of this instance's own most recent
        tick — never a live round-trip to Redis on read, so reading this
        property is always fast and never itself fails.
        """
        return self._is_leader

    def start(self) -> None:
        """Start the background election thread.

        Idempotent in effect for this package's usage (called exactly
        once per instance, from ``app.bootstrap``): starting twice would
        start two competing threads, so callers must not do that.
        """
        self._thread = threading.Thread(
            target=self._run_loop, name="scheduler-leader-election", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread and release leadership if held.

        Releasing explicitly here — rather than only waiting for the
        lock's TTL to expire — is what makes a graceful shutdown (a
        normal deploy/restart) hand off leadership immediately instead of
        leaving every other instance waiting out the full TTL window
        before a new leader can be elected.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._renewal_interval_seconds * 2)
        if self._is_leader:
            self._lock.release()
            self._is_leader = False
            self._logger.info(
                "Instance '%s' released Scheduler leadership on shutdown.", self._instance_id
            )

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._tick()
            self._stop_event.wait(self._renewal_interval_seconds)

    def _tick(self) -> None:
        """Attempt to acquire or renew leadership once.

        Fail-safe direction: any outcome other than a confirmed successful
        acquire/renew is treated as "not leader" (including a Redis error,
        which ``DistributedLock`` itself already translates into a
        ``False`` return rather than a raised exception) — this is what
        prevents a Redis outage from producing two simultaneous leaders
        once connectivity recovers: an instance that loses the ability to
        renew always assumes it has lost leadership, never that it might
        still hold it.
        """
        if self._is_leader:
            renewed = self._lock.extend(self._renewal_interval_seconds * 3)
            if not renewed:
                self._is_leader = False
                self._logger.warning(
                    "Instance '%s' failed to renew Scheduler leadership; "
                    "assuming leadership lost.",
                    self._instance_id,
                )
            return

        acquired = self._lock.acquire(blocking=False)
        if acquired:
            self._is_leader = True
            self._logger.info("Instance '%s' acquired Scheduler leadership.", self._instance_id)
