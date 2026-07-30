"""Centralized exception handling.

Converts every exception hierarchy this codebase defines into the same
JSON error envelope ``app.utils.response`` already builds, matching
``docs/api_design.md`` Sections 9/11 exactly. No exception class
anywhere in this codebase carries an HTTP status or ``ErrorCode`` of its
own — that mapping is built fresh here, keyed on ``isinstance`` checks,
the same dispatch style ``app.services.exceptions``'s own
``translate_*`` functions already use for their narrower translations.

The ``EAHError``/``AuthError``/``NotificationError``/``AnalyticsError``/
``EngineWorkflowError`` set registered below is the same set
``app.pages.components.run_with_feedback`` already catches for the
Streamlit Presentation Layer — this module answers with an HTTP response
instead of a flash message, but recognizes exactly the same exceptions.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.analytics.exceptions import AnalyticsError
from app.auth.exceptions import AuthenticationError, AuthError, AuthorizationError
from app.config.exceptions import ConfigurationError as ConfigConfigurationError
from app.models.exceptions import DomainError, EmptyUpdatePayloadError
from app.notifications.exceptions import NotificationError
from app.observability.metrics import RATE_LIMIT_REJECTIONS_TOTAL
from app.services.exceptions import (
    AssignmentError,
    ConcurrencyError,
    EAHError,
    InvalidInvitationStateError,
    InvitationConflictError,
    NotFoundError,
    StorageOperationError,
    ValidationError,
)
from app.services.exceptions import ConfigurationError as ServiceConfigurationError
from app.services.exceptions import PermissionDeniedError as ServicePermissionDeniedError
from app.services.exceptions import WorkflowError as ServiceWorkflowError
from app.utils.exceptions import UtilityError
from app.utils.rate_limiter import RateLimitExceededError
from app.utils.response import ErrorCode, build_error_response
from app.workflow.exceptions import WorkflowError as EngineWorkflowError

__all__ = ["register_exception_handlers"]

logger = logging.getLogger(__name__)


def _error_response(
    request: Request,
    *,
    code: ErrorCode,
    message: str,
    status_code: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build a ``JSONResponse`` using the existing ``app.utils.response`` envelope.

    Args:
        request: The current request, used only to read the correlation
            id ``RequestIDMiddleware`` already attached to
            ``request.state``.
        code: The machine-readable error code, from the fixed
            ``ErrorCode`` catalog.
        message: A human-readable, UI-safe summary.
        status_code: The HTTP status to respond with.
        headers: Additional response headers, if any (e.g. ``Retry-After``
            on a ``429``).

    Returns:
        A ``JSONResponse`` matching ``docs/api_design.md`` Section
        11.1's standard error format exactly.
    """
    request_id = getattr(request.state, "request_id", None)
    body = build_error_response(code, message, request_id=request_id)
    return JSONResponse(content=body, status_code=status_code, headers=headers)


async def _handle_eah_error(request: Request, exc: EAHError) -> JSONResponse:
    """Map every ``app.services.exceptions.EAHError`` subclass to its HTTP status.

    Field-level ``error.details`` population (Section 11.1) is deferred
    to whichever future phase implements validation-heavy write
    endpoints; Phase 0's two routes never exercise it.
    """
    if isinstance(exc, NotFoundError):
        return _error_response(
            request, code=ErrorCode.RESOURCE_NOT_FOUND, message=exc.message, status_code=404
        )
    if isinstance(exc, ValidationError):
        return _error_response(
            request, code=ErrorCode.VALIDATION_ERROR, message=exc.message, status_code=422
        )
    if isinstance(exc, InvitationConflictError):
        # Same category as a ConstraintViolationError-derived ValidationError
        # (see translate_database_error): a uniqueness conflict on write,
        # not an optimistic-locking version conflict (ConcurrencyError,
        # below) — mapped identically to that existing precedent rather
        # than introducing a new error code for the same kind of failure.
        return _error_response(
            request, code=ErrorCode.VALIDATION_ERROR, message=exc.message, status_code=422
        )
    if isinstance(exc, InvalidInvitationStateError):
        # Same category as an engine InvalidStateTransitionError (mapped
        # below, via WorkflowError, to the identical code/status): the
        # request is well-formed, but the invitation's current state does
        # not permit the attempted transition.
        return _error_response(
            request, code=ErrorCode.VALIDATION_ERROR, message=exc.message, status_code=422
        )
    if isinstance(exc, ServicePermissionDeniedError):
        return _error_response(
            request, code=ErrorCode.PERMISSION_DENIED, message=exc.message, status_code=403
        )
    if isinstance(exc, ConcurrencyError):
        return _error_response(
            request, code=ErrorCode.CONCURRENT_UPDATE, message=exc.message, status_code=409
        )
    if isinstance(exc, (ServiceWorkflowError, AssignmentError)):
        return _error_response(
            request, code=ErrorCode.VALIDATION_ERROR, message=exc.message, status_code=422
        )
    if isinstance(exc, ServiceConfigurationError):
        logger.error("Configuration/dependency error: %s", exc.message, exc_info=exc)
        return _error_response(
            request,
            code=ErrorCode.INTERNAL_ERROR,
            message="A required dependency is currently unavailable.",
            status_code=503,
        )
    if isinstance(exc, StorageOperationError):
        logger.error("Storage operation error: %s", exc.message, exc_info=exc)
        return _error_response(
            request,
            code=ErrorCode.INTERNAL_ERROR,
            message="A storage operation failed.",
            status_code=502,
        )
    logger.error("Unmapped EAHError subclass %s: %s", type(exc).__name__, exc.message, exc_info=exc)
    return _error_response(
        request,
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected error occurred.",
        status_code=500,
    )


