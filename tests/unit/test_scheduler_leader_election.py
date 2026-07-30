"""Unit tests for ``app.scheduler.leader_election.LeaderElection``, exercised
against ``fakeredis`` shared across multiple ``LeaderElection`` instances —
simulating multiple backend processes contending for the same Redis lock,
matching this codebase's established ``fakeredis``-based convention for
Redis-backed components (``tests/unit/test_jobs_redis_queue.py``).
"""

from __future__ import annotations

import time

import fakeredis
import pytest

from app.scheduler.distributed_lock import RedisDistributedLock
from app.scheduler.leader_election import LeaderElection

pytestmark = pytest.mark.unit

_LOCK_KEY = "test-scheduler-leader"


def _election(client: fakeredis.FakeRedis, *, instance_id: str, ttl_seconds: float) -> LeaderElection:
    return LeaderElection(
        lock=RedisDistributedLock(
            client=client, key=_LOCK_KEY, ttl_seconds=ttl_seconds, token=instance_id
        ),
        renewal_interval_seconds=ttl_seconds / 3,
        instance_id=instance_id,
    )


def _wait_until(predicate, *, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class TestSingleInstance:
    def test_a_lone_instance_becomes_leader_after_starting(self):
        client = fakeredis.FakeRedis(decode_responses=True)
        election = _election(client, instance_id="a", ttl_seconds=1)

        election.start()
        try:
            assert _wait_until(lambda: election.is_leader)
        finally:
            election.stop()

    def test_is_leader_is_false_before_start(self):
        election = _election(
            fakeredis.FakeRedis(decode_responses=True), instance_id="a", ttl_seconds=1
        )

        assert election.is_leader is False


class TestMultipleInstancesCompeting:
    def test_only_one_of_two_concurrently_started_instances_becomes_leader(self):
        client = fakeredis.FakeRedis(decode_responses=True)
        election_a = _election(client, instance_id="a", ttl_seconds=1)
        election_b = _election(client, instance_id="b", ttl_seconds=1)

        election_a.start()
        election_b.start()
        try:
            assert _wait_until(lambda: election_a.is_leader or election_b.is_leader)
            time.sleep(0.3)  # let a few more renewal ticks pass
            assert election_a.is_leader != election_b.is_leader
        finally:
            election_a.stop()
            election_b.stop()

    def test_a_graceful_stop_hands_off_leadership_immediately(self):
        client = fakeredis.FakeRedis(decode_responses=True)
        election_a = _election(client, instance_id="a", ttl_seconds=1)
        election_b = _election(client, instance_id="b", ttl_seconds=1)
        election_a.start()
        assert _wait_until(lambda: election_a.is_leader)
        election_b.start()

        election_a.stop()  # explicit release — must not require waiting out the TTL

        assert _wait_until(lambda: election_b.is_leader, timeout=1.0)
        election_b.stop()

    def test_a_crashed_leaders_lock_is_reclaimed_after_its_ttl_expires(self):
        client = fakeredis.FakeRedis(decode_responses=True)
        election_a = _election(client, instance_id="a", ttl_seconds=0.4)
        election_b = _election(client, instance_id="b", ttl_seconds=0.4)
        election_a.start()
        assert _wait_until(lambda: election_a.is_leader)

        # Simulate a crash: never call stop() (no explicit release), and
        # never let it renew again — this is exactly what happens if the
        # process running election_a dies without a graceful shutdown.
        election_a._stop_event.set()

        election_b.start()
        try:
            assert _wait_until(lambda: election_b.is_leader, timeout=2.0)
        finally:
            election_b.stop()


class TestFailSafeDirection:
    def test_a_renewal_failure_marks_leadership_lost_not_retained(self):
        client = fakeredis.FakeRedis(decode_responses=True)
        election = _election(client, instance_id="a", ttl_seconds=1)
        election.start()
        assert _wait_until(lambda: election.is_leader)

        # Another contender steals the key out from under this instance
        # (simulating the lock having already expired and been re-acquired
        # elsewhere) — the next renewal tick must observe this and flip
        # is_leader to False, never keep reporting True regardless.
        client.delete(_LOCK_KEY)
        client.set(_LOCK_KEY, "someone-else")

        assert _wait_until(lambda: not election.is_leader, timeout=2.0)
        election.stop()
