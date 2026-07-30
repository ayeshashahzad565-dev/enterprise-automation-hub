"""Tests for ``GET /api/v1/health``."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.bootstrap import ApplicationResources


def _fake_resources_factory(
    *,
    database_reachable: bool = True,
    scheduler_active: bool = False,
    redis_client: MagicMock | None = None,
    leader_election: MagicMock | None = None,
) -> ApplicationResources:
    database_client = MagicMock()
    database_client.health_check.return_value = database_reachable
    return MagicMock(
        spec=ApplicationResources,
        scheduler_stats=object() if scheduler_active else None,
        database_client=database_client,
        redis_client=redis_client,
        leader_election=leader_election,
    )


def _fake_leader_election(*, is_leader: bool) -> MagicMock:
    return MagicMock(is_leader=is_leader)


def test_health_returns_ok_status_when_the_database_is_reachable() -> None:
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "scheduler_active": False,
        "scheduler_leader_election": "static",
    }


def test_health_returns_503_when_the_database_is_unreachable() -> None:
    app = create_app(resources_factory=lambda: _fake_resources_factory(database_reachable=False))

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "database": "unreachable",
        "scheduler_active": False,
        "scheduler_leader_election": "static",
    }


def test_health_reports_scheduler_active_true_on_the_leader_instance() -> None:
    app = create_app(resources_factory=lambda: _fake_resources_factory(scheduler_active=True))

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.json()["scheduler_active"] is True
    assert response.json()["scheduler_leader_election"] == "static"


def test_health_reports_scheduler_active_true_when_this_instance_is_the_elected_leader() -> None:
    app = create_app(
        resources_factory=lambda: _fake_resources_factory(
            leader_election=_fake_leader_election(is_leader=True)
        )
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    body = response.json()
    assert body["scheduler_active"] is True
    assert body["scheduler_leader_election"] == "redis"


def test_health_reports_scheduler_active_false_when_redis_election_has_not_elected_this_instance() -> (
    None
):
    app = create_app(
        resources_factory=lambda: _fake_resources_factory(
            # scheduler_active=True (coordinator constructed) would be
            # misleading on its own under Redis-backed election, since
            # every instance registers jobs — is_leader=False is what
            # must actually gate `scheduler_active`.
            scheduler_active=True,
            leader_election=_fake_leader_election(is_leader=False),
        )
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    body = response.json()
    assert body["scheduler_active"] is False
    assert body["scheduler_leader_election"] == "redis"


def test_health_response_carries_a_request_id_header() -> None:
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.headers["X-Request-Id"]


def test_liveness_always_returns_200_with_no_dependency_check() -> None:
    app = create_app(resources_factory=lambda: _fake_resources_factory(database_reachable=False))

    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_returns_ok_when_the_database_is_reachable() -> None:
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "scheduler_active": False,
        "scheduler_leader_election": "static",
    }


def test_readiness_returns_503_when_the_database_is_unreachable() -> None:
    app = create_app(resources_factory=lambda: _fake_resources_factory(database_reachable=False))

    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_readiness_reports_redis_unreachable_when_configured_and_down() -> None:
    redis_client = MagicMock()
    redis_client.ping.side_effect = ConnectionError("boom")
    app = create_app(
        resources_factory=lambda: _fake_resources_factory(redis_client=redis_client)
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["redis"] == "unreachable"
    assert body["job_queue"] == "unreachable"
    assert body["status"] == "degraded"


def test_readiness_reports_redis_ok_when_configured_and_reachable() -> None:
    redis_client = MagicMock()
    redis_client.ping.return_value = True
    app = create_app(
        resources_factory=lambda: _fake_resources_factory(redis_client=redis_client)
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["redis"] == "ok"
    assert response.json()["job_queue"] == "ok"