async def _handle_auth_error(request: Request, exc: AuthError) -> JSONResponse:
    """Map every ``app.auth.exceptions.AuthError`` subclass to its HTTP status."""
    if isinstance(exc, AuthenticationError):
        return _error_response(
            request, code=ErrorCode.AUTHENTICATION_REQUIRED, message=exc.message, status_code=401
        )
    if isinstance(exc, AuthorizationError):
        return _error_response(
            request, code=ErrorCode.PERMISSION_DENIED, message=exc.message, status_code=403
        )
    return _error_response(
        request, code=ErrorCode.AUTHENTICATION_REQUIRED, message=exc.message, status_code=401
    )


async def _handle_engine_workflow_error(request: Request, exc: EngineWorkflowError) -> JSONResponse:
    """Defensive registration only.

    ``app.workflow.exceptions.WorkflowError`` should always be translated
    into an ``EAHError`` subclass by the service method that caught it
    (via ``translate_workflow_error``) before it escapes to this
    boundary — this handler exists only so an oversight fails safely (a
    422, not an unhandled 500 with a leaked stack trace).
    """
    logger.warning("Untranslated engine WorkflowError reached the API boundary: %s", exc.message)
    return _error_response(
        request, code=ErrorCode.VALIDATION_ERROR, message=exc.message, status_code=422
    )


async def _handle_defensive_error(request: Request, exc: Exception) -> JSONResponse:
    """Defensive registration for roots that should never escape a
    properly-behaving service method: ``NotificationError``,
    ``AnalyticsError``, ``DomainError``, ``ConfigurationError`` (config),
    ``UtilityError``. Logged loudly, since reaching here indicates a real
    gap in a service's own error handling, but still answered as a safe,
    generic 500 rather than propagating with a stack trace.
    """
    logger.error(
        "Unexpected %s reached the API boundary untranslated: %s",
        type(exc).__name__,
        exc,
        exc_info=exc,
    )
    return _error_response(
        request,
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected error occurred.",
        status_code=500,
    )


async def _handle_rate_limit_exceeded_error(
    request: Request, exc: RateLimitExceededError
) -> JSONResponse:
    """Map ``app.utils.rate_limiter.RateLimitExceededError`` to a standard
    ``429`` response with a ``Retry-After`` header (RFC 6585).

    Registered here (rather than built inline by
    ``app.api.rate_limiting.enforce_invitation_rate_limit``) so the rate
    limiter's dependency stays a plain, framework-thin "raise on
    exceeded" check, and every exception-to-HTTP-response mapping in this
    codebase continues to live in exactly one place, matching every other
    handler in this module.
    """
    RATE_LIMIT_REJECTIONS_TOTAL.inc()
    return _error_response(
        request,
        code=ErrorCode.RATE_LIMITED,
        message="Too many requests. Please try again later.",
        status_code=429,
        headers={"Retry-After": str(round(exc.retry_after_seconds))},
    )


async def _handle_empty_update_payload_error(
    request: Request, exc: EmptyUpdatePayloadError
) -> JSONResponse:
    """Map a partial-update (PATCH) payload with no field set to a 422.

    Per API-ADD Section 22 and ``EmptyUpdatePayloadError``'s own
    docstring — registered ahead of the generic ``DomainError`` handler
    (below) since Starlette dispatches to the most specific registered
    exception class, so this takes precedence over that handler's
    defensive 500 for this one, genuinely-expected case.
    """
    return _error_response(
        request, code=ErrorCode.VALIDATION_ERROR, message=exc.message, status_code=422
    )


async def _handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Reformat FastAPI's own built-in validation-error shape into this
    app's standard envelope.

    FastAPI installs a default handler for ``RequestValidationError``
    (malformed path/query parameters, e.g. a non-UUID ``{id}`` or a
    non-numeric ``page``) that returns ``{"detail": [...]}`` — a shape
    that never matches ``docs/api_design.md`` Section 11.1. Phase 0's two
    endpoints took no path/query parameters, so this was never triggered
    until Phase 2's endpoints introduced them.
    """
    return _error_response(
        request,
        code=ErrorCode.VALIDATION_ERROR,
        message="One or more request parameters failed validation.",
        status_code=422,
    )


async def _handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Final catch-all: never leak a stack trace to the client (API-ADD
    Section 11.2/24) — the full traceback is logged server-side only,
    correlated to the client-visible response solely via ``request_id``.
    """
    logger.error("Unhandled exception: %s", exc, exc_info=exc)
    return _error_response(
        request,
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected error occurred.",
        status_code=500,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register a handler for every exception root this codebase defines.

    Args:
        app: The FastAPI application to register handlers on.
    """
    # Each handler below is intentionally typed against its own specific
    # exception root (not the bare `Exception` Starlette's own stub
    # expects), since Starlette dispatches to a registered handler only
    # for that exact class or a subclass of it — runtime-safe, but a
    # mismatch mypy's stub can't express; hence the targeted ignores.
    app.add_exception_handler(EAHError, _handle_eah_error)  # type: ignore[arg-type]
    app.add_exception_handler(AuthError, _handle_auth_error)  # type: ignore[arg-type]
    app.add_exception_handler(EngineWorkflowError, _handle_engine_workflow_error)  # type: ignore[arg-type]
    app.add_exception_handler(NotificationError, _handle_defensive_error)
    app.add_exception_handler(AnalyticsError, _handle_defensive_error)
    app.add_exception_handler(DomainError, _handle_defensive_error)
    app.add_exception_handler(EmptyUpdatePayloadError, _handle_empty_update_payload_error)  # type: ignore[arg-type]
    app.add_exception_handler(ConfigConfigurationError, _handle_defensive_error)
    app.add_exception_handler(UtilityError, _handle_defensive_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(RateLimitExceededError, _handle_rate_limit_exceeded_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _handle_unhandled_exception)
