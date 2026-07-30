"""A Redis-backed, TTL-bounded memoizing cache.

Drop-in replacement for ``app.utils.cache.TTLCache``'s
``get_or_compute(key, compute)`` interface, so
``app.utils.cache.cached_method`` (and every analytics engine that uses
it) works identically regardless of which backend is wired in. Unlike
``TTLCache`` — explicitly documented as single-process-only — this class
shares one cache across every application instance, which is the actual
production gap it closes: ``app.analytics.analytics_engine.AnalyticsEngine``
and ``app.analytics.operational_engine.OperationalAnalyticsEngine`` both
already build fully-qualified, tenant-scoped cache keys via
``cached_method`` (function name plus every call argument, including
``company_id``) — this class only swaps the *storage*, so that existing,
already-reviewed key-scoping logic is inherited unchanged, not
reimplemented.

**Trust boundary**: values are serialized with ``pickle``. This is safe
here specifically because every cached value is a frozen DTO dataclass
constructed exclusively by this codebase's own server-side analytics
code — never deserialized from user/network input — the same trust
boundary under which Django's default cache backend, for example, uses
pickle. Do not reuse this class to cache anything derived from
unauthenticated or externally-supplied data without re-examining that
assumption.
"""

from __future__ import annotations

import hashlib
import pickle
from collections.abc import Callable, Hashable
from typing import TypeVar

import redis

__all__ = ["RedisCache"]

T = TypeVar("T")


class RedisCache:
    """A Redis-backed memoizing cache with a fixed TTL, namespaced per owner.

    Args:
        client: A connected Redis client.
        namespace: A short, unique label for this cache's owner (e.g.
            ``"analytics_engine"``, ``"operational_analytics_engine"``),
            so multiple engines sharing one Redis instance never read or
            overwrite each other's entries.
        ttl_seconds: How long a computed value remains valid. ``<= 0``
            disables caching entirely (every call recomputes), matching
            ``TTLCache``'s identical behavior.
    """

    def __init__(self, *, client: redis.Redis, namespace: str, ttl_seconds: float) -> None:
        self._client = client
        self._namespace = namespace
        self._ttl_seconds = ttl_seconds

    def _redis_key(self, key: Hashable) -> str:
        digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()
        return f"cache:{self._namespace}:{digest}"

    def get_or_compute(self, key: Hashable, compute: Callable[[], T]) -> T:
        """Return the cached value for ``key``, computing and storing it if absent or expired.

        Args:
            key: The cache key. Must be hashable and ``repr()``-stable.
            compute: Invoked to produce the value on a cache miss/expiry
                or a Redis connectivity failure (fail-open: a cache
                outage degrades to "always recompute," never an error
                surfaced to the caller).

        Returns:
            The cached or freshly computed value.
        """
        if self._ttl_seconds <= 0:
            return compute()

        redis_key = self._redis_key(key)
        try:
            # Synchronous client only (app.utils.redis_client), so this is
            # always a plain `str | None`, never awaitable.
            cached: str | None = self._client.get(redis_key)  # type: ignore[assignment]
        except redis.RedisError:
            return compute()
        if cached is not None:
            try:
                # nosec B301 - internal-only trust boundary: every cached
                # value is produced exclusively by this codebase's own
                # compute() calls, never deserialized from user/network
                # input. See this module's docstring for the full rationale.
                return pickle.loads(bytes.fromhex(cached))  # type: ignore[no-any-return] # nosec B301
            except (pickle.PickleError, ValueError):
                # A corrupt or cross-version-incompatible cached blob is
                # treated as a miss, never an error — the source of
                # truth is always `compute()`, this is only ever a
                # performance optimization over it.
                pass

        value = compute()
        try:
            serialized = pickle.dumps(value).hex()
            self._client.setex(redis_key, int(self._ttl_seconds) or 1, serialized)
        except redis.RedisError:
            pass
        return value
