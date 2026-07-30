"""Unit tests for ``app.utils.redis_cache.RedisCache`` (production
infrastructure layer), exercised against ``fakeredis`` so no real Redis
server is required.
"""

from __future__ import annotations

import dataclasses

import fakeredis
import pytest

from app.utils.redis_cache import RedisCache

pytestmark = pytest.mark.unit


@dataclasses.dataclass(frozen=True)
class _Metric:
    """Module-level (picklable) stand-in for a real analytics DTO."""

    total: int


def _cache(*, ttl_seconds: float, namespace: str = "test") -> RedisCache:
    client = fakeredis.FakeRedis(decode_responses=True)
    return RedisCache(client=client, namespace=namespace, ttl_seconds=ttl_seconds)


class TestRedisCache:
    def test_a_second_call_within_the_ttl_returns_the_cached_value(self):
        cache = _cache(ttl_seconds=60.0)
        calls = []

        def compute():
            calls.append(1)
            return "value"

        first = cache.get_or_compute("key", compute)
        second = cache.get_or_compute("key", compute)

        assert first == "value"
        assert second == "value"
        assert len(calls) == 1

    def test_different_keys_are_computed_independently(self):
        cache = _cache(ttl_seconds=60.0)

        a = cache.get_or_compute("a", lambda: "A")
        b = cache.get_or_compute("b", lambda: "B")

        assert a == "A"
        assert b == "B"

    def test_a_zero_ttl_disables_caching_entirely(self):
        cache = _cache(ttl_seconds=0.0)
        calls = []

        def compute():
            calls.append(1)
            return len(calls)

        first = cache.get_or_compute("key", compute)
        second = cache.get_or_compute("key", compute)

        assert first == 1
        assert second == 2

    def test_caches_a_frozen_dataclass_value_via_pickling(self):
        cache = _cache(ttl_seconds=60.0)
        calls = []

        def compute():
            calls.append(1)
            return _Metric(total=42)

        first = cache.get_or_compute("key", compute)
        second = cache.get_or_compute("key", compute)

        assert first == second == _Metric(total=42)
        assert len(calls) == 1

    def test_different_namespaces_sharing_one_client_do_not_collide(self):
        client = fakeredis.FakeRedis(decode_responses=True)
        cache_a = RedisCache(client=client, namespace="a", ttl_seconds=60.0)
        cache_b = RedisCache(client=client, namespace="b", ttl_seconds=60.0)

        cache_a.get_or_compute("key", lambda: "from-a")
        result = cache_b.get_or_compute("key", lambda: "from-b")

        assert result == "from-b"

    def test_an_exception_from_compute_is_never_cached(self):
        cache = _cache(ttl_seconds=60.0)
        calls = []

        def compute():
            calls.append(1)
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            cache.get_or_compute("key", compute)
        with pytest.raises(ValueError, match="boom"):
            cache.get_or_compute("key", compute)

        assert len(calls) == 2

    def test_a_redis_connectivity_failure_fails_open_to_recompute(self):
        import redis

        class _BrokenClient:
            def get(self, key):
                raise redis.RedisError("connection refused")

            def setex(self, key, ttl, value):
                raise redis.RedisError("connection refused")

        cache = RedisCache(client=_BrokenClient(), namespace="test", ttl_seconds=60.0)
        calls = []

        def compute():
            calls.append(1)
            return "value"

        result = cache.get_or_compute("key", compute)

        assert result == "value"
        assert len(calls) == 1
