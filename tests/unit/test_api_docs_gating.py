"""Tests for interactive API docs (Swagger/ReDoc/OpenAPI schema) being
disabled in Staging/Production and available in Development/Testing
(Milestone 13, High finding 5), and for ``CORS_ALLOWED_ORIGINS`` being
required (not silently defaulted) in those same hardened environments
(Milestone 13, Medium finding 7).

Uses the same ``MagicMock(spec=ApplicationResources, ...)``
``resources_factory`` pattern as ``test_api_health.py`` — none of these
tests need real infrastructure, only that ``create_app`` finishes
constructing the ASGI app.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.bootstrap import ApplicationResources
from app.config.exceptions import InvalidConfigurationValueError, MissingEnvironmentVariableError

pytestmark = pytest.mark.unit


def _fake_resources_factory() -> ApplicationResources:
    return MagicMock(spec=ApplicationResources, scheduler_stats=None, email_dispatch_executor=None)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_docs_are_disabled_in_hardened_environments(monkeypatch, environment):
    monkeypatch.setenv("APP_ENVIRONMENT", environment)
    # Unrelated to this test's concern (docs gating) — set only so
    # _cors_allowed_origins()'s own required-in-hardened-environments
    # check (Medium finding 7) doesn't fail construction first.
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        docs = client.get("/api/docs")
        redoc = client.get("/api/redoc")
        schema = client.get("/api/openapi.json")

    assert docs.status_code == 404
    assert redoc.status_code == 404
    assert schema.status_code == 404


@pytest.mark.parametrize("environment", ["development", "testing"])
def test_docs_remain_available_outside_hardened_environments(monkeypatch, environment):
    monkeypatch.setenv("APP_ENVIRONMENT", environment)
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        docs = client.get("/api/docs")
        schema = client.get("/api/openapi.json")

    assert docs.status_code == 200
    assert schema.status_code == 200


def test_docs_default_to_available_when_app_environment_is_unset(monkeypatch):
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    app = create_app(resources_factory=_fake_resources_factory)

    with TestClient(app) as client:
        docs = client.get("/api/docs")

    assert docs.status_code == 200


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_missing_cors_origins_raises_at_startup_in_hardened_environments(monkeypatch, environment):
    monkeypatch.setenv("APP_ENVIRONMENT", environment)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(MissingEnvironmentVariableError):
        create_app(resources_factory=_fake_resources_factory)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_configured_cors_origins_are_used_in_hardened_environments(monkeypatch, environment):
    monkeypatch.setenv("APP_ENVIRONMENT", environment)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")

    # Must not raise.
    create_app(resources_factory=_fake_resources_factory)


def test_missing_cors_origins_falls_back_to_localhost_outside_hardened_environments(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    # Must not raise.
    create_app(resources_factory=_fake_resources_factory)


@pytest.mark.parametrize("environment", ["development", "testing", "staging", "production"])
def test_wildcard_cors_origin_is_rejected_in_every_environment(monkeypatch, environment):
    """A bare "*" is rejected everywhere, not just in Staging/Production —
    this app's CORS middleware sets allow_credentials=True, and Starlette
    reflects the request's actual Origin when the origin list is "*" and
    credentials are allowed, rather than treating it as a harmless no-op."""
    monkeypatch.setenv("APP_ENVIRONMENT", environment)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")

    with pytest.raises(InvalidConfigurationValueError):
        create_app(resources_factory=_fake_resources_factory)


def test_wildcard_cors_origin_is_rejected_even_mixed_with_a_real_origin(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com,*")

    with pytest.raises(InvalidConfigurationValueError):
        create_app(resources_factory=_fake_resources_factory)
