"""FastAPI dependency providers.

Every provider here returns an already-constructed object from
``app.bootstrap.ApplicationResources`` (built once at process startup, in
``app.api.main``'s ``lifespan`` handler, and stored on
``app.state.resources``) — no provider here constructs a service,
repository, or engine itself; that remains ``app.bootstrap``'s job alone.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import AsyncIterator

from fastapi import Depends, Request

from app.analytics.interfaces import (
    AnalyticsProvider,
    OperationalAnalyticsProvider,
    ReportingProvider,
)
from app.auth.authentication import AuthenticatedIdentity, extract_bearer_token
from app.auth.middleware import AuthenticationMiddleware, RequestContext
from app.bootstrap import ApplicationResources
from app.config.security import AUTHORIZATION_HEADER_NAME
from app.database.client import DatabaseClient, SupabaseClientFactory
from app.database.exceptions import DatabaseConnectionError
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import (
    bind_current_tenant_client,
    reset_current_tenant_client,
)
from app.database.repositories.user_repository import ProfileRepository
from app.services.ai_insight_service import AiInsightService
from app.services.approval_service import ApprovalService
from app.services.attachment_service import AttachmentService
from app.services.comment_service import CommentService
from app.services.company_service import CompanyService
from app.services.dashboard_service import DashboardService
from app.services.feature_flag_service import FeatureFlagService
from app.services.invitation_service import InvitationService
from app.services.notification_service import NotificationService
from app.services.request_service import RequestService
from app.services.search_service import GlobalSearchService
from app.services.user_service import UserService
from app.services.workflow_definition_service import WorkflowDefinitionService

logger = logging.getLogger(__name__)

__all__ = [
    "get_resources",
    "get_request_service",
    "get_approval_service",
    "get_workflow_definition_service",
    "get_notification_service",
    "get_comment_service",
    "get_attachment_service",
    "get_search_service",
    "get_ai_insight_service",
    "get_dashboard_service",
    "get_invitation_service",
    "get_company_service",
    "get_feature_flag_service",
    "get_analytics_provider",
    "get_reporting_provider",
    "get_operational_analytics_provider",
    "get_audit_repository",
    "get_approval_repository",
    "get_profile_repository",
    "get_database_client",
    "get_current_identity",
    "bind_tenant_database_client",
]


def get_resources(request: Request) -> ApplicationResources:
    """Return the process-wide ``ApplicationResources`` built at startup.

    Args:
        request: The current request, used only to reach ``app.state``.

    Returns:
        The single ``ApplicationResources`` instance ``app.api.main``'s
        ``lifespan`` handler constructed once for this process.
    """
    return request.app.state.resources


def get_request_service(resources: ApplicationResources = Depends(get_resources)) -> RequestService:
    """Provide ``RequestService``."""
    return resources.request_service


def get_approval_service(
    resources: ApplicationResources = Depends(get_resources),
) -> ApprovalService:
    """Provide ``ApprovalService``."""
    return resources.approval_service


def get_workflow_definition_service(
    resources: ApplicationResources = Depends(get_resources),
) -> WorkflowDefinitionService:
    """Provide ``WorkflowDefinitionService``."""
    return resources.workflow_definition_service


def get_notification_service(
    resources: ApplicationResources = Depends(get_resources),
) -> NotificationService:
    """Provide ``NotificationService``."""
    return resources.notification_service


def get_comment_service(resources: ApplicationResources = Depends(get_resources)) -> CommentService:
    """Provide ``CommentService``."""
    return resources.comment_service


def get_attachment_service(
    resources: ApplicationResources = Depends(get_resources),
) -> AttachmentService:
    """Provide ``AttachmentService``."""
    return resources.attachment_service


def get_search_service(
    resources: ApplicationResources = Depends(get_resources),
) -> GlobalSearchService:
    """Provide ``GlobalSearchService``."""
    return resources.search_service


def get_ai_insight_service(
    resources: ApplicationResources = Depends(get_resources),
) -> AiInsightService:
    """Provide ``AiInsightService``."""
    return resources.ai_insight_service


def get_dashboard_service(
    resources: ApplicationResources = Depends(get_resources),
) -> DashboardService:
    """Provide ``DashboardService``."""
    return resources.dashboard_service


def get_invitation_service(
    resources: ApplicationResources = Depends(get_resources),
) -> InvitationService:
    """Provide ``InvitationService``."""
    return resources.invitation_service


def get_company_service(
    resources: ApplicationResources = Depends(get_resources),
) -> CompanyService:
    """Provide ``CompanyService``."""
    return resources.company_service


def get_user_service(
    resources: ApplicationResources = Depends(get_resources),
) -> UserService:
    """Provide ``UserService`` (role/department, deactivation, GDPR erasure)."""
    return resources.user_service


def get_feature_flag_service(
    resources: ApplicationResources = Depends(get_resources),
) -> FeatureFlagService:
    """Provide ``FeatureFlagService``."""
    return resources.feature_flag_service


def get_analytics_provider(
    resources: ApplicationResources = Depends(get_resources),
) -> AnalyticsProvider:
    """Provide the read-only analytics engine."""
    return resources.analytics_provider


def get_reporting_provider(
    resources: ApplicationResources = Depends(get_resources),
) -> ReportingProvider:
    """Provide the read-only reporting engine."""
    return resources.reporting_provider


def get_operational_analytics_provider(
    resources: ApplicationResources = Depends(get_resources),
) -> OperationalAnalyticsProvider:
    """Provide the read-only operational analytics engine."""
    return resources.operational_analytics_provider


def get_audit_repository(
    resources: ApplicationResources = Depends(get_resources),
) -> AuditRepository:
    """Provide ``AuditRepository`` directly.

    A narrow, documented exception to this module's usual "return an
    Application Service" pattern — see
    ``app.api.routers.analytics``'s module docstring for why the
    "Recent Activity" feed has no Application Service method to wrap.
    """
    return resources.audit_repo


def get_approval_repository(
    resources: ApplicationResources = Depends(get_resources),
) -> ApprovalRepository:
    """Provide ``ApprovalRepository`` directly.

    Same narrow exception as ``get_audit_repository``, backing the
    "Aging Requests" view via ``list_overdue_stages``.
    """
    return resources.approval_repo


def get_profile_repository(
    resources: ApplicationResources = Depends(get_resources),
) -> ProfileRepository:
    """Provide ``ProfileRepository`` directly (already used this way by
    ``SupabaseTokenVerifier``'s own construction) — needed to resolve
    actor display names for the "Recent Activity" feed."""
    return resources.profile_repo


def get_database_client(
    resources: ApplicationResources = Depends(get_resources),
) -> DatabaseClient:
    """Provide the underlying Supabase client directly.

    A narrow, documented exception mirroring ``get_audit_repository``'s
    — used only by ``GET /health`` for its Supabase-reachability check.
    """
    return resources.database_client


def get_current_identity(
    request: Request, resources: ApplicationResources = Depends(get_resources)
) -> AuthenticatedIdentity:
    """Resolve and validate the caller's identity from the ``Authorization`` header.

    Reuses ``app.auth.middleware.AuthenticationMiddleware`` unmodified,
    supplying ``resources.token_verifier.resolve_claims`` as its
    ``ClaimsResolver`` — per API-ADD Section 5.3, a request with a
    missing, malformed, or expired token never reaches a route handler;
    the corresponding ``app.auth.exceptions.AuthError`` subclass raised
    here propagates to the centralized exception handler instead.

    Note: ``request.headers`` (a Starlette ``Headers`` object) is passed
    directly, not ``dict(request.headers)`` — ASGI header names arrive
    lowercased, so converting to a plain ``dict`` first would make a
    case-sensitive ``"Authorization"`` lookup always miss. Starlette's
    ``Headers`` already provides the case-insensitive ``.get()``
    ``RequestContext``/``extract_bearer_token`` expect.

    This makes a real Supabase network call on every request (no
    server-side session/token cache exists, per API-ADD Section 5.5/5.6),
    so it is declared as a plain (synchronous) function — FastAPI runs
    synchronous dependencies in a thread pool, keeping this blocking call
    off the event loop.

    Args:
        request: The current request, used to read its headers.
        resources: The process-wide resource bundle.

    Returns:
        The resolved, validated ``AuthenticatedIdentity``.

    Raises:
        app.auth.exceptions.AuthError: If the token is missing,
            malformed, invalid, or its subject has no ``profiles`` row.
    """
    middleware = AuthenticationMiddleware(claims_resolver=resources.token_verifier.resolve_claims)
    context = RequestContext(headers=request.headers)
    result = middleware.process(context)
    assert result.identity is not None  # AuthenticationMiddleware.process always sets it or raises
    # Stashed for RequestLoggingMiddleware (app.api.middleware), which runs
    # as outer ASGI middleware with no visibility into this per-route
    # dependency otherwise — the same request.state pattern RequestIDMiddleware
    # already uses for request_id.
    request.state.user_id = str(result.identity.user_id)
    return result.identity


async def bind_tenant_database_client(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> AsyncIterator[None]:
    """Bind a per-request, caller-scoped database client for the duration
    of this request, so Row-Level Security is actually enforced for the
    repositories verified safe to run under it (see
    ``BaseRepository.always_use_injected_client``'s docstring for exactly
    which ones, and why the rest deliberately stay on the service-role
    client instead).

    This is declared as an **async generator** dependency (``async def
    ... yield``), not a plain sync ``def`` — deliberately. FastAPI/Starlette
    dispatches a sync dependency or endpoint through a thread pool via a
    *copy* of the current ``contextvars.Context``; a ``ContextVar.set()``
    made inside that copy never propagates back to the request's own task.
    An async generator dependency, by contrast, runs directly on the
    request's event-loop task, so the ``bind_current_tenant_client`` call
    below happens in the *same* context every subsequent dependency and
    the endpoint itself will read from (whether or not those are
    threadpooled sync code) — reads from a later-copied context always see
    a value set earlier in the ambient one. Attached once, at the
    ``app.api.main.create_app`` ``include_router`` call, via the same
    ``_rate_limited`` dependency list every authenticated router already
    uses for ``enforce_rate_limit`` (which already depends on
    ``get_current_identity`` — FastAPI's per-request dependency caching
    means the one real Supabase network call this triggers is not
    duplicated).

    Args:
        request: The current request, used to read its raw ``Authorization``
            header (the identity dependency below resolves and validates
            the token, but does not retain the raw string).
        identity: The already-resolved, already-validated caller identity —
            depended on directly (rather than assumed already resolved by
            an earlier dependency in the same list) so this function's own
            correctness does not depend on dependency-list ordering
            elsewhere, and to log which caller a client was bound for.
        resources: The process-wide resource bundle, used only for its
            ``supabase_connection_settings``.

    Yields:
        Nothing — this dependency exists entirely for its bind/reset side
        effect around the request.
    """
    token = extract_bearer_token(request.headers.get(AUTHORIZATION_HEADER_NAME))
    reset_token: contextvars.Token[DatabaseClient | None] | None = None
    try:
        tenant_client = SupabaseClientFactory.create_user_scoped_client(
            resources.supabase_connection_settings, token
        )
    except DatabaseConnectionError:
        # Never fatal to the request: every repository this would matter
        # for already falls back to its own constructor-injected default
        # client (today, always the service-role one) when no tenant
        # client is bound — exactly the same behavior as before this
        # mechanism existed. Logged as an error (never silent) since, on a
        # real deployment with valid connection settings, this path is
        # expected to be unreachable — reaching it in production would
        # mean something is actually misconfigured. In unit tests that
        # stub `ApplicationResources` without real connection settings
        # (unrelated to tenant-isolation behavior), this keeps every route
        # working exactly as it did before this dependency existed.
        logger.error(
            "Could not construct a tenant-scoped database client for user %s; "
            "falling back to each repository's default client for this request.",
            identity.user_id,
            extra={"user_id": str(identity.user_id)},
        )
    else:
        logger.debug(
            "Bound tenant-scoped database client for user %s",
            identity.user_id,
            extra={"user_id": str(identity.user_id)},
        )
        reset_token = bind_current_tenant_client(tenant_client)
    try:
        yield
    finally:
        if reset_token is not None:
            reset_current_tenant_client(reset_token)
