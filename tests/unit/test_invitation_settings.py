"""Unit tests for the Milestone 4 invitation configuration:
``app.config.settings.InvitationSettings`` and its loading in
``load_settings``.

Only the invitation-specific slice of ``load_settings`` is exercised here
— general settings-loading behavior (required variables, SMTP, rate
limits, etc.) is unchanged by this milestone and is out of its scope.

``TestInvitationExpiryHoursValidation`` and
``TestInvitationPublicRateLimitSetting`` were added in Milestone 9's
Configuration audit: the former closes a "no runtime surprises" gap (a
non-positive expiry was previously accepted silently), the latter covers
the new setting backing ``app.api.rate_limiting``.
"""

from __future__ import annotations

import pytest

from app.config.exceptions import InvalidConfigurationValueError, MissingEnvironmentVariableError
from app.config.settings import load_settings

pytestmark = pytest.mark.unit

_REQUIRED_ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_ANON_KEY": "anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
}

#: load_settings() also requires SMTP in Staging/Production (see
#: _load_smtp_settings) — unrelated to this file's own concern
#: (APP_BASE_URL), set only so a hardened-environment test doesn't fail
#: construction on SMTP first.
_HARDENED_ENV_EXTRAS = {
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USERNAME": "notifications@example.com",
    "SMTP_PASSWORD": "smtp-password",
    "SMTP_FROM_ADDRESS": "notifications@example.com",
}


class TestInvitationSettingsDefaults:
    def test_expiry_hours_defaults_to_72(self) -> None:
        settings = load_settings(env=_REQUIRED_ENV)

        assert settings.invitation.expiry_hours == 72.0

    def test_app_base_url_defaults_to_localhost_dev_server(self) -> None:
        settings = load_settings(env=_REQUIRED_ENV)

        assert settings.invitation.app_base_url == "http://localhost:3000"

    def test_accept_path_defaults_to_accept_invite(self) -> None:
        settings = load_settings(env=_REQUIRED_ENV)

        assert settings.invitation.accept_path == "/accept-invite"


class TestInvitationSettingsFromEnvironment:
    def test_expiry_hours_is_read_from_env(self) -> None:
        env = {**_REQUIRED_ENV, "INVITATION_EXPIRY_HOURS": "48"}

        settings = load_settings(env=env)

        assert settings.invitation.expiry_hours == 48.0

    def test_app_base_url_is_read_from_env(self) -> None:
        env = {**_REQUIRED_ENV, "APP_BASE_URL": "https://portal.example.com"}

        settings = load_settings(env=env)

        assert settings.invitation.app_base_url == "https://portal.example.com"

    def test_app_base_url_trailing_slash_is_stripped(self) -> None:
        env = {**_REQUIRED_ENV, "APP_BASE_URL": "https://portal.example.com/"}

        settings = load_settings(env=env)

        assert settings.invitation.app_base_url == "https://portal.example.com"

    def test_accept_path_is_read_from_env(self) -> None:
        env = {**_REQUIRED_ENV, "INVITATION_ACCEPT_PATH": "/join"}

        settings = load_settings(env=env)

        assert settings.invitation.accept_path == "/join"

    def test_invalid_expiry_hours_raises_invalid_configuration_value_error(self) -> None:
        env = {**_REQUIRED_ENV, "INVITATION_EXPIRY_HOURS": "not-a-number"}

        with pytest.raises(InvalidConfigurationValueError):
            load_settings(env=env)


class TestInvitationExpiryHoursValidation:
    def test_zero_expiry_hours_fails_at_startup(self) -> None:
        env = {**_REQUIRED_ENV, "INVITATION_EXPIRY_HOURS": "0"}

        with pytest.raises(InvalidConfigurationValueError) as exc_info:
            load_settings(env=env)

        assert exc_info.value.variable_name == "INVITATION_EXPIRY_HOURS"

    def test_negative_expiry_hours_fails_at_startup(self) -> None:
        env = {**_REQUIRED_ENV, "INVITATION_EXPIRY_HOURS": "-5"}

        with pytest.raises(InvalidConfigurationValueError) as exc_info:
            load_settings(env=env)

        assert exc_info.value.variable_name == "INVITATION_EXPIRY_HOURS"

    def test_a_small_positive_expiry_is_accepted(self) -> None:
        env = {**_REQUIRED_ENV, "INVITATION_EXPIRY_HOURS": "0.5"}

        settings = load_settings(env=env)

        assert settings.invitation.expiry_hours == 0.5


class TestAppBaseUrlRequiredInHardenedEnvironments:
    """An unset APP_BASE_URL in Staging/Production previously failed
    silently: SMTP is already required there, so the invitation email
    sends successfully — its acceptance link just silently pointed every
    invited user at localhost:3000, breaking onboarding with no startup
    error. Matches CORS_ALLOWED_ORIGINS' identical required-in-hardened-
    environments discipline (app/api/main.py)."""

    @pytest.mark.parametrize("environment", ["staging", "production"])
    def test_missing_app_base_url_raises_at_startup(self, environment: str) -> None:
        env = {**_REQUIRED_ENV, **_HARDENED_ENV_EXTRAS, "APP_ENVIRONMENT": environment}

        with pytest.raises(MissingEnvironmentVariableError) as exc_info:
            load_settings(env=env)

        assert exc_info.value.variable_name == "APP_BASE_URL"

    @pytest.mark.parametrize("environment", ["staging", "production"])
    def test_configured_app_base_url_is_used_in_hardened_environments(
        self, environment: str
    ) -> None:
        env = {
            **_REQUIRED_ENV,
            **_HARDENED_ENV_EXTRAS,
            "APP_ENVIRONMENT": environment,
            "APP_BASE_URL": "https://portal.example.com",
        }

        settings = load_settings(env=env)

        assert settings.invitation.app_base_url == "https://portal.example.com"

    @pytest.mark.parametrize("environment", ["development", "testing"])
    def test_missing_app_base_url_still_falls_back_outside_hardened_environments(
        self, environment: str
    ) -> None:
        env = {**_REQUIRED_ENV, "APP_ENVIRONMENT": environment}

        # Must not raise.
        settings = load_settings(env=env)

        assert settings.invitation.app_base_url == "http://localhost:3000"


class TestInvitationPublicRateLimitSetting:
    def test_defaults_to_20_per_5_minutes(self) -> None:
        settings = load_settings(env=_REQUIRED_ENV)

        assert settings.rate_limits.invitation_public_per_5_minutes == 20

    def test_is_read_from_env(self) -> None:
        env = {**_REQUIRED_ENV, "RATE_LIMIT_INVITATION_PUBLIC_PER_5_MINUTES": "5"}

        settings = load_settings(env=env)

        assert settings.rate_limits.invitation_public_per_5_minutes == 5

    def test_zero_is_a_valid_configuration_and_blocks_every_request(self) -> None:
        env = {**_REQUIRED_ENV, "RATE_LIMIT_INVITATION_PUBLIC_PER_5_MINUTES": "0"}

        settings = load_settings(env=env)

        assert settings.rate_limits.invitation_public_per_5_minutes == 0

    def test_a_negative_limit_fails_at_startup(self) -> None:
        env = {**_REQUIRED_ENV, "RATE_LIMIT_INVITATION_PUBLIC_PER_5_MINUTES": "-1"}

        with pytest.raises(InvalidConfigurationValueError) as exc_info:
            load_settings(env=env)

        assert exc_info.value.variable_name == "RATE_LIMIT_INVITATION_PUBLIC_PER_5_MINUTES"
