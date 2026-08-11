"""ASGI middleware: request IDs, structured request logging, security headers.

CORS itself is not implemented here — Starlette's own ``CORSMiddleware``
(configured in ``app.api.main.create_app``) already does exactly this
job; writing a bespoke CORS middleware would only duplicate a
well-tested standard component for no benefit.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.observability.metrics import REQUEST_COUNT, REQUEST_LATENCY_SECONDS
from app.utils.id_generator import generate_request_correlation_id

__all__ = [
    "RequestIDMiddleware",
    "CorrelationIdMiddleware",
    "SecurityHeadersMiddleware",
    "RequestLoggingMiddleware",
    "MetricsMiddleware",
]

logger = logging.getLogger(__name__)

_REQUEST_ID_HEADER = "X-Request-Id"
_CORRELATION_ID_HEADER = "X-Correlation-Id"

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a correlation id to every request, matching API-ADD Section 9's
    ``meta.request_id`` convention.

    Echoes back a client-supplied ``X-Request-Id`` header if present (so a
    caller's own tracing id survives the round trip), generating a new one
    via ``app.utils.id_generator.generate_request_correlation_id`` otherwise
    — the exact same fallback ``app.utils.response.build_meta`` already
    uses when no id is supplied. Stored on ``request.state.request_id`` for
    downstream middleware, route handlers, and exception handlers to read,
    and echoed back on the response so a client can correlate its own logs
    with this application's.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Attach/propagate the request's correlation id.

        Args:
            request: The incoming request.
            call_next: The next stage in the middleware/router chain.

        Returns:
            The response, with ``X-Request-Id`` set.
        """
        request_id = request.headers.get(_REQUEST_ID_HEADER) or generate_request_correlation_id()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[_REQUEST_ID_HEADER] = request_id
        return response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach a correlation id to every request, distinct from its request id.

    A request id (``RequestIDMiddleware``, above) identifies exactly one
    HTTP request/response pair. A correlation id identifies a *logical
    operation* that may span several requests — for example, several API
    calls a single frontend page load triggers, or a request forwarded
    through an upstream gateway that already assigned one — so that every
    log line touched by that operation can be grepped together across
    requests, not just correlated within a single one.

    Echoes back a client-supplied ``X-Correlation-Id`` header if present,
    falling back to this request's own request id (never generating a
    second, independent id) when no correlation id was supplied — the
    common case of a single, standalone request is then trivially its own
    correlation id, with no extra id to track.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Attach/propagate the request's correlation id.

        Args:
            request: The incoming request.
            call_next: The next stage in the middleware/router chain.

        Returns:
            The response, with ``X-Correlation-Id`` set.
        """
        correlation_id = request.headers.get(_CORRELATION_ID_HEADER) or getattr(
            request.state, "request_id", None
        )
        if not correlation_id:
            correlation_id = generate_request_correlation_id()
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers[_CORRELATION_ID_HEADER] = correlation_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach a fixed set of defensive HTTP security headers to every response.

    Per DG Section 19 (Security Hardening); this is response-header
    hardening only — it duplicates nothing any Application Service does.
    """

    _HEADERS: dict[str, str] = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
        # Harmless to send over plain HTTP (browsers ignore it there) —
        # sent unconditionally rather than gated by environment, matching
        # every other header in this dict.
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        # This is a JSON API with no user-rendered HTML of its own —
        # default-src 'self' is safe for every ordinary route. The one
        # exception is /api/docs and /api/redoc (disabled outright in
        # Staging/Production, per app.api.main.create_app's
        # docs_enabled gate), whose default Swagger UI/ReDoc assets load
        # from cdn.jsdelivr.net and inject inline styles — allow-listed
        # explicitly here rather than left off, so those two
        # development/testing-only routes still render correctly instead
        # of silently breaking.
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "img-src 'self' data: https://cdn.jsdelivr.net; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'"
        ),
    }

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Add every configured security header to the response.

        Args:
            request: The incoming request.
            call_next: The next stage in the middleware/router chain.

        Returns:
            The response, with every header in ``_HEADERS`` set (unless
            already present).
        """
        response = await call_next(request)
        for name, value in self._HEADERS.items():
            response.headers.setdefault(name, value)
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Emit one structured log line per request via the application's
    already-configured root logger (``app.config.logging_config``).

    Matches API-ADD Section 27's Observability fields (``request_id``,
    ``duration_ms``) — no new logging framework or log format is
    introduced; every field here is passed through ``extra=`` exactly as
    every other component in this codebase already logs. ``user_id`` is
    read from ``request.state``, where ``app.api.dependencies
    .get_current_identity`` stashes it once resolved — this middleware
    itself never touches authentication, so an unauthenticated or
    pre-auth-failure request simply logs with ``user_id: null``, matching
    ``StructuredFormatter``'s "never fabricate a field" rule.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Log one line covering this request's user, method, path, status, and duration.

        Args:
            request: The incoming request.
            call_next: The next stage in the middleware/router chain.

        Returns:
            The response, unmodified.
        """
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "correlation_id": getattr(request.state, "correlation_id", None),
                "user_id": getattr(request.state, "user_id", None),
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 1),
            },
        )
        return response


def _templated_path(request: Request) -> str:
    """Return this request's full, templated path for use as a metric label.

    Args:
        request: The request, after routing has run (so ``scope`` carries
            ``route``/``path_params`` for anything that matched).

    Returns:
        The request path with every matched path-param value replaced by
        its ``{name}`` placeholder — e.g.
        ``/api/v1/requests/{request_id}`` — or ``"unmatched"`` when no
        route matched, since a raw unmatched path is attacker-controllable
        and would blow up label cardinality.
    """
    if request.scope.get("route") is None:
        return "unmatched"

    raw_path = request.url.path
    params = request.scope.get("path_params") or {}
    if not params:
        return raw_path

    placeholder_for_value = {str(value): name for name, value in params.items()}
    return "/".join(
        f"{{{placeholder_for_value[segment]}}}" if segment in placeholder_for_value else segment
        for segment in raw_path.split("/")
    )


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record Prometheus request-count and latency metrics for every request.

    Labels each metric with the *templated* request path (e.g.
    ``/api/v1/requests/{request_id}``, not the literal
    ``/api/v1/requests/3fa8...``). Deliberately never labels a metric
    with the raw path: an unbounded label value (one time series per
    distinct resource id ever requested) is exactly the "cardinality
    explosion" Prometheus's own documentation warns against, so an
    unmatched request (a genuine 404, prior to routing) is labeled with a
    fixed ``"unmatched"`` placeholder instead.

    The template is rebuilt from ``request.url.path`` plus
    ``scope["path_params"]`` rather than read off ``scope["route"].path``
    directly. Those are not the same string: a route registered on a
    router that was included under a prefix reports only its own
    router-relative path there (``/health``, not ``/api/v1/health``), so
    using it would silently merge same-suffix routes from different
    routers into one time series and drop the prefix from every metric.
    Substituting each matched path-param value back into the real request
    path yields the full, prefixed template while keeping cardinality
    bounded exactly as before.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Time the request and record its outcome.

        Args:
            request: The incoming request.
            call_next: The next stage in the middleware/router chain.

        Returns:
            The response, unmodified.
        """
        started = time.perf_counter()
        response = await call_next(request)
        duration_seconds = time.perf_counter() - started

        path_template = _templated_path(request)

        REQUEST_LATENCY_SECONDS.labels(method=request.method, path_template=path_template).observe(
            duration_seconds
        )
        REQUEST_COUNT.labels(
            method=request.method,
            path_template=path_template,
            status_code=str(response.status_code),
        ).inc()
        return response
