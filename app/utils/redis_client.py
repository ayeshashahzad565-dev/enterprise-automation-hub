"""Redis connection factory for the production infrastructure layer.

A single, thin construction point for the ``redis-py`` client, mirroring
``app.database.client.SupabaseClientFactory``'s "one factory, no
component reads a connection string directly" precedent. Every
Redis-backed component in this codebase (``app.utils.redis_rate_limiter``,
``app.utils.redis_cache``, ``app.jobs``) is constructed from the client
this module builds, never from a raw ``redis.Redis(...)`` call scattered
at each call site.

Nothing in this module is imported unless ``AppSettings.redis.enabled``
is ``True`` — a process that never sets ``REDIS_URL`` never touches this
module at runtime, keeping the "Redis is strictly optional" guarantee
intact even if the ``redis`` package were ever absent from an
environment's installed dependencies.
"""

from __future__ import annotations

import redis

__all__ = ["create_redis_client"]


def create_redis_client(url: str) -> redis.Redis:
    """Construct a Redis client for the given connection URL.

    Args:
        url: A ``redis://`` (or ``rediss://`` for TLS) connection URL.

    Returns:
        A ``redis.Redis`` instance with a connection pool, decoding
        responses to ``str`` (every value this codebase stores in Redis
        is either plain text or JSON, never raw binary), matching the
        synchronous style already used throughout this codebase's
        Supabase/repository layer (no async client is introduced).
    """
    return redis.Redis.from_url(url, decode_responses=True)
