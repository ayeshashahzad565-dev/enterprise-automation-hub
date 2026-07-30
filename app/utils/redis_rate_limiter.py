"""A Redis-backed, sliding-window rate limiter.

Drop-in, multi-instance-safe replacement for
``app.utils.rate_limiter.InMemoryRateLimiter``: same public surface
(``check(key: str) -> None``, raising the same
``app.utils.rate_limiter.RateLimitExceededError``), so every existing
caller (``app.api.rate_limiting``) works unmodified regardless of which
implementation ``app.bootstrap`` wires in. ``InMemoryRateLimiter``'s own
docstring already documents its single-process limitation in a
multi-instance deployment; this class is the fix, selected instead of it
only when ``AppSettings.redis.enabled`` is ``True`` (see
``app.bootstrap.build_application_resources``) — when Redis is not
configured, nothing in this module is ever constructed or imported at
runtime.

Implemented as a Redis sorted set per bucket key (members are
per-request-unique, scores are the hit's timestamp), pruned and checked
atomically via a single Lua script so concurrent requests across many
application processes can never race past the limit — the same
correctness guarantee ``InMemoryRateLimiter`` gets for free from a single
process's GIL-protected lock, reproduced here at the Redis-server level.
"""

from __future__ import annotations

import time
import uuid

import redis

from app.utils.rate_limiter import RateLimitExceededError

__all__ = ["RedisRateLimiter"]

#: See ``app.utils.rate_limiter``'s identical constant for why a
#: caller is never told to retry in under a second.
_MIN_RETRY_AFTER_SECONDS = 1.0

#: KEYS[1] = bucket key; ARGV[1] = now; ARGV[2] = window_seconds;
#: ARGV[3] = limit; ARGV[4] = unique member for this hit.
#: Returns -1 if the hit is allowed (and has already been recorded), or
#: the number of seconds to wait before retrying if it is rejected (the
#: hit is *not* recorded in that case, matching InMemoryRateLimiter.check
#: only appending on success).
_CHECK_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local cutoff = now - window

redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)

if count >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    if oldest[2] then
        return tostring(tonumber(oldest[2]) + window - now)
    end
    return tostring(window)
end

redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window))
return "-1"
"""


class RedisRateLimiter:
    """A thread/process-safe, fixed-limit sliding-window rate limiter, backed by Redis.

    Every bucket key is namespaced (``rate_limit:{namespace}:{key}``) so
    multiple limiters (read/write/upload/notification-poll/invitation)
    sharing one Redis instance never collide with each other, matching
    ``app.bootstrap``'s existing "one ``InMemoryRateLimiter`` instance per
    limiter category" construction.
    """

    def __init__(
        self, *, client: redis.Redis, namespace: str, limit: int, window_seconds: float
    ) -> None:
        """Initialize the limiter.

        Args:
            client: A connected Redis client (see
                ``app.utils.redis_client.create_redis_client``).
            namespace: A short, unique label for this limiter category
                (e.g. ``"read"``, ``"write"``, ``"invitation"``),
                prefixed onto every bucket key.
            limit: The maximum number of requests permitted per bucket
                within ``window_seconds``. ``0`` blocks every request
                unconditionally, matching ``InMemoryRateLimiter``.
            window_seconds: The sliding window's width, in seconds.
        """
        self._client = client
        self._namespace = namespace
        self._limit = limit
        self._window_seconds = window_seconds
        self._check_script = client.register_script(_CHECK_SCRIPT)

    def _bucket_key(self, key: str) -> str:
        return f"rate_limit:{self._namespace}:{key}"

    def check(self, key: str) -> None:
        """Record one hit for ``key`` and enforce the configured limit.

        Args:
            key: The bucket identifier (e.g. a user id or client IP).

        Raises:
            RateLimitExceededError: If this hit would exceed the
                configured limit within the current window.
        """
        now = time.time()
        member = f"{now}:{uuid.uuid4()}"
        result = self._check_script(
            keys=[self._bucket_key(key)],
            args=[now, self._window_seconds, self._limit, member],
        )
        retry_after = float(result)
        if retry_after >= 0:
            raise RateLimitExceededError(max(retry_after, _MIN_RETRY_AFTER_SECONDS))
