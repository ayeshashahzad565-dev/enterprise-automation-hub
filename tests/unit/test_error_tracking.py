"""Tests for ``app.config.error_tracking.init_error_tracking`` (Milestone
13, Medium finding 12): a no-op unless ``SENTRY_DSN`` is configured.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config.error_tracking import init_error_tracking

pytestmark = pytest.mark.unit


class TestInitErrorTracking:
    def test_does_nothing_when_sentry_dsn_is_unset(self, monkeypatch):
        monkeypatch.delenv("SENTRY_DSN", raising=False)

        with patch("sentry_sdk.init") as mock_init:
            init_error_tracking(environment="production")

        mock_init.assert_not_called()

    def test_does_nothing_when_sentry_dsn_is_blank(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "   ")

        with patch("sentry_sdk.init") as mock_init:
            init_error_tracking(environment="production")

        mock_init.assert_not_called()

    def test_initializes_sentry_with_the_configured_dsn_and_environment(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "https://example@o0.ingest.sentry.io/0")

        with patch("sentry_sdk.init") as mock_init:
            init_error_tracking(environment="production")

        mock_init.assert_called_once_with(
            dsn="https://example@o0.ingest.sentry.io/0",
            environment="production",
            traces_sample_rate=0.0,
        )
