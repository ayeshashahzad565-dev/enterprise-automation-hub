"""Unit tests for ``app.utils.redis_rate_limiter.RedisRateLimiter``
(production infrastructure layer), exercised against ``fakeredis`` so no
real Redis server is required.
"""

from __future__ import annotations

import fakeredis
import pytest

from app.utils.rate_limiter import RateLimitExceededError
from app.utils.redis_rate_limiter import RedisRateLimiter

pytestmark = pytest.mark.unit


def _limiter(*, limit: int, window_seconds: float, namespace: str = "test") -> RedisRateLimiter:
    client = fakeredis.FakeRedis(decode_responses=True)
    return RedisRateLimiter(
        client=client, namespace=namespace, limit=limit, window_seconds=window_seconds
    )


class TestRedisRateLimiter:
    def test_allows_requests_up_to_the_configured_limit(self):
        limiter = _limiter(limit=3, window_seconds=60)

        limiter.check("1.2.3.4")
        limiter.check("1.2.3.4")
        limiter.check("1.2.3.4")

    def test_rejects_the_request_that_exceeds_the_limit(self):
        limiter = _limiter(limit=2, window_seconds=60)
        limiter.check("1.2.3.4")
        limiter.check("1.2.3.4")

        with pytest.raises(RateLimitExceededError):
            limiter.check("1.2.3.4")

    def test_a_limit_of_zero_blocks_every_request(self):
        limiter = _limiter(limit=0, window_seconds=60)

        with pytest.raises(RateLimitExceededError):
            limiter.check("1.2.3.4")

    def test_different_keys_have_independent_budgets(self):
        limiter = _limiter(limit=1, window_seconds=60)
        limiter.check("1.2.3.4")

        limiter.check("5.6.7.8")

        with pytest.raises(RateLimitExceededError):
            limiter.check("1.2.3.4")

    def test_different_namespaces_sharing_one_client_do_not_collide(self):
        client = fakeredis.FakeRedis(decode_responses=True)
        read_limiter = RedisRateLimiter(client=client, namespace="read", limit=1, window_seconds=60)
        write_limiter = RedisRateLimiter(
            client=client, namespace="write", limit=1, window_seconds=60
        )

        read_limiter.check("user-1")
        # Same key, different namespace: independent budget.
        write_limiter.check("user-1")

        with pytest.raises(RateLimitExceededError):
            read_limiter.check("user-1")

    def test_retry_after_is_never_reported_below_one_second(self):
        limiter = _limiter(limit=1, window_seconds=10)
        limiter.check("1.2.3.4")

        with pytest.raises(RateLimitExceededError) as exc_info:
            limiter.check("1.2.3.4")

        assert exc_info.value.retry_after_seconds >= 1.0
