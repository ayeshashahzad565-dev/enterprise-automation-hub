"""Tests for ``app.api.middleware.SecurityHeadersMiddleware``'s HSTS and
CSP headers (Milestone 13, Medium finding 6).
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
    )


def test_response_carries_hsts_and_csp_headers() -> None:
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
