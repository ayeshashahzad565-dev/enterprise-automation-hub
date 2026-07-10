"""Environment detection and validation.

Per the Deployment Guide (DG Section 3), Enterprise Automation Hub runs in
exactly four environments: Development, Testing (CI), Staging, and
Production. This module defines the ``Environment`` enum representing
those four values and the ``detect_environment`` function that resolves
the currently running environment from configuration, with no dependency
on any other module in this package (in particular, no dependency on
``settings.py``, so that environment detection can be performed
independently and early, before the rest of configuration is loaded).
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping

from app.config.constants import ENV_APP_ENVIRONMENT
from app.config.exceptions import EnvironmentDetectionError


class Environment(str, Enum):
    """The four environments EAH is deployed into, per DG Section 3.

    Values are lowercase strings so that ``Environment(raw_value)``
    accepts the environment variable's value directly, without a
    translation step.
    """

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production(self) -> bool:
        """Whether this is the production environment."""
        return self is Environment.PRODUCTION

    @property
    def is_staging(self) -> bool:
        """Whether this is the staging environment."""
        return self is Environment.STAGING

    @property
    def is_development(self) -> bool:
        """Whether this is the development environment."""
        return self is Environment.DEVELOPMENT

    @property
    def is_testing(self) -> bool:
        """Whether this is the testing (CI) environment."""
        return self is Environment.TESTING

    @property
    def requires_production_grade_hardening(self) -> bool:
        """Whether this environment must have every hardening measure in
        DG Section 19 enabled without relaxation.

        Per DG Section 8.1 and Section 19.5, Staging and Production are
        held to an identical hardening standard (rate limiting always
        enforced, email dispatch always enabled) so that Staging remains
        a faithful predictor of Production behavior; only Development and
        Testing may relax these.
        """
        return self in (Environment.STAGING, Environment.PRODUCTION)


#: The default environment assumed when no explicit value is configured,
#: matching the least-privileged, least-production-like option so that a
#: missing configuration value never accidentally behaves as Production.
DEFAULT_ENVIRONMENT: Environment = Environment.DEVELOPMENT


def detect_environment(env: Mapping[str, str] | None = None) -> Environment:
    """Determine the currently running environment.

    Args:
        env: The environment variable mapping to read from. Defaults to
            ``os.environ`` when ``None`` is passed; tests and other
            callers may supply any ``Mapping[str, str]`` instead, which is
            what makes this function straightforward to unit test without
            mutating real process environment variables.

    Returns:
        The detected ``Environment``. If ``APP_ENVIRONMENT`` is unset or
        empty, ``DEFAULT_ENVIRONMENT`` (Development) is returned rather
        than raising, since a missing value is a normal condition for a
        local developer workstation, not a misconfiguration.

    Raises:
        EnvironmentDetectionError: If ``APP_ENVIRONMENT`` is set to a
            value that does not match any ``Environment`` member.
    """
    import os

    source = env if env is not None else os.environ
    raw_value = source.get(ENV_APP_ENVIRONMENT)
    if raw_value is None or not raw_value.strip():
        return DEFAULT_ENVIRONMENT

    normalized = raw_value.strip().lower()
    try:
        return Environment(normalized)
    except ValueError as exc:
        raise EnvironmentDetectionError(raw_value) from exc