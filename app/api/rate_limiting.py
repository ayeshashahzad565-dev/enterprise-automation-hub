"""Rate limiting for every authenticated route, plus the public
invitation endpoints — FastAPI glue.

Two independent enforcement mechanisms live in this module:

1. **Per-authenticated-user** (``enforce_rate_limit``,
   ``enforce_upload_rate_limit``, ``enforce_notification_poll_rate_limit``):
   the general case for every route that requires a bearer token,
   matching ``docs/api_design.md`` Section 15's original design —
   "enforced per authenticated user (keyed on ``profiles.id``), not per
   IP address, since this is an internally-authenticated system." Applied
   at ``app.api.main``'s ``include_router`` call sites (one dependency per
   router, method-aware so a single dependency covers both its
   ``GET``/read and its ``POST``/``PUT``/``PATCH``/``DELETE``/write
   routes), plus two narrower, route-specific dependencies for the two
   endpoints that have their own dedicated budget in
   ``app.config.settings.RateLimitSettings``: attachment upload/replace
   (``upload_per_minute``) and the notification unread-count poll
   endpoint (``notification_poll_per_minute``).

2. **Per-IP** (``enforce_invitation_rate_limit``): ``GET
   /invitations/validate`` and ``POST /invitations/accept`` are this
   codebase's only unauthenticated entry points, so there is no
   ``profiles.id`` to key on for either — IP address is the correct,
   narrowly-scoped exception for exactly this pair of routes.

The actual counting logic for both lives in the framework-agnostic
``app.utils.rate_limiter.InMemoryRateLimiter`` — see that module's
docstring for the known single-process-only limitation this implies in a
multi-instance deployment, and why that trade-off was accepted rather
than introducing a new (Redis or similar) infrastructure dependency. A
``RateLimitExceededError`` raised by any function in this module is
mapped to a standard ``429`` response with a ``Retry-After`` header by
``app.api.exception_handlers``.

**Fail-closed, not fail-open**: if a caller's IP cannot be determined
(``request.client`` absent — possible in some deployment/proxy
configurations or test harnesses), every such request is bucketed under
one shared, fixed key rather than skipping the check entirely — an
attacker cannot bypass the limit merely by causing the IP to be
unresolvable.
"""

from __future__ import annotations

import logging

from fastapi import Depends, Request

from app.api.dependencies import get_current_identity, get_resources
from app.auth.authentication import AuthenticatedIdentity
from app.bootstrap import ApplicationResources

logger = logging.getLogger(__name__)

__all__ = [
    "enforce_invitation_rate_limit",
    "enforce_rate_limit",
    "enforce_upload_rate_limit",
    "enforce_notification_poll_rate_limit",
    "enforce_search_rate_limit",
    "enforce_ai_rate_limit",
]

#: HTTP methods treated as "read" for the read/write rate-limit split —
#: everything else (POST, PUT, PATCH, DELETE) is "write".
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: The bucket key used when a caller's IP address cannot be determined —
#: see this module's docstring for why this is fail-closed rather than a
#: skip.
_UNKNOWN_CLIENT_KEY = "unknown"


def _client_key(request: Request) -> str:
    """Resolve the bucket key for a request: the caller's IP, or a fixed
    fallback if it cannot be determined.

    Args:
        request: The incoming request.

    Returns:
        ``request.client.host``, or ``_UNKNOWN_CLIENT_KEY`` if
        unavailable — see this module's docstring for why this is
        fail-closed rather than a skip.
    """
    client = request.client
    if client is None or not client.host:
        return _UNKNOWN_CLIENT_KEY
    return client.host


def enforce_invitation_rate_limit(
    request: Request,
    resources: ApplicationResources = Depends(get_resources),
) -> None:
    """FastAPI dependency: enforce the configured public-invitation rate
    limit for the calling IP address.

    Intended to be attached only to ``GET /invitations/validate`` and
    ``POST /invitations/accept`` (via that router's own
    ``dependencies=[Depends(enforce_invitation_rate_limit)]``) — never
    registered as global middleware, so no other route is ever affected.

    Args:
        request: The incoming request, used to resolve the caller's IP.
        resources: The process-wide resource bundle, providing the
            single ``InMemoryRateLimiter`` instance constructed for this
            process (see ``app.bootstrap.build_application_resources``).

    Raises:
        app.utils.rate_limiter.RateLimitExceededError: If the calling IP
            has exceeded the configured limit within the current window.
    """
    resources.invitation_rate_limiter.check(_client_key(request))


