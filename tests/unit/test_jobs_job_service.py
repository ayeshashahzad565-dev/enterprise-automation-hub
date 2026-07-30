"""Unit tests for ``app.jobs.job_service.JobService``.

Exercises the real ``RedisJobQueue`` against ``fakeredis`` (so the Redis
side is genuinely dispatched, not mocked) paired with a minimal in-memory
fake standing in for ``JobRepository`` (so no real Postgres/Supabase
client is required) — matching this codebase's existing convention of
faking only the persistence boundary while exercising the real Redis
wire behavior (e.g. ``tests/unit/test_redis_task_queue.py``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis
import pytest
import redis

from app.database.repositories.job_repository import JobRecord
from app.jobs.job_service import JobService
from app.jobs.redis_queue import RedisJobQueue
from app.models.enums import JobPriority

pytestmark = pytest.mark.unit


class _FakeJobRepository:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def create_job(
        self,
        *,
        task_type,
        queue_name,
        priority,
        payload,
        max_attempts,
        scheduled_for=None,
        request_id=None,
        actor_id=None,
    ) -> JobRecord:
        self.created.append(
            {
                "task_type": task_type,
                "queue_name": queue_name,
                "priority": priority,
                "max_attempts": max_attempts,
                "scheduled_for": scheduled_for,
            }
        )
        return JobRecord(
            id=uuid.uuid4(),
            task_type=task_type,
            queue_name=queue_name,
            priority=priority,
            status="queued",
            payload=payload,
            attempts=0,
            max_attempts=max_attempts,
            last_error=None,
            error_history=[],
            scheduled_for=scheduled_for,
            started_at=None,
            finished_at=None,
            locked_by=None,
            request_id=request_id,
            actor_id=actor_id,
            version=1,
            created_at=datetime.now(UTC),
        )


class _BrokenRedisQueue(RedisJobQueue):
    def push_ready(self, **kwargs):
        raise redis.RedisError("connection refused")

    def push_delayed(self, **kwargs):
        raise redis.RedisError("connection refused")


def _service(repo: _FakeJobRepository | None = None, *, default_max_attempts: int = 5):
    client = fakeredis.FakeRedis(decode_responses=True)
    redis_queue = RedisJobQueue(client=client)
    job_repository = repo if repo is not None else _FakeJobRepository()
    service = JobService(
        job_repository=job_repository,  # type: ignore[arg-type]
        redis_queue=redis_queue,
        default_max_attempts=default_max_attempts,
    )
    return service, job_repository, redis_queue


class TestEnqueueImmediate:
    def test_enqueue_creates_a_durable_job_and_pushes_it_ready(self):
        service, repo, redis_queue = _service()

        job = service.enqueue(
            task_type="send_email", queue_name="default", payload={"to_address": "a@example.com"}
        )

        assert job.status == "queued"
        dequeued = redis_queue.dequeue(
            queue_names=["default"], priority_order=[JobPriority.NORMAL], timeout_seconds=1
        )
        assert dequeued == str(job.id)

    def test_enqueue_uses_the_default_max_attempts_when_not_overridden(self):
        service, repo, _ = _service(default_max_attempts=7)

        service.enqueue(task_type="send_email", queue_name="default", payload={})

        assert repo.created[0]["max_attempts"] == 7

    def test_enqueue_honors_an_explicit_max_attempts_override(self):
        service, repo, _ = _service(default_max_attempts=7)

        service.enqueue(
            task_type="escalate_stage", queue_name="escalation", payload={}, max_attempts=3
        )

        assert repo.created[0]["max_attempts"] == 3

    def test_enqueue_pushes_onto_the_ready_list_matching_the_given_priority(self):
        service, _, redis_queue = _service()

        job = service.enqueue(
            task_type="escalate_stage",
            queue_name="escalation",
            payload={},
            priority=JobPriority.HIGH,
        )

        assert redis_queue.queue_depth(queue_name="escalation", priority=JobPriority.HIGH) == 1
        dequeued = redis_queue.dequeue(
            queue_names=["escalation"], priority_order=[JobPriority.HIGH], timeout_seconds=1
        )
        assert dequeued == str(job.id)


class TestEnqueueDelayed:
    def test_a_scheduled_for_future_time_goes_to_the_delayed_set_not_the_ready_list(self):
        service, _, redis_queue = _service()
        ready_at = datetime.now(UTC) + timedelta(hours=1)

        service.enqueue(
            task_type="send_reminder",
            queue_name="escalation",
            payload={},
            scheduled_for=ready_at,
        )

        assert redis_queue.delayed_count(queue_name="escalation") == 1
        assert redis_queue.queue_depth(queue_name="escalation", priority=JobPriority.NORMAL) == 0


class TestEnqueueSurvivesARedisPushFailure:
    def test_the_job_is_still_durably_created_even_if_the_redis_push_fails(self):
        client = fakeredis.FakeRedis(decode_responses=True)
        broken_queue = _BrokenRedisQueue(client=client)
        repo = _FakeJobRepository()
        service = JobService(
            job_repository=repo,  # type: ignore[arg-type]
            redis_queue=broken_queue,
            default_max_attempts=5,
        )

        job = service.enqueue(task_type="send_email", queue_name="default", payload={})

        assert job.status == "queued"
        assert len(repo.created) == 1
