"""Unit tests for ``app.scheduler.distributed_lock``, exercised against
``fakeredis`` so no real Redis server is required (matching
``tests/unit/test_jobs_redis_queue.py``'s established convention for
Redis-backed components in this codebase).
"""

from __future__ import annotations

import time

import fakeredis
import pytest

from app.scheduler.distributed_lock import NullDistributedLock, RedisDistributedLock

pytestmark = pytest.mark.unit


def _client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


class TestRedisDistributedLockAcquireRelease:
    def test_acquire_succeeds_when_the_key_is_free(self):
        lock = RedisDistributedLock(client=_client(), key="test-lock", ttl_seconds=5)

        assert lock.acquire() is True
        assert lock.owned is True

    def test_a_second_contender_cannot_acquire_while_the_first_holds_it(self):
        client = _client()
        lock_a = RedisDistributedLock(client=client, key="test-lock", ttl_seconds=5, token="a")
        lock_b = RedisDistributedLock(client=client, key="test-lock", ttl_seconds=5, token="b")

        assert lock_a.acquire() is True
        assert lock_b.acquire() is False
        assert lock_b.owned is False

    def test_release_lets_another_contender_acquire(self):
        client = _client()
        lock_a = RedisDistributedLock(client=client, key="test-lock", ttl_seconds=5, token="a")
        lock_b = RedisDistributedLock(client=client, key="test-lock", ttl_seconds=5, token="b")
        lock_a.acquire()

        lock_a.release()

        assert lock_b.acquire() is True

    def test_release_when_not_owned_is_a_safe_no_op(self):
        lock = RedisDistributedLock(client=_client(), key="test-lock", ttl_seconds=5)

        lock.release()  # never acquired — must not raise

        assert lock.owned is False

    def test_owned_is_false_before_any_acquire_attempt(self):
        lock = RedisDistributedLock(client=_client(), key="test-lock", ttl_seconds=5)

        assert lock.owned is False


class TestRedisDistributedLockExpiry:
    def test_the_lock_expires_on_its_own_after_its_ttl(self):
        client = _client()
        lock_a = RedisDistributedLock(client=client, key="test-lock", ttl_seconds=0.5, token="a")
        lock_b = RedisDistributedLock(client=client, key="test-lock", ttl_seconds=0.5, token="b")
        lock_a.acquire()

        time.sleep(0.8)

        assert lock_b.acquire() is True


class TestRedisDistributedLockExtend:
    def test_extend_succeeds_and_resets_the_ttl_while_held(self):
        client = _client()
        lock_a = RedisDistributedLock(client=client, key="test-lock", ttl_seconds=0.5, token="a")
        lock_b = RedisDistributedLock(client=client, key="test-lock", ttl_seconds=0.5, token="b")
        lock_a.acquire()

        assert lock_a.extend(2) is True
        time.sleep(0.8)  # past the original TTL, well within the extended one

        assert lock_b.acquire() is False, "extend should have reset the TTL, not merely added to it"

    def test_extend_fails_when_the_lock_is_not_held(self):
        lock = RedisDistributedLock(client=_client(), key="test-lock", ttl_seconds=5)

        assert lock.extend(5) is False


class TestNullDistributedLock:
    def test_always_acquires(self):
        lock = NullDistributedLock()

        assert lock.acquire() is True
        assert lock.acquire() is True, "acquiring twice never contends with itself"

    def test_release_is_a_no_op(self):
        NullDistributedLock().release()  # must not raise

    def test_extend_always_succeeds(self):
        assert NullDistributedLock().extend(30) is True

    def test_owned_is_always_true(self):
        assert NullDistributedLock().owned is True
