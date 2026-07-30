"""Tests for the ``/api/v1/admin/jobs`` and ``/api/v1/admin/scheduled-jobs`` routes.

Exercises the router against fakes standing in for
``JobRepository``/``RedisJobQueue`` (no real Postgres/Redis) and a real
``SchedulerCoordinator`` wired with a no-op backend (matching
``test_scheduler_coordinator.py``'s fakes) for the scheduled-job
management endpoints.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
from app.config.settings import load_settings
from app.database.exceptions import RecordNotFoundError
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.job_repository import JobRecord
from app.models.enums import JobPriority
from app.scheduler.interfaces import ExecutionContext, ExecutionResult
from app.scheduler.registry import JobRegistry
from app.scheduler.scheduler import SchedulerCoordinator

pytestmark = pytest.mark.unit

_TOKEN = "test-token"
_TEST_ENV = {
    "APP_ENVIRONMENT": "development",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_ANON_KEY": "anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
}


def _job(
    *,
    task_type: str = "send_email",
    queue_name: str = "default",
    priority: str = "normal",
    status: str = "queued",
    payload: dict | None = None,
    attempts: int = 0,
    max_attempts: int = 5,
) -> JobRecord:
    return JobRecord(
        id=uuid.uuid4(),
        task_type=task_type,
        queue_name=queue_name,
        priority=priority,
        status=status,
        payload=payload or {"to_address": "a@example.com"},
        attempts=attempts,
        max_attempts=max_attempts,
        last_error=None,
        error_history=[],
        scheduled_for=None,
        started_at=None,
        finished_at=None,
        locked_by=None,
        request_id=None,
        actor_id=None,
        version=1,
        created_at=datetime.now(UTC),
    )


class _FakeJobRepository:
    def __init__(self, jobs: list[JobRecord] | None = None) -> None:
        self._jobs: dict[uuid.UUID, JobRecord] = {j.id: j for j in (jobs or [])}
        self.retried: list[uuid.UUID] = []

    def get_by_id(self, job_id: uuid.UUID) -> JobRecord:
        job = self._jobs.get(job_id)
        if job is None:
            raise RecordNotFoundError("jobs", job_id)
        return job

    def list_jobs(self, *, status=None, task_type=None, queue_name=None, priority=None, page: Page):
        items = list(self._jobs.values())
        if status is not None:
            items = [j for j in items if j.status == status]
        if task_type is not None:
            items = [j for j in items if j.task_type == task_type]
        return PagedResult(items=items, page=page.number, page_size=page.size, total_records=len(items))

    def list_dead_letter(self, *, task_type=None, page: Page):
        return self.list_jobs(status="dead_lettered", task_type=task_type, page=page)

    def retry_dead_letter(self, job_id: uuid.UUID, *, expected_version: int) -> JobRecord:
        job = self.get_by_id(job_id)
        self.retried.append(job_id)
        retried = dataclasses.replace(job, status="queued", attempts=0, version=job.version + 1)
        self._jobs[job_id] = retried
        return retried

    def count_dead_letter_by_queue(self) -> dict[str, int]:
        return {
            "default": sum(1 for j in self._jobs.values() if j.status == "dead_lettered"),
        }


class _FakeRedisJobQueue:
    def __init__(self) -> None:
        self.pushed: list[tuple[str, JobPriority, str]] = []

    def queue_depth(self, *, queue_name: str, priority: JobPriority) -> int:
        return 0

    def delayed_count(self, *, queue_name: str) -> int:
        return 0

    def push_ready(self, *, queue_name: str, priority: JobPriority, job_id: str) -> None:
        self.pushed.append((queue_name, priority, job_id))


class _FakeBackend:
    def __init__(self) -> None:
        self._running = True

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


class _FakeScheduledJob:
    def __init__(self, name: str, *, interval_seconds: int = 3600) -> None:
        self._name = name
        self._interval_seconds = interval_seconds

    @property
    def name(self) -> str:
        return self._name

    @property
    def interval_seconds(self) -> int:
        return self._interval_seconds

    def run(self, context: ExecutionContext) -> ExecutionResult:
        now = datetime.now(UTC)
        return ExecutionResult(job_name=self._name, started_at=now, finished_at=now, success=True)


def _coordinator_with_job(name: str = "escalation_check") -> SchedulerCoordinator:
    coordinator = SchedulerCoordinator(backend=_FakeBackend(), registry=JobRegistry())
    coordinator.register_job(_FakeScheduledJob(name))
    return coordinator


class _FakeTokenVerifier:
    def __init__(self, identity: AuthenticatedIdentity) -> None:
        self._identity = identity

    def resolve_claims(self, token: str) -> Mapping[str, Any]:
        if token != _TOKEN:
            raise InvalidTokenError("Unknown test token.")
        return {
            "sub": str(self._identity.user_id),
            "email": self._identity.email,
            "role": self._identity.role.value,
            "company_id": str(self._identity.company_id),
            "is_platform_admin": self._identity.is_platform_admin,
        }


def _build_client(
    identity: AuthenticatedIdentity,
    *,
    job_repository=None,
    job_service=None,
    redis_job_queue=None,
    scheduler_stats=None,
) -> TestClient:
    settings = load_settings(env=_TEST_ENV)

    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            settings=settings,
            token_verifier=_FakeTokenVerifier(identity),
            job_repository=job_repository if job_repository is not None else _FakeJobRepository(),
            job_service=job_service,
            redis_job_queue=redis_job_queue,
            scheduler_stats=scheduler_stats,
            audit_repo=MagicMock(),
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


class TestAuthorization:
    def test_employee_is_forbidden_from_listing_jobs(self, employee):
        _, employee_identity = employee
        client = _build_client(employee_identity)

        response = client.get("/api/v1/admin/jobs")

        assert response.status_code == 403


class TestListJobs:
    def test_admin_can_list_jobs(self, admin):
        _, admin_identity = admin
        repo = _FakeJobRepository([_job(task_type="send_email"), _job(task_type="escalate_stage")])
        client = _build_client(admin_identity, job_repository=repo)

        response = client.get("/api/v1/admin/jobs")

        assert response.status_code == 200
        assert len(response.json()["data"]) == 2

    def test_task_type_filter_is_applied(self, admin):
        _, admin_identity = admin
        target = _job(task_type="escalate_stage")
        repo = _FakeJobRepository([_job(task_type="send_email"), target])
        client = _build_client(admin_identity, job_repository=repo)

        response = client.get("/api/v1/admin/jobs", params={"task_type": "escalate_stage"})

        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == str(target.id)

    def test_invitation_token_is_redacted_in_the_response(self, admin):
        _, admin_identity = admin
        job = _job(
            task_type="send_invitation_email",
            payload={"to_email": "a@example.com", "token": "super-secret-raw-token"},
        )
        repo = _FakeJobRepository([job])
        client = _build_client(admin_identity, job_repository=repo)

        response = client.get("/api/v1/admin/jobs")

        assert "super-secret-raw-token" not in response.text
        assert response.json()["data"][0]["payload"]["token"] == "***redacted***"


class TestGetJob:
    def test_admin_can_fetch_a_single_job(self, admin):
        _, admin_identity = admin
        job = _job()
        client = _build_client(admin_identity, job_repository=_FakeJobRepository([job]))

        response = client.get(f"/api/v1/admin/jobs/{job.id}")

        assert response.status_code == 200
        assert response.json()["data"]["id"] == str(job.id)

    def test_unknown_job_id_is_404(self, admin):
        _, admin_identity = admin
        client = _build_client(admin_identity, job_repository=_FakeJobRepository([]))

        response = client.get(f"/api/v1/admin/jobs/{uuid.uuid4()}")

        assert response.status_code == 404


class TestDeadLetterAndRetry:
    def test_list_dead_letter_only_returns_dead_lettered_jobs(self, admin):
        _, admin_identity = admin
        dead = _job(status="dead_lettered")
        repo = _FakeJobRepository([_job(status="queued"), dead])
        client = _build_client(admin_identity, job_repository=repo)

        response = client.get("/api/v1/admin/jobs/dead-letter")

        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == str(dead.id)

    def test_retry_requires_the_job_system_to_be_active(self, admin):
        _, admin_identity = admin
        dead = _job(status="dead_lettered")
        repo = _FakeJobRepository([dead])
        client = _build_client(
            admin_identity, job_repository=repo, job_service=None, redis_job_queue=None
        )

        response = client.post(f"/api/v1/admin/jobs/{dead.id}/retry")

        assert response.status_code == 422

    def test_retry_rejects_a_job_that_is_not_dead_lettered(self, admin):
        _, admin_identity = admin
        queued = _job(status="queued")
        repo = _FakeJobRepository([queued])
        client = _build_client(
            admin_identity,
            job_repository=repo,
            job_service=MagicMock(),
            redis_job_queue=_FakeRedisJobQueue(),
        )

        response = client.post(f"/api/v1/admin/jobs/{queued.id}/retry")

        assert response.status_code == 422

    def test_retry_resets_and_requeues_a_dead_lettered_job(self, admin):
        _, admin_identity = admin
        dead = _job(status="dead_lettered", attempts=5)
        repo = _FakeJobRepository([dead])
        redis_queue = _FakeRedisJobQueue()
        client = _build_client(
            admin_identity, job_repository=repo, job_service=MagicMock(), redis_job_queue=redis_queue
        )

        response = client.post(f"/api/v1/admin/jobs/{dead.id}/retry")

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "queued"
        assert response.json()["data"]["attempts"] == 0
        assert len(redis_queue.pushed) == 1
        assert dead.id in repo.retried


class TestQueueStats:
    def test_stats_report_none_queue_depth_when_redis_is_not_configured(self, admin):
        _, admin_identity = admin
        client = _build_client(admin_identity, redis_job_queue=None)

        response = client.get("/api/v1/admin/jobs/stats/summary")

        data = response.json()["data"]
        assert data["queue_depth"] is None
        assert data["delayed_count"] is None

    def test_stats_report_queue_depth_when_redis_is_configured(self, admin):
        _, admin_identity = admin
        client = _build_client(admin_identity, redis_job_queue=_FakeRedisJobQueue())

        response = client.get("/api/v1/admin/jobs/stats/summary")

        data = response.json()["data"]
        assert data["queue_depth"] is not None
        assert isinstance(data["dead_letter_count"], dict)


class TestScheduledJobs:
    def test_list_scheduled_jobs_is_empty_when_no_scheduler_is_active(self, admin):
        _, admin_identity = admin
        client = _build_client(admin_identity, scheduler_stats=None)

        response = client.get("/api/v1/admin/scheduled-jobs")

        assert response.json()["data"] == []

    def test_list_scheduled_jobs_reports_a_registered_job(self, admin):
        _, admin_identity = admin
        client = _build_client(admin_identity, scheduler_stats=_coordinator_with_job())

        response = client.get("/api/v1/admin/scheduled-jobs")

        names = [job["name"] for job in response.json()["data"]]
        assert "escalation_check" in names

    def test_disable_then_enable_a_scheduled_job(self, admin):
        _, admin_identity = admin
        coordinator = _coordinator_with_job()
        client = _build_client(admin_identity, scheduler_stats=coordinator)

        disable_response = client.post("/api/v1/admin/scheduled-jobs/escalation_check/disable")
        assert disable_response.status_code == 200
        assert disable_response.json()["data"]["enabled"] is False

        enable_response = client.post("/api/v1/admin/scheduled-jobs/escalation_check/enable")
        assert enable_response.status_code == 200
        assert enable_response.json()["data"]["enabled"] is True

    def test_toggling_an_unregistered_job_is_404(self, admin):
        _, admin_identity = admin
        client = _build_client(admin_identity, scheduler_stats=_coordinator_with_job())

        response = client.post("/api/v1/admin/scheduled-jobs/does-not-exist/enable")

        assert response.status_code == 404

    def test_trigger_now_requires_an_active_scheduler(self, admin):
        _, admin_identity = admin
        client = _build_client(admin_identity, scheduler_stats=None)

        response = client.post("/api/v1/admin/scheduled-jobs/escalation_check/trigger-now")

        assert response.status_code == 422

    def test_trigger_now_returns_202_for_a_registered_job(self, admin):
        _, admin_identity = admin
        client = _build_client(admin_identity, scheduler_stats=_coordinator_with_job())

        response = client.post("/api/v1/admin/scheduled-jobs/escalation_check/trigger-now")

        assert response.status_code == 202
        assert response.json()["data"]["triggered"] is True
