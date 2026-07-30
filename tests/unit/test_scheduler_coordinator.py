"""Unit tests for ``app.scheduler.scheduler.SchedulerCoordinator``.

No dedicated test file previously existed for this module (a gap flagged
during the job system's design work). Covers job registration/statistics
and the new ``trigger_now`` method (used by the admin job-management
API, ``POST /admin/scheduled-jobs/{job_name}/trigger-now``) — a fake
in-memory ``SchedulerBackend`` is used throughout so no real APScheduler
background thread is ever started.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import fakeredis
import pytest

from app.scheduler.distributed_lock import RedisDistributedLock
from app.scheduler.exceptions import JobRegistrationError
from app.scheduler.interfaces import ExecutionContext, ExecutionResult
from app.scheduler.registry import JobRegistry
from app.scheduler.scheduler import SchedulerCoordinator

pytestmark = pytest.mark.unit


class _FakeBackend:
    """A ``SchedulerBackend`` that records registrations but never ticks on its own."""

    def __init__(self) -> None:
        self.added: dict[str, tuple] = {}
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def add_job(self, job_id, func, *, interval_seconds):
        self.added[job_id] = (func, interval_seconds)

    def remove_job(self, job_id):
        self.added.pop(job_id, None)

    def get_next_run_time(self, job_id):
        return None

    def start(self):
        self._running = True

    def shutdown(self, *, wait):
        self._running = False


class _FakeJob:
    """A minimal ``ScheduledJob`` whose ``run`` optionally invokes a callback."""

    def __init__(self, name: str, *, interval_seconds: int = 60, on_run=None) -> None:
        self._name = name
        self._interval_seconds = interval_seconds
        self._on_run = on_run

    @property
    def name(self) -> str:
        return self._name

    @property
    def interval_seconds(self) -> int:
        return self._interval_seconds

    def run(self, context: ExecutionContext) -> ExecutionResult:
        if self._on_run is not None:
            self._on_run()
        now = datetime.now(UTC)
        return ExecutionResult(
            job_name=self._name,
            started_at=now,
            finished_at=now,
            success=True,
            items_processed=1,
        )


def _coordinator() -> SchedulerCoordinator:
    return SchedulerCoordinator(backend=_FakeBackend(), registry=JobRegistry())


def _wait_for_run_count(coordinator: SchedulerCoordinator, job_name: str, *, at_least: int = 1):
    deadline = time.monotonic() + 2
    stats = coordinator.get_statistics(job_name)
    while stats is not None and stats.run_count < at_least and time.monotonic() < deadline:
        time.sleep(0.01)
        stats = coordinator.get_statistics(job_name)
    return stats


class TestRegisterAndStatistics:
    def test_get_statistics_returns_none_for_an_unregistered_job(self):
        coordinator = _coordinator()

        assert coordinator.get_statistics("nope") is None

    def test_register_job_initializes_zeroed_statistics(self):
        coordinator = _coordinator()

        coordinator.register_job(_FakeJob("job-a"))

        stats = coordinator.get_statistics("job-a")
        assert stats is not None
        assert stats.run_count == 0
        assert stats.currently_running is False

    def test_get_all_statistics_includes_every_registered_job(self):
        coordinator = _coordinator()
        coordinator.register_job(_FakeJob("job-a"))
        coordinator.register_job(_FakeJob("job-b"))

        all_stats = coordinator.get_all_statistics()

        assert set(all_stats.keys()) == {"job-a", "job-b"}


class TestTriggerNow:
    def test_trigger_now_raises_for_an_unregistered_job(self):
        coordinator = _coordinator()

        with pytest.raises(JobRegistrationError):
            coordinator.trigger_now("nope")

    def test_trigger_now_returns_before_the_job_finishes(self):
        coordinator = _coordinator()
        release = threading.Event()
        coordinator.register_job(_FakeJob("job-a", on_run=release.wait))

        started = time.monotonic()
        coordinator.trigger_now("job-a")
        elapsed = time.monotonic() - started

        assert elapsed < 1.0, "trigger_now blocked waiting for the job to complete"
        release.set()

    def test_trigger_now_executes_the_job_and_updates_statistics(self):
        coordinator = _coordinator()
        ran = threading.Event()
        coordinator.register_job(_FakeJob("job-a", on_run=ran.set))

        coordinator.trigger_now("job-a")

        assert ran.wait(timeout=2), "triggered job did not run within timeout"
        stats = _wait_for_run_count(coordinator, "job-a")
        assert stats is not None
        assert stats.run_count == 1
        assert stats.success_count == 1

    def test_a_second_trigger_while_the_first_is_running_is_skipped_not_queued(self):
        coordinator = _coordinator()
        started = threading.Event()
        release = threading.Event()

        def _slow_run() -> None:
            started.set()
            release.wait(timeout=2)

        coordinator.register_job(_FakeJob("job-a", on_run=_slow_run))

        coordinator.trigger_now("job-a")
        assert started.wait(timeout=2)

        coordinator.trigger_now("job-a")  # must be skipped: the lock is already held
        time.sleep(0.1)
        release.set()

        stats = _wait_for_run_count(coordinator, "job-a")
        assert stats is not None
        assert stats.run_count == 1
        assert stats.skipped_overlap_count == 1


class TestLeaderCheck:
    def test_a_tick_is_skipped_and_counted_when_this_instance_is_not_leader(self):
        coordinator = SchedulerCoordinator(
            backend=_FakeBackend(), registry=JobRegistry(), leader_check=lambda: False
        )
        ran = threading.Event()
        coordinator.register_job(_FakeJob("job-a", on_run=ran.set))

        coordinator.trigger_now("job-a")
        time.sleep(0.2)

        assert not ran.is_set(), "the job body must never run when this instance is not leader"
        stats = coordinator.get_statistics("job-a")
        assert stats is not None
        assert stats.run_count == 0
        assert stats.skipped_not_leader_count == 1

    def test_a_tick_runs_normally_when_leader_check_returns_true(self):
        coordinator = SchedulerCoordinator(
            backend=_FakeBackend(), registry=JobRegistry(), leader_check=lambda: True
        )
        coordinator.register_job(_FakeJob("job-a"))

        coordinator.trigger_now("job-a")

        stats = _wait_for_run_count(coordinator, "job-a")
        assert stats is not None
        assert stats.run_count == 1
        assert stats.skipped_not_leader_count == 0

    def test_leader_check_is_re_evaluated_on_every_tick_not_cached(self):
        is_leader = {"value": False}
        coordinator = SchedulerCoordinator(
            backend=_FakeBackend(),
            registry=JobRegistry(),
            leader_check=lambda: is_leader["value"],
        )
        coordinator.register_job(_FakeJob("job-a"))

        coordinator.trigger_now("job-a")
        time.sleep(0.2)
        stats = coordinator.get_statistics("job-a")
        assert stats is not None
        assert stats.run_count == 0

        is_leader["value"] = True
        coordinator.trigger_now("job-a")

        stats = _wait_for_run_count(coordinator, "job-a")
        assert stats is not None
        assert stats.run_count == 1


class TestDistributedLock:
    def test_a_tick_is_skipped_and_counted_when_another_instance_holds_the_jobs_lock(self):
        client = fakeredis.FakeRedis(decode_responses=True)
        # Simulates another instance already running this exact job:
        # acquire the same Redis key this coordinator's own
        # distributed_lock_factory will build, and never release it.
        other_instance_lock = RedisDistributedLock(
            client=client, key="job-a-lock", ttl_seconds=5, token="other-instance"
        )
        assert other_instance_lock.acquire() is True

        coordinator = SchedulerCoordinator(
            backend=_FakeBackend(),
            registry=JobRegistry(),
            distributed_lock_factory=lambda job_name: RedisDistributedLock(
                client=client, key=f"{job_name}-lock", ttl_seconds=5
            ),
        )
        ran = threading.Event()
        coordinator.register_job(_FakeJob("job-a", on_run=ran.set))

        coordinator.trigger_now("job-a")
        time.sleep(0.2)

        assert not ran.is_set(), "job body must never run while another instance holds the lock"
        stats = coordinator.get_statistics("job-a")
        assert stats is not None
        assert stats.run_count == 0
        assert stats.skipped_distributed_lock_count == 1

    def test_a_tick_runs_and_releases_the_distributed_lock_when_uncontended(self):
        client = fakeredis.FakeRedis(decode_responses=True)
        coordinator = SchedulerCoordinator(
            backend=_FakeBackend(),
            registry=JobRegistry(),
            distributed_lock_factory=lambda job_name: RedisDistributedLock(
                client=client, key=f"{job_name}-lock", ttl_seconds=5
            ),
        )
        coordinator.register_job(_FakeJob("job-a"))

        coordinator.trigger_now("job-a")

        stats = _wait_for_run_count(coordinator, "job-a")
        assert stats is not None
        assert stats.run_count == 1
        assert stats.skipped_distributed_lock_count == 0
        # Released after running — a subsequent tick must be able to
        # acquire the same key again (proves this coordinator releases
        # its own distributed lock, not just skips re-acquiring it).
        other_instance_lock = RedisDistributedLock(client=client, key="job-a-lock", ttl_seconds=5)
        assert other_instance_lock.acquire() is True
