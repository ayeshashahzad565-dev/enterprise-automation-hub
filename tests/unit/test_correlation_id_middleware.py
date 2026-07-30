"""Tests for ``app.api.middleware.CorrelationIdMiddleware`` (production
infrastructure layer).
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


def test_a_client_supplied_correlation_id_is_echoed_back() -> None:
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers={"X-Correlation-Id": "abc-123"})

    assert response.headers["X-Correlation-Id"] == "abc-123"


def test_a_correlation_id_is_generated_when_none_is_supplied() -> None:
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.headers["X-Correlation-Id"]


def test_the_generated_correlation_id_matches_the_request_id_when_neither_is_supplied() -> None:
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.headers["X-Correlation-Id"] == response.headers["X-Request-Id"]


def test_a_client_supplied_request_id_does_not_override_an_explicit_correlation_id() -> None:
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health",
            headers={"X-Request-Id": "req-1", "X-Correlation-Id": "corr-1"},
        )

    assert response.headers["X-Request-Id"] == "req-1"
    assert response.headers["X-Correlation-Id"] == "corr-1"
