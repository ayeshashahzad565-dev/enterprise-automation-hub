"""Optional error-tracking integration (Sentry).

Per ``docs/deployment.md`` Section 15.1, EAH's baseline monitoring
surface is deliberately lightweight — structured logs and a health
endpoint, with no dedicated metrics-collection or distributed-tracing
platform, since none is part of the fixed stack. This module adds
exactly one narrow, entirely optional hook on top of that baseline: if
``SENTRY_DSN`` is set, every unhandled exception (API routes, the
Scheduler's jobs) is automatically reported to Sentry. If it is unset
(the default, and the only configuration every existing deployment of
this app has ever had), ``init_error_tracking`` is a no-op — this
introduces no behavior change, no network call, and no new operational
requirement for a deployment that doesn't opt in.

Deliberately error-capture only, not the broader "distributed tracing
platform" the Deployment Guide explicitly excludes:
``traces_sample_rate=0.0`` disables Sentry's separate Performance
Tracing feature outright, keeping this hook scoped to exactly what it
claims to be.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

__all__ = ["init_error_tracking"]


def init_error_tracking(*, environment: str) -> None:
    """Initialize Sentry error tracking, if ``SENTRY_DSN`` is configured.

    Safe to call unconditionally at startup — does nothing when
    ``SENTRY_DSN`` is absent or blank.

    Args:
        environment: The running environment's name (e.g.
            ``Environment.value``), tagged on every reported event so
            issues can be filtered by Development/Testing/Staging/
            Production in the Sentry dashboard.
    """
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        logger.debug("SENTRY_DSN not set; Sentry error tracking is disabled.")
        return

    import sentry_sdk

    sentry_sdk.init(dsn=dsn, environment=environment, traces_sample_rate=0.0)
    logger.info(
        "Sentry error tracking initialized for environment '%s'.",
        environment,
        extra={"environment": environment},
    )
