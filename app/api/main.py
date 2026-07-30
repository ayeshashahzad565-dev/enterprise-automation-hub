"""FastAPI application factory — the first physical HTTP binding for the
REST contract ``docs/api_design.md`` already specifies.

Per the Phase 0 migration plan, this module wires the exact same
Application Services Streamlit already calls (via ``app.bootstrap``,
shared with ``app.py``), a JWT-bearer authentication dependency
(``app.api.dependencies.get_current_identity``), centralized exception
handling (``app.api.exception_handlers``), and cross-cutting middleware
(``app.api.middleware``) — every route handler simply calls an existing
Application Service (or, for the one established exception, a
repository) method; none contain business logic of their own.

Run with: ``uvicorn app.api.main:create_app --factory``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.dependencies import bind_tenant_database_client
from app.api.exception_handlers import register_exception_handlers
from app.api.middleware import (
    CorrelationIdMiddleware,
    MetricsMiddleware,
    RequestIDMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.rate_limiting import enforce_rate_limit
from app.api.routers import activity as activity_router
from app.api.routers import admin_dashboard as admin_dashboard_router
from app.api.routers import admin_departments as admin_departments_router
from app.api.routers import admin_invitations as admin_invitations_router
from app.api.routers import admin_jobs as admin_jobs_router
from app.api.routers import admin_roles as admin_roles_router
from app.api.routers import admin_settings as admin_settings_router
from app.api.routers import admin_users as admin_users_router
from app.api.routers import ai as ai_router
from app.api.routers import analytics as analytics_router
from app.api.routers import approvals as approvals_router
from app.api.routers import attachments as attachments_router
from app.api.routers import auth as auth_router
from app.api.routers import comments as comments_router
from app.api.routers import dashboard as dashboard_router
from app.api.routers import health as health_router
from app.api.routers import metrics as metrics_router
from app.api.routers import notifications as notifications_router
from app.api.routers import operational_analytics as operational_analytics_router
from app.api.routers import platform as platform_router
from app.api.routers import public_invitations as public_invitations_router
from app.api.routers import requests as requests_router
from app.api.routers import search as search_router
from app.api.routers import workflow_definitions as workflow_definitions_router
from app.bootstrap import (
    ApplicationResources,
    build_application_resources,
    shutdown_notification_email_dispatch,
    shutdown_scheduler,
)
from app.config.environment import detect_environment
from app.config.exceptions import InvalidConfigurationValueError, MissingEnvironmentVariableError

__all__ = ["create_app"]

logger = logging.getLogger(__name__)

_API_V1_PREFIX = "/api/v1"

#: The default Next.js dev server origin — used only when
#: ``CORS_ALLOWED_ORIGINS`` is not set, since no deployed frontend origin
#: exists yet in this phase. Not a hardcoded-only option: overridable via
#: that environment variable, a comma-separated origin list, matching the
#: same "load from environment, never hardcode" discipline
#: ``app.config.settings`` already applies to every other environment-
#: specific value in this codebase.
_DEFAULT_CORS_ORIGINS = ["http://localhost:3000"]


def _metrics_enabled() -> bool:
    """Return whether ``GET /metrics`` should be mounted.

    Read directly from ``os.environ`` (matching ``_cors_allowed_origins``'s
    identical pattern above) rather than through ``AppSettings``, since
    router mounting happens synchronously in ``create_app``, before
    ``build_application_resources`` loads settings in the ``lifespan``
    handler.

    Returns:
        ``True`` unless ``METRICS_ENABLED`` is explicitly set to a
        falsy value (``"false"``/``"0"``/``"no"``, case-insensitive).
    """
    raw = os.environ.get("METRICS_ENABLED", "true").strip().lower()
    return raw not in ("false", "0", "no")


def _cors_allowed_origins() -> list[str]:
    """Return the configured CORS-allowed origins.

    Returns:
        The comma-separated origins in the ``CORS_ALLOWED_ORIGINS``
        environment variable, or ``_DEFAULT_CORS_ORIGINS`` if unset.

    Raises:
        MissingEnvironmentVariableError: If ``CORS_ALLOWED_ORIGINS`` is
            unset in Staging/Production. Silently falling back to the
            localhost default there fails safe for browsers (nothing
            external gets through) but fails *silently* for the real
            deployed frontend — this app would simply stop accepting its
            own frontend's requests with no explicit startup error
            pointing at the missing variable. Failing loudly at startup
            instead surfaces the misconfiguration immediately, matching
            ``_load_smtp_settings``'s identical required-in-Staging/
            Production precedent (``app/config/settings.py``).
        InvalidConfigurationValueError: If ``CORS_ALLOWED_ORIGINS``
            includes ``"*"``, in any environment — see the inline comment
            on that check for why a wildcard is never safe here.
    """
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        # This app's CORS middleware is configured with allow_credentials=
        # True below; combined with a wildcard origin, Starlette reflects
        # whatever Origin header the request actually sent (the standard
        # browser-CORS behavior for "any origin, with credentials") rather
        # than statically allowing "*" — i.e. this isn't a no-op, it is
        # "any origin at all, with credentials." Never a legitimate value
        # for this application's own frontend origin, so it's rejected
        # unconditionally rather than only in Staging/Production.
        raise InvalidConfigurationValueError(
            "CORS_ALLOWED_ORIGINS",
            "must not include '*' — this API is called with credentials, so a "
            "wildcard origin would allow any site to make credentialed requests. "
            "List the real frontend origin(s) explicitly, comma-separated.",
        )
    if origins:
        return origins
    if detect_environment().requires_production_grade_hardening:
        raise MissingEnvironmentVariableError("CORS_ALLOWED_ORIGINS")
    return _DEFAULT_CORS_ORIGINS


def _build_lifespan(resources_factory: Callable[[], ApplicationResources]):
    """Build a ``lifespan`` handler closed over a specific resources factory.

    Args:
        resources_factory: A zero-argument callable returning
            ``ApplicationResources`` — ``build_application_resources`` in
            production, or a fake/mocked bundle in a test (see
            ``create_app``'s own ``resources_factory`` parameter).

    Returns:
        An async context manager suitable for ``FastAPI(lifespan=...)``.
    """

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Build ``ApplicationResources`` once per process and tear the
        Scheduler down cleanly on shutdown.

        Mirrors ``app.py``'s own ``@st.cache_resource``-memoized,
        "construct once per process" resource lifecycle, using FastAPI's
        own idiomatic mechanism instead (see ``app.bootstrap``'s module
        docstring).

        Args:
            app: The FastAPI application being started.
        """
        resources = resources_factory()
        app.state.resources = resources
        logger.info("FastAPI application resources constructed.")
        yield
        if resources.scheduler_stats is not None:
            shutdown_scheduler(resources.scheduler_stats)
        if resources.email_dispatch_executor is not None:
            shutdown_notification_email_dispatch(resources.email_dispatch_executor)

    return _lifespan


def create_app(
    resources_factory: Callable[[], ApplicationResources] | None = None,
) -> FastAPI:
    """Construct and fully configure the FastAPI application.

    Args:
        resources_factory: A zero-argument callable returning
            ``ApplicationResources``, invoked exactly once at startup.
            Defaults to ``app.bootstrap.build_application_resources`` —
            the same wiring Streamlit uses. Overriding this is intended
            for tests only, so they can exercise real routes/middleware/
            exception handling without constructing a real Supabase
            client (see ``tests/unit/test_api_health.py``,
            ``tests/unit/test_api_auth_me.py``).

    Returns:
        A ready-to-serve ``FastAPI`` instance.
    """
    factory = resources_factory or build_application_resources
    # Interactive API docs (Swagger UI, ReDoc) and the raw OpenAPI schema
    # expose the full route/schema surface, including admin and platform
    # routes, to anyone who can reach this host — appropriate for
    # Development/Testing, but not for Staging/Production, which are held
    # to an identical hardening standard (Environment.
    # requires_production_grade_hardening's own docstring). Resolved via
    # detect_environment() directly, independent of AppSettings/a real
    # Supabase client, since this decision must be made synchronously
    # here, before build_application_resources ever runs in the lifespan
    # handler below.
    docs_enabled = not detect_environment().requires_production_grade_hardening
    app = FastAPI(
        title="Enterprise Automation Hub API",
        version="1.0.0",
        docs_url="/api/docs" if docs_enabled else None,
        redoc_url="/api/redoc" if docs_enabled else None,
        openapi_url="/api/openapi.json" if docs_enabled else None,
        lifespan=_build_lifespan(factory),
    )

    # Middleware order: Starlette's own ``Starlette.add_middleware``
    # *prepends* each call to ``self.user_middleware`` and then builds the
    # ASGI stack by wrapping in reverse of that list — net effect, the
    # LAST middleware added via ``add_middleware`` ends up OUTERMOST (its
    # pre-``call_next`` code runs first; its post-``call_next`` code runs
    # last), not the first, despite what an earlier version of this
    # comment claimed. Calls below are ordered oldest-to-newest
    # (innermost-to-outermost): CORS, CorrelationId, RequestID,
    # SecurityHeaders, RequestLogging, Metrics.
    #
    # RequestID is added *after* CorrelationId (making RequestID more
    # outer) specifically because CorrelationIdMiddleware reads
    # ``request.state.request_id`` as its fallback *before* calling
    # ``call_next`` — that read only ever sees a value RequestIDMiddleware
    # already set if RequestID's own pre-``call_next`` code has already
    # run, i.e. only if RequestID is more outer. SecurityHeaders,
    # RequestLogging, and Metrics all read/write ``request.state``/
    # response headers only *after* ``call_next`` returns, so their
    # relative order doesn't have this same constraint.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(MetricsMiddleware)

    register_exception_handlers(app)

    # `enforce_rate_limit` is per-authenticated-user and method-aware
    # (GET/HEAD/OPTIONS -> read_per_minute, everything else ->
    # write_per_minute — see app.api.rate_limiting's module docstring),
    # so attaching it once per router here gives every authenticated
    # route — auth, requests, approvals, admin, analytics, etc. — general
    # rate-limit coverage in one place. health_router (unauthenticated
    # liveness probe) and public_invitations_router (its own, separate
    # per-IP limiter — enforce_rate_limit requires an authenticated
    # identity, which neither of that router's routes has) are the only
    # two deliberately excluded.
    #
    # `bind_tenant_database_client` rides along in the same list for the
    # same reason: every authenticated route needs its per-request,
    # RLS-enforcing database client bound before any repository call, and
    # this is the one place that's already true for the whole API surface.
    # It is a no-op for repositories that stay on the service-role client
    # (``BaseRepository.always_use_injected_client=True``) and a real
    # RLS-enforcing swap for the handful verified safe to run under it —
    # see docs/tenant_isolation.md.
    _rate_limited = [Depends(enforce_rate_limit), Depends(bind_tenant_database_client)]

    app.include_router(health_router.router, prefix=_API_V1_PREFIX)
    if _metrics_enabled():
        app.include_router(metrics_router.router)
    app.include_router(auth_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited)
    app.include_router(
        requests_router.router, prefix=f"{_API_V1_PREFIX}/requests", dependencies=_rate_limited
    )
    app.include_router(comments_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited)
    app.include_router(dashboard_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited)
    app.include_router(attachments_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited)
    app.include_router(
        approvals_router.router, prefix=f"{_API_V1_PREFIX}/approvals", dependencies=_rate_limited
    )
    app.include_router(analytics_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited)
    app.include_router(
        operational_analytics_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited
    )
    app.include_router(
        notifications_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited
    )
    app.include_router(activity_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited)
    app.include_router(
        workflow_definitions_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited
    )
    app.include_router(admin_users_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited)
    app.include_router(admin_roles_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited)
    app.include_router(
        admin_departments_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited
    )
    app.include_router(
        admin_settings_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited
    )
    app.include_router(
        admin_dashboard_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited
    )
    app.include_router(
        admin_invitations_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited
    )
    app.include_router(admin_jobs_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited)
    app.include_router(public_invitations_router.router, prefix=_API_V1_PREFIX)
    app.include_router(platform_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited)
    app.include_router(search_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited)
    app.include_router(ai_router.router, prefix=_API_V1_PREFIX, dependencies=_rate_limited)

    return app
