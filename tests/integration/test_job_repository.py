"""Real-database tests for ``JobRepository``.

Verifies the ``jobs`` table (migration ``0015_jobs``) and its repository
against genuine Postgres/postgrest: insert, the named status-transition
methods under optimistic-locking control, retry-from-dead-letter, and
filtered/paginated listing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from app.database.exceptions import ConcurrentUpdateError
from app.database.repositories.base_repository import Page

pytestmark = pytest.mark.integration


@pytest.fixture
def make_test_job(real_repos, _committing_pg_conn: psycopg.Connection):
    """Factory fixture: create a job row and guarantee its removal at teardown.

    ``jobs`` is never cascade-deleted from anything else this suite's
    other fixtures clean up, so this fixture owns its own cleanup rather
    than relying on ``make_test_profile``'s cascade.
    """
    created_ids: list[uuid.UUID] = []

    def _make(
        *,
        task_type: str = "send_email",
        queue_name: str = "default",
        priority: str = "normal",
        payload: dict | None = None,
        max_attempts: int = 5,
    ):
        job = real_repos.job.create_job(
            task_type=task_type,
            queue_name=queue_name,
            priority=priority,
            payload=payload or {"to_address": "itest@example.invalid"},
            max_attempts=max_attempts,
        )
        created_ids.append(job.id)
        return job

    yield _make

    if created_ids:
        with _committing_pg_conn.cursor() as cur:
            cur.execute(
                "delete from public.jobs where id = any(%s);",
                ([str(i) for i in created_ids],),
            )


class TestJobRepositoryAgainstRealPostgres:
    def test_create_job_persists_with_queued_status_and_version_one(self, make_test_job):
        job = make_test_job(payload={"to_address": "a@example.invalid", "subject": "Hi"})

        assert job.status == "queued"
        assert job.version == 1
        assert job.attempts == 0
        assert job.payload == {"to_address": "a@example.invalid", "subject": "Hi"}

    def test_mark_running_then_succeeded_transitions_correctly(self, real_repos, make_test_job):
        job = make_test_job()

        running = real_repos.job.mark_running(job.id, expected_version=job.version, locked_by="host-1")
        assert running.status == "running"
        assert running.locked_by == "host-1"
        assert running.started_at is not None
        assert running.version == job.version + 1

        succeeded = real_repos.job.mark_succeeded(running.id, expected_version=running.version)
        assert succeeded.status == "succeeded"
        assert succeeded.finished_at is not None

    def test_mark_failed_will_retry_increments_attempts_and_appends_history(
        self, real_repos, make_test_job
    ):
        job = make_test_job()
        next_attempt = datetime.now(UTC) + timedelta(seconds=30)

        retried = real_repos.job.mark_failed_will_retry(
            job.id,
            expected_version=job.version,
            attempts=1,
            error="SMTP timeout",
            current_error_history=job.error_history,
            next_attempt_scheduled_for=next_attempt,
        )

        assert retried.status == "retrying"
        assert retried.attempts == 1
        assert retried.last_error == "SMTP timeout"
        assert len(retried.error_history) == 1
        assert retried.error_history[0]["error"] == "SMTP timeout"
        assert retried.scheduled_for is not None

    def test_mark_dead_lettered_is_terminal_and_retry_dead_letter_resets_it(
        self, real_repos, make_test_job
    ):
        job = make_test_job()

        dead = real_repos.job.mark_dead_lettered(
            job.id,
            expected_version=job.version,
            attempts=5,
            error="permanent failure",
            current_error_history=job.error_history,
        )
        assert dead.status == "dead_lettered"
        assert dead.attempts == 5

        retried = real_repos.job.retry_dead_letter(dead.id, expected_version=dead.version)
        assert retried.status == "queued"
        assert retried.attempts == 0
        assert retried.last_error is None

    def test_a_stale_version_transition_is_rejected(self, real_repos, make_test_job):
        job = make_test_job()
        real_repos.job.mark_running(job.id, expected_version=job.version, locked_by="host-1")

        with pytest.raises(ConcurrentUpdateError):
            real_repos.job.mark_running(job.id, expected_version=job.version, locked_by="host-2")

    def test_list_jobs_filters_by_status_and_task_type(self, real_repos, make_test_job):
        target = make_test_job(task_type="escalate_stage", queue_name="escalation")
        make_test_job(task_type="send_email", queue_name="default")

        page = real_repos.job.list_jobs(task_type="escalate_stage", page=Page(size=50))

        assert any(j.id == target.id for j in page.items)
        assert all(j.task_type == "escalate_stage" for j in page.items)

    def test_list_dead_letter_returns_only_dead_lettered_jobs(self, real_repos, make_test_job):
        job = make_test_job()
        real_repos.job.mark_dead_lettered(
            job.id, expected_version=job.version, attempts=5, error="boom", current_error_history=[]
        )
        make_test_job()  # a second, still-queued job that must not appear

        page = real_repos.job.list_dead_letter(page=Page(size=50))

        assert any(j.id == job.id for j in page.items)
        assert all(j.status == "dead_lettered" for j in page.items)

    def test_list_stuck_running_finds_jobs_running_since_before_the_cutoff(
        self, real_repos, make_test_job
    ):
        job = make_test_job()
        real_repos.job.mark_running(job.id, expected_version=job.version, locked_by="host-1")

        future_cutoff = datetime.now(UTC) + timedelta(minutes=1)
        stuck = real_repos.job.list_stuck_running(older_than=future_cutoff)

        assert any(j.id == job.id for j in stuck)

    def test_count_dead_letter_by_queue_aggregates_per_queue(self, real_repos, make_test_job):
        job = make_test_job(queue_name="escalation")
        real_repos.job.mark_dead_lettered(
            job.id, expected_version=job.version, attempts=3, error="boom", current_error_history=[]
        )

        counts = real_repos.job.count_dead_letter_by_queue()

        assert counts.get("escalation", 0) >= 1
