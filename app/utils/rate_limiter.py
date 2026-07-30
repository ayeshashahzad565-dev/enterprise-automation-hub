"""A generic, in-process, fixed-window rate limiter.

Framework-agnostic (no FastAPI/Starlette import), matching
``app.utils.retry``'s identical "generic, reusable resilience primitive
lives in ``app.utils``" precedent — this module knows nothing about
HTTP, IP addresses, or ``ApplicationResources``; ``app.api.rate_limiting``
is the thin, FastAPI-specific glue built on top of it, for the two
public invitation endpoints Milestone 9 introduces enforcement for.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Protocol, runtime_checkable

__all__ = ["RateLimitExceededError", "InMemoryRateLimiter", "RateLimiter"]

#: The minimum ``Retry-After`` value ever reported, so a caller is never
#: told to retry in under a second even when the arithmetic result is a
#: small fraction (e.g. a hit that just aged out of the window a moment
#: ago).
_MIN_RETRY_AFTER_SECONDS = 1.0


class RateLimitExceededError(Exception):
    """Raised when a caller has exceeded a configured rate limit.

    Carries ``retry_after_seconds`` so a caller (typically an HTTP
    exception handler) can report a standard ``Retry-After`` value, per
    RFC 6585.
    """

    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__(f"Rate limit exceeded; retry after {retry_after_seconds:.0f}s.")
        self.retry_after_seconds = retry_after_seconds


@runtime_checkable
class RateLimiter(Protocol):
    """Structural interface shared by ``InMemoryRateLimiter`` and
    ``app.utils.redis_rate_limiter.RedisRateLimiter``.

    Lets ``app.bootstrap`` and ``app.api.rate_limiting`` treat either
    backend interchangeably; which concrete class gets constructed is an
    ``app.bootstrap``-only decision (``AppSettings.redis.enabled``).
    """

    def check(self, key: str) -> None:
        """Record one hit for ``key`` and enforce the configured limit."""
        ...


class InMemoryRateLimiter:
    """A thread-safe, fixed-window, in-process rate limiter.

    Tracks request timestamps per bucket key in a plain dict, evicting
    entries older than ``window_seconds`` on every check — adequate at
    low request volumes, and avoids pulling in a third-party
    rate-limiting library or an external store (Redis or similar) for a
    single pair of low-volume endpoints. See
    ``app.api.rate_limiting``'s module docstring for the known
    single-process-only limitation this implies in a multi-instance
    deployment, and why that trade-off was accepted rather than
    introducing new infrastructure.

    A fresh instance should be constructed once per long-lived owner
    (e.g. once per ``ApplicationResources``) — never held as a
    module-level singleton — so that independent owners (in particular,
    independent test app instances) never share rate-limit state.
    """

    def __init__(self, *, limit: int, window_seconds: float) -> None:
        """Initialize the limiter.

        Args:
            limit: The maximum number of requests permitted per bucket
                within ``window_seconds``. ``0`` blocks every request
                unconditionally (a valid, if extreme, configuration).
            window_seconds: The sliding window's width, in seconds.
        """
        self._limit = limit
        self._window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Record one hit for ``key`` and enforce the configured limit.

        Args:
            key: The bucket identifier (e.g. a client IP address).

        Raises:
            RateLimitExceededError: If this hit would exceed the
                configured limit within the current window.
        """
        now = time.monotonic()
        cutoff = now - self._window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self._limit:
                # `limit <= 0` means every request is rejected before any
                # hit is ever recorded, so `hits` can be empty here —
                # there is no oldest hit to age out, so the full window
                # is the only meaningful "try again in" estimate.
                retry_after = hits[0] + self._window_seconds - now if hits else self._window_seconds
                raise RateLimitExceededError(max(retry_after, _MIN_RETRY_AFTER_SECONDS))
            hits.append(now)
