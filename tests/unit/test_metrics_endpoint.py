"""Tests for ``GET /metrics`` and ``app.api.middleware.MetricsMiddleware``
(production infrastructure layer).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.bootstrap import ApplicationResources


def _fake_resources_factory() -> ApplicationResources:
    database_client = MagicMock()
    database_client.health_check.return_value = True
    return MagicMock(
        spec=ApplicationResources,
        scheduler_stats=None,
        leader_election=None,
        database_client=database_client,
        redis_client=None,
    )


def test_metrics_endpoint_returns_prometheus_text_format() -> None:
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


def test_metrics_endpoint_is_not_mounted_under_the_api_v1_prefix() -> None:
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/metrics")

    assert response.status_code == 404


def test_a_request_increments_the_request_count_metric() -> None:
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        client.get("/api/v1/health")
        metrics_response = client.get("/metrics")

    body = metrics_response.text
    assert 'eah_http_requests_total{method="GET",path_template="/api/v1/health"' in body


def test_metrics_can_be_disabled_via_environment_variable(monkeypatch) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "false")
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 404


class _FakeRedisJobQueueForMetrics:
    def queue_depth(self, *, queue_name, priority):
        return 3 if queue_name == "default" else 0

    def delayed_count(self, *, queue_name):
        return 1


class _FakeJobRepositoryForMetrics:
    def count_dead_letter_by_queue(self):
        return {"default": 2}


def test_metrics_reflects_current_job_queue_depth_and_dead_letter_counts() -> None:
    def _factory() -> ApplicationResources:
        database_client = MagicMock()
        database_client.health_check.return_value = True
        return MagicMock(
            spec=ApplicationResources,
            scheduler_stats=None,
            leader_election=None,
            database_client=database_client,
            redis_client=None,
            redis_job_queue=_FakeRedisJobQueueForMetrics(),
            job_repository=_FakeJobRepositoryForMetrics(),
        )

    app = create_app(resources_factory=_factory)

    with TestClient(app) as client:
        response = client.get("/metrics")

    body = response.text
    assert 'eah_job_queue_depth{priority="normal",queue_name="default"} 3.0' in body
    assert 'eah_job_delayed_count{queue_name="default"} 1.0' in body
    assert 'eah_job_dead_letter_count{queue_name="default"} 2.0' in body


def test_metrics_reports_no_queue_depth_when_redis_is_not_configured() -> None:
    def _factory() -> ApplicationResources:
        database_client = MagicMock()
        database_client.health_check.return_value = True
        return MagicMock(
            spec=ApplicationResources,
            scheduler_stats=None,
            leader_election=None,
            database_client=database_client,
            redis_client=None,
            redis_job_queue=None,
            job_repository=_FakeJobRepositoryForMetrics(),
        )

    app = create_app(resources_factory=_factory)

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert 'eah_job_dead_letter_count{queue_name="default"} 2.0' in response.text
