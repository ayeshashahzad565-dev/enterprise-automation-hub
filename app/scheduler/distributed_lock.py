"""Distributed locking primitive for cross-instance Scheduler coordination.

Per this package's design brief, ``SchedulerCoordinator``'s existing
``threading.Lock``-based overlap prevention (``scheduler.py``) only ever
protected a single process — it has no effect once more than one backend
instance is running (``docs/scheduler_distributed_coordination.md``). This
module adds the one new primitive both ``LeaderElection`` and
``SchedulerCoordinator``'s per-job locking build on: ``RedisDistributedLock``,
a thin wrapper around ``redis.lock.Lock`` — redis-py's own correct,
token-fenced, Lua-scripted distributed lock (``SET NX PX`` to acquire; a
Lua script that checks token ownership before ``PEXPIRE``/``DEL`` for
extend/release) — so this module hand-rolls no locking logic of its own.

``NullDistributedLock`` is the strict-fallback counterpart: it always
"acquires" successfully and never contends with anything, used whenever
Redis is not configured, so that absent ``REDIS_URL`` this package's
behavior is byte-for-byte what it was before this module existed —
the same convention every other Redis-backed component in this codebase
(``app.utils.redis_rate_limiter``, ``app.utils.redis_cache``, ``app.jobs``)
already follows.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import redis
from redis.exceptions import LockError, RedisError

__all__ = ["DistributedLock", "RedisDistributedLock", "NullDistributedLock"]

logger = logging.getLogger(__name__)


@runtime_checkable
class DistributedLock(Protocol):
    """Structural interface for a single named distributed lock.

    Both ``LeaderElection`` (one long-lived lock, periodically renewed)
    and ``SchedulerCoordinator`` (one short-lived lock per job execution)
    depend only on this narrow protocol, never on ``redis.lock.Lock``
    directly — keeping Redis itself an implementation detail swappable
    for ``NullDistributedLock`` when Redis is not configured.
    """

    def acquire(self, *, blocking: bool = False) -> bool:
        """Attempt to acquire the lock.

        Args:
            blocking: Whether to block until the lock becomes available.
                Every caller in this package passes ``False`` — a
                scheduler tick that can't acquire its lock right now
                should be skipped, never queued.

        Returns:
            ``True`` if the lock was acquired, ``False`` otherwise. Never
            raises: a Redis-level failure is treated as "not acquired,"
            the fail-safe direction for coordination primitives (see this
            module's docstring).
        """
        ...

    def release(self) -> None:
        """Release the lock if currently held by this instance.

        Never raises: releasing a lock this instance does not (or no
        longer) own — for example, because its TTL already expired — is
        treated as a no-op, not an error, since the caller's own
        ``finally`` block should never itself fail because a best-effort
        cleanup step found nothing to clean up.
        """
        ...

    def extend(self, additional_seconds: float) -> bool:
        """Reset the lock's remaining TTL, if still held by this instance.

        Args:
            additional_seconds: The new TTL to set, in seconds, replacing
                whatever TTL remains (not added to it) — the renewal
                semantics ``LeaderElection`` needs: each successful
                renewal should reset the countdown to a full period, not
                accumulate.

        Returns:
            ``True`` if the lock was still held by this instance and its
            TTL was reset, ``False`` otherwise (including on any Redis
            error) — the caller (``LeaderElection``) treats ``False`` as
            "leadership lost," never as "assume still leader," per this
            package's fail-safe-to-non-leader design.
        """
        ...

    @property
    def owned(self) -> bool:
        """Whether this instance currently holds the lock."""
        ...


class RedisDistributedLock:
    """A ``DistributedLock`` backed by ``redis.lock.Lock``.

    One instance of this class corresponds to one named lock; it is not
    safe to share a single instance across threads that should be treated
    as independent contenders (each contender should construct its own,
    even against the same Redis key) — this matches ``redis.lock.Lock``'s
    own ``thread_local=True`` default, which this class relies on.
    """

    def __init__(
        self, *, client: redis.Redis, key: str, ttl_seconds: float, token: str | None = None
    ) -> None:
        """Construct a distributed lock for a specific Redis key.

        Args:
            client: The shared Redis client (``app.utils.redis_client``).
            key: The Redis key this lock is held under. Callers are
                responsible for namespacing (this package uses the
                ``eah:scheduler:`` prefix, matching ``app.jobs.redis_queue``'s
                own ``eah:jobs:`` convention).
            ttl_seconds: How long the lock is held for before it expires
                automatically if never renewed or released — the
                "graceful recovery after crash" backstop: a process that
                dies while holding this lock stops renewing it, and it
                expires on its own within this window.
            token: A fixed value to store as the lock's owner, rather
                than letting ``redis.lock.Lock`` generate a random UUID.
                Passing this instance's own identifier here means an
                operator can run ``redis-cli GET <key>`` and see exactly
                which instance currently holds it — purely an operational
                debugging aid; the underlying safety property (only the
                acquirer can release/extend) holds either way.
        """
        self._key = key
        self._ttl_seconds = ttl_seconds
        self._token = token.encode() if token is not None else None
        # thread_local=False: this lock's acquire/extend/release calls are
        # not guaranteed to all happen from the same thread (in
        # particular, ``LeaderElection`` acquires/renews from its own
        # background thread but may be released from whatever thread
        # calls ``LeaderElection.stop()``) — redis-py's default
        # ``thread_local=True`` stores the acquired token in
        # thread-local storage, which would make ``release()``/``extend()``
        # silently believe the lock is unowned when called from a
        # different thread than the one that acquired it.
        self._lock = client.lock(key, timeout=ttl_seconds, blocking=False, thread_local=False)
        self._logger = logging.getLogger(f"{__name__}.RedisDistributedLock")

    def acquire(self, *, blocking: bool = False) -> bool:
        """Attempt to acquire this lock. See ``DistributedLock.acquire``."""
        try:
            return bool(self._lock.acquire(blocking=blocking, token=self._token))
        except RedisError as exc:
            self._logger.warning(
                "Redis error acquiring lock '%s': %s", self._key, exc, extra={"lock_key": self._key}
            )
            return False

    def release(self) -> None:
        """Release this lock. See ``DistributedLock.release``."""
        try:
            self._lock.release()
        except LockError:
            # Not owned (never acquired, already released, or its TTL
            # already expired and was possibly claimed by someone else) —
            # a no-op, not an error, per this method's documented contract.
            pass
        except RedisError as exc:
            self._logger.warning(
                "Redis error releasing lock '%s': %s", self._key, exc, extra={"lock_key": self._key}
            )

    def extend(self, additional_seconds: float) -> bool:
        """Reset this lock's TTL. See ``DistributedLock.extend``."""
        try:
            return bool(self._lock.extend(additional_seconds, replace_ttl=True))
        except LockError:
            return False
        except RedisError as exc:
            self._logger.warning(
                "Redis error extending lock '%s': %s", self._key, exc, extra={"lock_key": self._key}
            )
            return False

    @property
    def owned(self) -> bool:
        """Whether this instance currently holds the lock."""
        try:
            return bool(self._lock.owned())
        except RedisError:
            return False


class NullDistributedLock:
    """A ``DistributedLock`` that always succeeds and never contends.

    Used whenever Redis is not configured, preserving this package's exact
    pre-Redis behavior: only the in-process ``threading.Lock`` (already in
    ``SchedulerCoordinator``) matters, with no cross-instance guarantee —
    which is correct here, since without Redis there is no cross-instance
    coordination to provide in the first place.
    """

    def acquire(self, *, blocking: bool = False) -> bool:
        """Always succeeds; nothing is actually locked. See ``DistributedLock.acquire``."""
        return True

    def release(self) -> None:
        """No-op. See ``DistributedLock.release``."""

    def extend(self, additional_seconds: float) -> bool:
        """Always succeeds; nothing is actually held. See ``DistributedLock.extend``."""
        return True

    @property
    def owned(self) -> bool:
        """Always ``True``: this lock is never actually contended."""
        return True
