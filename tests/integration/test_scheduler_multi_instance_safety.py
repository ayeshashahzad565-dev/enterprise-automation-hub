"""Integration proof: multiple backend instances cannot execute the same
scheduled job simultaneously.

Two independent ``SchedulerCoordinator`` + ``LeaderElection`` pairs are
constructed, each standing in for one backend container, sharing a single
``fakeredis.FakeRedis`` client — standing in for the one real Redis server
every replica in a production deployment points at
(``docker-compose.production.yml``'s ``backend``/``backend-2``). Real
``threading.Thread``s drive both "instances" concurrently, exactly as two
separate OS processes would. ``fakeredis`` implements the same ``SET NX
PX``/Lua-scripted locking semantics a real Redis server does (verified in
``tests/unit/test_scheduler_distributed_lock.py`` and
``test_scheduler_leader_election.py``), so this is a faithful, CI-safe
substitute for standing up two real containers and a real Redis instance —
matching this codebase's own established convention for testing
Redis-backed components (``tests/unit/test_jobs_redis_queue.py``).

See ``docs/scheduler_distributed_coordination.md`` for the mechanism this
proves: Redis-backed leader election (only one instance's ticks ever
execute) plus a second, independent per-job distributed lock (true mutual
exclusion even in a simulated split-brain window where both instances
believe themselves to be leader).
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import fakeredis
import pytest

from app.scheduler.distributed_lock import RedisDistributedLock
from app.scheduler.interfaces import ExecutionContext, ExecutionResult
from app.scheduler.leader_election import LeaderElection
from app.scheduler.registry import JobRegistry
from app.scheduler.scheduler import SchedulerCoordinator

pytestmark = pytest.mark.integration

_LEADER_LOCK_KEY = "eah:scheduler:leader"


class _FakeBackend:
    """A ``SchedulerBackend`` that never ticks on its own — every
    execution in this test is driven explicitly via ``trigger_now``, so
    no real APScheduler thread or wall-clock interval timing is needed.
    """

    def __init__(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def add_job(self, job_id, func, *, interval_seconds):
        pass

    def remove_job(self, job_id):
        pass

    def get_next_run_time(self, job_id):
        return None

    def start(self):
        self._running = True

    def shutdown(self, *, wait):
        self._running = False


class _RecordingJob:
    """A ``ScheduledJob`` recording every concurrent execution's start/end,
    so a test can assert no two recorded intervals ever overlapped.
    """

    def __init__(self, name: str, *, run_duration_seconds: float = 0.3) -> None:
        self._name = name
        self._run_duration_seconds = run_duration_seconds
        self.lock = threading.Lock()
        self.currently_running_count = 0
        self.max_concurrent_observed = 0
        self.total_run_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def interval_seconds(self) -> int:
        return 3600

    def run(self, context: ExecutionContext) -> ExecutionResult:
        with self.lock:
            self.currently_running_count += 1
            self.max_concurrent_observed = max(
                self.max_concurrent_observed, self.currently_running_count
            )
            self.total_run_count += 1

        time.sleep(self._run_duration_seconds)

        with self.lock:
            self.currently_running_count -= 1

        now = datetime.now(UTC)
        return ExecutionResult(job_name=self._name, started_at=now, finished_at=now, success=True)


def _make_instance(
    *, redis_client: fakeredis.FakeRedis, instance_id: str, job: _RecordingJob, leader_ttl: float
) -> tuple[SchedulerCoordinator, LeaderElection]:
    """Build one simulated backend instance: its own coordinator and
    leader-election participant, both wired to the shared fake Redis —
    exactly the wiring ``app.bootstrap.build_application_resources``
    performs for a real instance.
    """
    leader_election = LeaderElection(
        lock=RedisDistributedLock(
            client=redis_client, key=_LEADER_LOCK_KEY, ttl_seconds=leader_ttl, token=instance_id
        ),
        renewal_interval_seconds=leader_ttl / 3,
        instance_id=instance_id,
    )
    coordinator = SchedulerCoordinator(
        backend=_FakeBackend(),
        registry=JobRegistry(),
        leader_check=lambda: leader_election.is_leader,
        distributed_lock_factory=lambda job_name: RedisDistributedLock(
            client=redis_client, key=f"eah:scheduler:job-lock:{job_name}", ttl_seconds=5
        ),
    )
    coordinator.register_job(job)
    return coordinator, leader_election


def _wait_until(predicate, *, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class TestLeaderElectionGatesExecution:
    def test_only_the_elected_leaders_tick_actually_executes(self):
        redis_client = fakeredis.FakeRedis(decode_responses=True)
        job_a = _RecordingJob("shared-job", run_duration_seconds=0.2)
        job_b = _RecordingJob("shared-job", run_duration_seconds=0.2)
        coordinator_a, election_a = _make_instance(
            redis_client=redis_client, instance_id="instance-a", job=job_a, leader_ttl=1.0
        )
        coordinator_b, election_b = _make_instance(
            redis_client=redis_client, instance_id="instance-b", job=job_b, leader_ttl=1.0
        )

        election_a.start()
        election_b.start()
        try:
            assert _wait_until(lambda: election_a.is_leader or election_b.is_leader)
            time.sleep(0.3)
            assert election_a.is_leader != election_b.is_leader, "exactly one must be leader"

            # Both instances' schedulers fire "simultaneously," as they
            # would on the same wall-clock interval in production.
            coordinator_a.trigger_now("shared-job")
            coordinator_b.trigger_now("shared-job")
            time.sleep(0.5)

            leader_job = job_a if election_a.is_leader else job_b
            follower_job = job_b if election_a.is_leader else job_a
            assert leader_job.total_run_count == 1
            assert follower_job.total_run_count == 0
        finally:
            election_a.stop()
            election_b.stop()


class TestDistributedLockPreventsDuplicateExecutionEvenUnderSplitBrain:
    def test_two_instances_that_both_believe_they_are_leader_still_cannot_run_the_job_concurrently(
        self,
    ):
        """The scenario ``docs/scheduler_distributed_coordination.md``
        discloses as the residual risk leader election alone cannot rule
        out: both instances' `leader_check` returns True at the same
        moment (a real split-brain window). This proves the second,
        independent per-job Redis lock still prevents the job's body
        from ever running on both instances concurrently.
        """
        redis_client = fakeredis.FakeRedis(decode_responses=True)
        job_a = _RecordingJob("shared-job", run_duration_seconds=0.4)
        job_b = _RecordingJob("shared-job", run_duration_seconds=0.4)

        def distributed_lock_factory(job_name: str) -> RedisDistributedLock:
            return RedisDistributedLock(
                client=redis_client, key=f"eah:scheduler:job-lock:{job_name}", ttl_seconds=5
            )

        coordinator_a = SchedulerCoordinator(
            backend=_FakeBackend(),
            registry=JobRegistry(),
            leader_check=lambda: True,  # simulated split-brain: always "leader"
            distributed_lock_factory=distributed_lock_factory,
        )
        coordinator_b = SchedulerCoordinator(
            backend=_FakeBackend(),
            registry=JobRegistry(),
            leader_check=lambda: True,  # simulated split-brain: always "leader"
            distributed_lock_factory=distributed_lock_factory,
        )
        coordinator_a.register_job(job_a)
        coordinator_b.register_job(job_b)

        thread_a = threading.Thread(target=lambda: coordinator_a.trigger_now("shared-job"))
        thread_b = threading.Thread(target=lambda: coordinator_b.trigger_now("shared-job"))
        thread_a.start()
        thread_b.start()
        thread_a.join()
        thread_b.join()
        time.sleep(0.6)  # let whichever one acquired the lock finish running

        total_runs = job_a.total_run_count + job_b.total_run_count
        assert total_runs == 1, (
            "exactly one instance's job-lock acquire must succeed; the other must be "
            "skipped outright, even though both instances believe they are leader"
        )
        assert max(job_a.max_concurrent_observed, job_b.max_concurrent_observed) == 1


class TestCrashRecovery:
    def test_a_crashed_instances_job_lock_is_reclaimed_and_the_job_runs_again(self):
        """Instance A acquires the job lock and "crashes" (never
        releases it). Instance B must still be able to acquire the same
        lock and run the job once instance A's lock TTL expires — proving
        recovery with no manual intervention, per this document's
        "configurable lock expiry" / "graceful recovery after crashes"
        requirements.
        """
        redis_client = fakeredis.FakeRedis(decode_responses=True)
        short_ttl = 0.4
        crashed_lock = RedisDistributedLock(
            client=redis_client,
            key="eah:scheduler:job-lock:shared-job",
            ttl_seconds=short_ttl,
            token="instance-a",
        )
        assert crashed_lock.acquire() is True  # instance A starts the job...
        # ...and crashes: no release() is ever called.

        job_b = _RecordingJob("shared-job", run_duration_seconds=0.1)
        coordinator_b = SchedulerCoordinator(
            backend=_FakeBackend(),
            registry=JobRegistry(),
            distributed_lock_factory=lambda job_name: RedisDistributedLock(
                client=redis_client, key=f"eah:scheduler:job-lock:{job_name}", ttl_seconds=5
            ),
        )
        coordinator_b.register_job(job_b)

        # Immediately after the "crash," the lock is still held (within
        # its TTL) — instance B must not be able to run yet.
        coordinator_b.trigger_now("shared-job")
        time.sleep(0.15)
        assert job_b.total_run_count == 0
        stats = coordinator_b.get_statistics("shared-job")
        assert stats is not None
        assert stats.skipped_distributed_lock_count == 1

        time.sleep(short_ttl)  # wait out the crashed instance's lock TTL

        coordinator_b.trigger_now("shared-job")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and job_b.total_run_count == 0:
            time.sleep(0.02)

        assert job_b.total_run_count == 1, (
            "instance B must recover and run the job once the crashed instance's "
            "lock has expired, with no manual intervention"
        )
