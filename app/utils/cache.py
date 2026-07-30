"""A generic, in-process, TTL-bounded memoizing cache.

Mirrors ``app.utils.rate_limiter``'s identical "generic, framework-
agnostic primitive lives in ``app.utils``" precedent — this module knows
nothing about HTTP, FastAPI, or the Analytics Layer; ``cached_method`` and
the ``TTLCache`` it wraps are reusable anywhere a short-lived, per-process
memoization is useful.

Single-process-only, like ``InMemoryRateLimiter``: a multi-instance
deployment gets independent caches per instance rather than a shared one.
For read-mostly, naturally-a-few-seconds-stale analytics figures (the
motivating use case — see ``app.analytics.analytics_engine.AnalyticsEngine``
and ``app.analytics.operational_engine.OperationalAnalyticsEngine``), this
is an acceptable trade-off, consistent with this codebase's existing
"no new infrastructure dependency for a single, low-volume need" stance —
introducing Redis or another shared cache purely for this would be
disproportionate.
"""

from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable, Hashable
from typing import Any, Protocol, TypeVar, runtime_checkable

__all__ = ["ResponseCache", "TTLCache", "cached_method"]

T = TypeVar("T")


@runtime_checkable
class ResponseCache(Protocol):
    """Structural interface shared by ``TTLCache`` and
    ``app.utils.redis_cache.RedisCache``.

    Lets any caller that constructs a ``_response_cache`` (e.g.
    ``app.analytics.analytics_engine.AnalyticsEngine``) accept either
    backend interchangeably — ``app.bootstrap`` selects which concrete
    class to build based on ``AppSettings.redis.enabled``, and the engine
    itself never needs to know which one it was given.
    """

    def get_or_compute(self, key: Hashable, compute: Callable[[], T]) -> T:
        """Return the cached value for ``key``, computing it on a miss."""
        ...


class TTLCache:
    """A thread-safe, fixed-TTL, in-process memoizing cache.

    Tracks ``(expires_at, value)`` per key in a plain dict, matching
    ``InMemoryRateLimiter``'s own simplicity — adequate for a low-volume,
    read-mostly cache and avoids pulling in a third-party caching library
    or an external store (Redis or similar) for this single need.
    """

    def __init__(self, *, ttl_seconds: float) -> None:
        """Initialize the cache.

        Args:
            ttl_seconds: How long a computed value remains valid before
                the next lookup for the same key recomputes it.
        """
        self._ttl_seconds = ttl_seconds
        self._store: dict[Hashable, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._key_locks: dict[Hashable, threading.Lock] = {}

    def get_or_compute(self, key: Hashable, compute: Callable[[], T]) -> T:
        """Return the cached value for ``key``, computing and storing it if absent or expired.

        Concurrent misses for the *same* key are serialized on a per-key
        lock rather than each independently calling ``compute``: on a
        cold cache, opening a page that fires several requests sharing
        one expensive underlying computation (e.g. the Analytics page's
        Intelligence tab, whose KPI/SLA/bottleneck cards and AI-insight
        cards all resolve through the same ``get_bottlenecks``/
        ``get_sla_metrics`` call) previously triggered one independent,
        full computation per concurrent request — a cache stampede that
        multiplied the number of round trips to the database for no
        benefit, since every caller wanted the identical result. Only the
        first caller for a given key actually computes; every other
        concurrent caller for that same key waits and then reads the
        result the first caller just stored. Different keys never block
        each other — only same-key contention is serialized.

        Args:
            key: The cache key. Must be hashable.
            compute: Invoked to produce the value on a cache miss/expiry.
                Not called at all on a cache hit.

        Returns:
            The cached or freshly computed value.
        """
        if self._ttl_seconds <= 0:
            # Caching disabled outright — skips the store entirely
            # (rather than storing with a zero/negative TTL) so a very
            # fast repeated call within the same clock tick can never
            # coincidentally read back a stale value.
            return compute()

        hit: tuple[float, T] | None = self._read(key)
        if hit is not None:
            return hit[1]

        with self._lock:
            key_lock = self._key_locks.setdefault(key, threading.Lock())

        with key_lock:
            # Re-check: another thread may have just finished computing
            # this exact key while we were waiting for key_lock.
            hit = self._read(key)
            if hit is not None:
                return hit[1]

            value = compute()
            with self._lock:
                self._store[key] = (time.monotonic() + self._ttl_seconds, value)
            return value

    def _read(self, key: Hashable) -> tuple[float, T] | None:
        """Return ``(expires_at, value)`` if ``key`` has a live entry, else ``None``."""
        with self._lock:
            entry = self._store.get(key)
        if entry is not None and entry[0] > time.monotonic():
            return entry
        return None


def cached_method(func: Callable[..., T]) -> Callable[..., T]:
    """Memoize an instance method's result via a per-instance ``TTLCache``.

    The decorated instance must expose a ``_response_cache: TTLCache``
    attribute (constructed once in ``__init__``, so its TTL and lifetime
    are owned by the instance, not shared process-wide). The cache key is
    the method name plus every positional and keyword argument — true of
    every parameter these Analytics Layer methods ordinarily accept
    (``UUID``, ``str | None``, ``datetime | None``, enum, ``int``). One
    method (``AnalyticsEngine.get_workload_summary``) accepts an optional,
    unhashable ``Sequence`` argument for its own internal-reuse callers
    (``OperationalAnalyticsEngine``, avoiding a duplicate fetch — see that
    parameter's own docstring); a call shaped that way transparently
    bypasses the cache rather than raising, so this decorator is safe to
    apply to every public method uniformly regardless of its parameters.

    Args:
        func: The method to memoize.

    Returns:
        A wrapped method with identical signature and behavior on a
        cache miss or an unhashable argument, serving a cached result
        only on a genuine hit.
    """

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> T:
        try:
            key: Hashable = (func.__name__, args, tuple(sorted(kwargs.items())))
            hash(key)
        except TypeError:
            return func(self, *args, **kwargs)
        return self._response_cache.get_or_compute(key, lambda: func(self, *args, **kwargs))

    return wrapper