def _identity_key(identity: AuthenticatedIdentity) -> str:
    """Resolve the bucket key for an authenticated caller: their user id.

    Args:
        identity: The caller's already-resolved identity.

    Returns:
        A per-user bucket key, matching ``docs/api_design.md`` Section
        15's "keyed on ``profiles.id``" design.
    """
    return str(identity.user_id)


def enforce_rate_limit(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> None:
    """FastAPI dependency: enforce the caller's general read/write rate limit.

    Method-aware, so a single dependency — attached once, per router, at
    each ``app.api.main.create_app`` ``include_router`` call — covers
    every route that router registers: ``GET``/``HEAD``/``OPTIONS``
    consume the ``read_per_minute`` budget, every other method (write,
    including approval decisions and administrative mutations) consumes
    the ``write_per_minute`` budget. Both are keyed per authenticated
    user, per ``docs/api_design.md`` Section 15.

    Args:
        request: The incoming request, used only to read its HTTP method.
        identity: The caller's already-resolved identity (also proves
            authentication ran before this check, so an unauthenticated
            request never reaches — or exhausts — a rate-limit bucket).
        resources: The process-wide resource bundle.

    Raises:
        app.utils.rate_limiter.RateLimitExceededError: If the caller has
            exceeded the applicable limit within the current window.
    """
    limiter = (
        resources.read_rate_limiter
        if request.method in _READ_METHODS
        else resources.write_rate_limiter
    )
    limiter.check(_identity_key(identity))


def enforce_upload_rate_limit(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> None:
    """FastAPI dependency: enforce the caller's attachment-upload rate limit.

    Attached directly to ``POST /requests/{id}/attachments`` and ``PUT
    /attachments/{id}`` — the two endpoints ``upload_per_minute`` is
    documented for — in addition to (not instead of) the attachments
    router's own general ``enforce_rate_limit``, so an upload also counts
    against the caller's general write budget as normal, plus this
    tighter, upload-specific one.

    Args:
        identity: The caller's already-resolved identity.
        resources: The process-wide resource bundle.

    Raises:
        app.utils.rate_limiter.RateLimitExceededError: If the caller has
            exceeded the upload limit within the current window.
    """
    resources.upload_rate_limiter.check(_identity_key(identity))


def enforce_notification_poll_rate_limit(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> None:
    """FastAPI dependency: enforce the caller's notification-poll rate limit.

    Attached directly to ``GET /notifications/unread-count`` — the
    endpoint ``notification_poll_per_minute`` is documented for, expected
    to be polled far more frequently than an ordinary read endpoint — in
    addition to (not instead of) the notifications router's own general
    ``enforce_rate_limit``.

    Args:
        identity: The caller's already-resolved identity.
        resources: The process-wide resource bundle.

    Raises:
        app.utils.rate_limiter.RateLimitExceededError: If the caller has
            exceeded the poll limit within the current window.
    """
    resources.notification_poll_rate_limiter.check(_identity_key(identity))


def enforce_search_rate_limit(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> None:
    """FastAPI dependency: enforce the caller's search rate limit.

    Attached directly to ``GET /search`` — the endpoint ``search_per_minute``
    is documented for, expected to be polled once per debounced keystroke
    by both the command palette and the dedicated search page — in
    addition to (not instead of) the search router's own general
    ``enforce_rate_limit``.

    Args:
        identity: The caller's already-resolved identity.
        resources: The process-wide resource bundle.

    Raises:
        app.utils.rate_limiter.RateLimitExceededError: If the caller has
            exceeded the search limit within the current window.
    """
    resources.search_rate_limiter.check(_identity_key(identity))


def enforce_ai_rate_limit(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> None:
    """FastAPI dependency: enforce the caller's AI rate limit.

    Attached to every route in ``app.api.routers.ai`` (via that router's
    own ``dependencies=[Depends(enforce_ai_rate_limit)]``) — in addition to
    (not instead of) the general ``enforce_rate_limit`` — since every one
    of those routes may invoke a paid, multi-second external AI provider
    request rather than a local database query, warranting a materially
    tighter budget than an ordinary read endpoint.

    Args:
        identity: The caller's already-resolved identity.
        resources: The process-wide resource bundle.

    Raises:
        app.utils.rate_limiter.RateLimitExceededError: If the caller has
            exceeded the AI limit within the current window.
    """
    resources.ai_rate_limiter.check(_identity_key(identity))
