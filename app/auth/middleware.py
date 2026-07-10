"""Framework-agnostic authentication and authorization middleware.

The fixed technology stack includes no web framework (per the ADD, the
API Design Document's contract is a specification layer over in-process
calls, API-ADD Section 1.2), so "middleware" here is a small, composable
pipeline abstraction rather than a binding to any specific framework's
middleware system. Each middleware component transforms an immutable
``RequestContext`` into a new one, and a ``MiddlewarePipeline`` chains
several together — the same shape a future HTTP-binding layer (API-ADD
Section 32) could adapt to whatever framework it eventually introduces,
without requiring these components to change.

Per this package's constraint that middleware handles only
authentication/authorization concerns, ``AuthenticationMiddleware`` and
``AuthorizationMiddleware`` are the only two middleware components
defined here, and neither performs any business logic, persistence
access, or Presentation Layer concern. ``AuthorizationMiddleware``
delegates its actual decision to ``app.auth.authorization``, the single
module in this package that knows how to combine an
``AuthenticatedIdentity`` with an authorization outcome.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Protocol

from app.auth import authorization
from app.auth.authentication import AuthenticatedIdentity, extract_bearer_token
from app.auth.exceptions import MissingCredentialsError
from app.auth.permissions import Permission
from app.config.security import AUTHORIZATION_HEADER_NAME

__all__ = [
    "RequestContext",
    "Middleware",
    "AuthenticationMiddleware",
    "AuthorizationMiddleware",
    "MiddlewarePipeline",
]

logger = logging.getLogger(__name__)

#: A callable that, given a raw bearer token, returns the already-verified
#: claims mapping for it. In production this is expected to be a thin
#: wrapper around Supabase's own ``client.auth.get_user(token)`` call,
#: supplied by a future service-layer package that holds the actual
#: Supabase client connection — this module never constructs or calls
#: such a client itself, per this package's "no database access"
#: constraint.
ClaimsResolver = Callable[[str], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class RequestContext:
    """An immutable representation of a single call's authentication and
    authorization state as it passes through the middleware pipeline.

    Attributes:
        headers: The incoming request's header mapping (case-sensitivity
            is the caller's responsibility; this module reads exactly the
            key named by ``app.config.security.AUTHORIZATION_HEADER_NAME``).
        identity: The resolved caller identity, populated by
            ``AuthenticationMiddleware``; ``None`` before that middleware
            has run.
    """

    headers: Mapping[str, str]
    identity: AuthenticatedIdentity | None = None


class Middleware(Protocol):
    """Structural interface every middleware component in this module
    satisfies."""

    def process(self, context: RequestContext) -> RequestContext:
        """Transform a ``RequestContext``, returning a new one.

        Args:
            context: The context as received from the previous stage in
                the pipeline (or the pipeline's initial input).

        Returns:
            A new ``RequestContext`` reflecting this middleware's effect.
        """
        ...


class AuthenticationMiddleware:
    """Resolves the caller's identity from the request's bearer token.

    Depends on an injected ``ClaimsResolver`` to obtain already-verified
    claims for a token — this class itself never performs cryptographic
    verification or network access (per ``app.auth.authentication``'s own
    documented boundary).
    """

    def __init__(self, claims_resolver: ClaimsResolver) -> None:
        """Initialize the middleware with an injected claims resolver.

        Args:
            claims_resolver: A callable returning verified claims for a
                given bearer token.
        """
        self._claims_resolver = claims_resolver

    def process(self, context: RequestContext) -> RequestContext:
        """Extract the bearer token, resolve its claims, and attach the
        resulting identity to the context.

        Args:
            context: The incoming request context.

        Returns:
            A new ``RequestContext`` with ``identity`` populated.

        Raises:
            MissingCredentialsError: If no ``Authorization`` header is
                present.
            MalformedAuthorizationHeaderError: If the header does not
                match the expected ``Bearer <token>`` shape.
            InvalidTokenError: If the resolved claims are missing a
                required field.
            TokenExpiredError: If the resolved claims indicate the token
                has already expired.
        """
        raw_header = context.headers.get(AUTHORIZATION_HEADER_NAME)
        token = extract_bearer_token(raw_header)
        claims = self._claims_resolver(token)
        identity = AuthenticatedIdentity.from_claims(claims)
        logger.debug(
            "Authenticated request for user %s",
            identity.user_id,
            extra={"user_id": str(identity.user_id), "role": identity.role.value},
        )
        return replace(context, identity=identity)


class AuthorizationMiddleware:
    """Enforces that the already-authenticated caller holds a required permission.

    Must run after ``AuthenticationMiddleware`` in a pipeline, since it
    requires ``context.identity`` to already be populated. The actual
    enforcement decision is delegated to
    ``app.auth.authorization.authorize_permission``, keeping this class a
    thin pipeline adapter rather than a second place authorization logic
    is implemented.
    """

    def __init__(self, required_permission: Permission) -> None:
        """Initialize the middleware with the permission it enforces.

        Args:
            required_permission: The permission the caller must hold.
        """
        self._required_permission = required_permission

    def process(self, context: RequestContext) -> RequestContext:
        """Verify the context's identity holds the required permission.

        Args:
            context: The context produced by a prior
                ``AuthenticationMiddleware`` stage.

        Returns:
            ``context``, unchanged, if authorization succeeds.

        Raises:
            MissingCredentialsError: If ``context.identity`` is ``None``
                (this middleware ran before authentication, which is a
                pipeline configuration error).
            SessionExpiredError: If the identity's token has expired.
            PermissionDeniedError: If the identity's role does not carry
                the required permission.
        """
        if context.identity is None:
            raise MissingCredentialsError()
        authorization.authorize_permission(context.identity, self._required_permission)
        return context


class MiddlewarePipeline:
    """Chains a sequence of ``Middleware`` components into a single callable.

    Each middleware's output context becomes the next middleware's input,
    in the order supplied.
    """

    def __init__(self, *middlewares: Middleware) -> None:
        """Initialize the pipeline with an ordered sequence of middleware.

        Args:
            *middlewares: The middleware components to apply, in order.
        """
        self._middlewares: tuple[Middleware, ...] = middlewares

    def run(self, context: RequestContext) -> RequestContext:
        """Apply every middleware in sequence to a context.

        Args:
            context: The initial request context.

        Returns:
            The final context after every middleware has run.

        Raises:
            AuthError: Any exception a constituent middleware raises
                propagates immediately, halting the pipeline.
        """
        current = context
        for middleware in self._middlewares:
            current = middleware.process(current)
        return current