"""Unit tests for ``app.jobs.redis_queue.RedisJobQueue``, exercised
against ``fakeredis`` so no real Redis server is required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import fakeredis
import pytest

from app.jobs.redis_queue import RedisJobQueue
from app.models.enums import JobPriority

pytestmark = pytest.mark.unit


def _queue() -> RedisJobQueue:
    client = fakeredis.FakeRedis(decode_responses=True)
    return RedisJobQueue(client=client)


class TestReadyQueue:
    def test_dequeue_returns_none_when_nothing_is_ready(self):
        queue = _queue()

        result = queue.dequeue(
            queue_names=["default"], priority_order=[JobPriority.HIGH], timeout_seconds=1
        )

        assert result is None

    def test_a_pushed_job_round_trips_through_dequeue(self):
        queue = _queue()

        queue.push_ready(queue_name="default", priority=JobPriority.NORMAL, job_id="job-1")
        result = queue.dequeue(
            queue_names=["default"], priority_order=[JobPriority.NORMAL], timeout_seconds=1
        )

        assert result == "job-1"

    def test_jobs_are_dequeued_fifo_within_one_priority(self):
        queue = _queue()
        queue.push_ready(queue_name="default", priority=JobPriority.NORMAL, job_id="first")
        queue.push_ready(queue_name="default", priority=JobPriority.NORMAL, job_id="second")

        first = queue.dequeue(
            queue_names=["default"], priority_order=[JobPriority.NORMAL], timeout_seconds=1
        )
        second = queue.dequeue(
            queue_names=["default"], priority_order=[JobPriority.NORMAL], timeout_seconds=1
        )

        assert first == "first"
        assert second == "second"

    def test_dequeue_respects_the_given_priority_order(self):
        queue = _queue()
        queue.push_ready(queue_name="default", priority=JobPriority.LOW, job_id="low-job")
        queue.push_ready(queue_name="default", priority=JobPriority.HIGH, job_id="high-job")

        result = queue.dequeue(
            queue_names=["default"],
            priority_order=[JobPriority.HIGH, JobPriority.NORMAL, JobPriority.LOW],
            timeout_seconds=1,
        )

        assert result == "high-job"

    def test_dequeue_falls_back_to_a_lower_priority_when_reversed(self):
        queue = _queue()
        queue.push_ready(queue_name="default", priority=JobPriority.LOW, job_id="low-job")

        # Simulates the worker's periodic starvation-avoidance reversal:
        # even with LOW listed first, HIGH (empty) is checked but LOW
        # still wins since it's the only key with data.
        result = queue.dequeue(
            queue_names=["default"],
            priority_order=[JobPriority.LOW, JobPriority.NORMAL, JobPriority.HIGH],
            timeout_seconds=1,
        )

        assert result == "low-job"

    def test_queues_of_different_names_are_isolated(self):
        queue = _queue()
        queue.push_ready(queue_name="escalation", priority=JobPriority.HIGH, job_id="esc-job")

        result = queue.dequeue(
            queue_names=["default"], priority_order=[JobPriority.HIGH], timeout_seconds=1
        )

        assert result is None

    def test_dequeue_can_poll_multiple_queue_names_at_once(self):
        queue = _queue()
        queue.push_ready(queue_name="escalation", priority=JobPriority.HIGH, job_id="esc-job")

        result = queue.dequeue(
            queue_names=["default", "escalation"],
            priority_order=[JobPriority.HIGH],
            timeout_seconds=1,
        )

        assert result == "esc-job"

    def test_queue_depth_reflects_ready_list_length(self):
        queue = _queue()
        queue.push_ready(queue_name="default", priority=JobPriority.NORMAL, job_id="a")
        queue.push_ready(queue_name="default", priority=JobPriority.NORMAL, job_id="b")

        assert queue.queue_depth(queue_name="default", priority=JobPriority.NORMAL) == 2
        assert queue.queue_depth(queue_name="default", priority=JobPriority.HIGH) == 0


class TestDelayedPromotion:
    def test_a_delayed_job_is_not_ready_before_its_time(self):
        queue = _queue()
        queue.push_delayed(
            queue_name="default",
            priority=JobPriority.NORMAL,
            job_id="future-job",
            ready_at=datetime.now(UTC) + timedelta(hours=1),
        )

        assert queue.delayed_count(queue_name="default") == 1
        result = queue.dequeue(
            queue_names=["default"], priority_order=[JobPriority.NORMAL], timeout_seconds=1
        )
        assert result is None

    def test_promote_due_moves_an_eligible_job_onto_its_ready_list(self):
        queue = _queue()
        queue.push_delayed(
            queue_name="default",
            priority=JobPriority.HIGH,
            job_id="due-job",
            ready_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        promoted = queue.promote_due(queue_name="default", now=datetime.now(UTC))

        assert promoted == 1
        assert queue.delayed_count(queue_name="default") == 0
        assert queue.queue_depth(queue_name="default", priority=JobPriority.HIGH) == 1
        result = queue.dequeue(
            queue_names=["default"], priority_order=[JobPriority.HIGH], timeout_seconds=1
        )
        assert result == "due-job"

    def test_promote_due_does_not_move_a_not_yet_eligible_job(self):
        queue = _queue()
        queue.push_delayed(
            queue_name="default",
            priority=JobPriority.NORMAL,
            job_id="future-job",
            ready_at=datetime.now(UTC) + timedelta(hours=1),
        )

        promoted = queue.promote_due(queue_name="default", now=datetime.now(UTC))

        assert promoted == 0
        assert queue.delayed_count(queue_name="default") == 1


class TestHeartbeat:
    def test_heartbeat_exists_is_false_before_it_is_recorded(self):
        queue = _queue()

        assert queue.heartbeat_exists(hostname="worker-1") is False

    def test_heartbeat_exists_is_true_after_it_is_recorded(self):
        queue = _queue()

        queue.record_heartbeat(hostname="worker-1")

        assert queue.heartbeat_exists(hostname="worker-1") is True
