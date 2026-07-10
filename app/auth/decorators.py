"""Reusable authentication- and permission-enforcement decorators.

These decorators are deliberately framework-agnostic — there is no web
framework in the fixed technology stack for them to bind to. Each
decorator factory accepts a small, explicitly injected callable
(``identity_getter``) that, given the same arguments the wrapped function
receives, returns the ``AuthenticatedIdentity`` currently in effect. This
keeps every decorator here fully generic, dependency-injectable, and
independently unit-testable without any global request/session context,
consistent with this package's "ready for dependency injection and unit
testing" requirement.

Per this package's core design constraint, authentication concerns
(``require_authentication``) and authorization concerns
(``require_permission_decorator``, ``require_role_decorator``) are
provided as entirely separate decorators, so that a caller applies
exactly the check it needs rather than a single, conflated decorator that
always does both. All permission- and role-based enforcement here is
delegated to ``app.auth.authorization``, which is itself the only module
that knows how to combine an ``AuthenticatedIdentity`` with an
authorization decision — this module never calls ``app.auth.rbac``
directly, so there is exactly one place in the package where "identity +
rbac predicate" logic lives.
"""

from __future__ import annotations

import functools
import logging
from typing import Callable, ParamSpec, TypeVar

from app.auth import authorization
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import MissingCredentialsError, SessionExpiredError
from app.auth.permissions import Permission
from app.models.enums import UserRole

__all__ = ["require_authentication", "require_permission_decorator", "require_role_decorator"]

P = ParamSpec("P")
R = TypeVar("R")

logger = logging.getLogger(__name__)

IdentityGetter = Callable[..., AuthenticatedIdentity | None]


def _resolve_identity_or_raise(
    identity_getter: IdentityGetter, args: tuple, kwargs: dict
) -> AuthenticatedIdentity:
    """Resolve the current identity, raising if absent or expired.

    Args:
        identity_getter: The injected callable that resolves an identity
            from the wrapped function's own arguments.
        args: The wrapped function's positional arguments.
        kwargs: The wrapped function's keyword arguments.

    Returns:
        A non-expired ``AuthenticatedIdentity``.

    Raises:
        MissingCredentialsError: If ``identity_getter`` returns ``None``.
        SessionExpiredError: If the resolved identity's token has
            already expired.
    """
    identity = identity_getter(*args, **kwargs)
    if identity is None:
        raise MissingCredentialsError()
    if identity.is_expired:
        raise SessionExpiredError()
    return identity


def require_authentication(
    *, identity_getter: IdentityGetter
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator enforcing that a valid, non-expired identity is present.

    Args:
        identity_getter: A callable, invoked with the wrapped function's
            own ``*args``/``**kwargs``, that returns the current
            ``AuthenticatedIdentity`` or ``None`` if no caller is
            currently authenticated.

    Returns:
        A decorator that raises before invoking the wrapped function if
        no valid identity is present.

    Raises:
        MissingCredentialsError: If no identity is present.
        SessionExpiredError: If the resolved identity's token has
            already expired.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            _resolve_identity_or_raise(identity_getter, args, kwargs)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def require_permission_decorator(
    permission: Permission, *, identity_getter: IdentityGetter
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator enforcing that the current caller's role carries a
    given permission.

    This decorator implies authentication (an identity must be present
    to have a role to check at all); the required identity presence and
    expiry checks are performed as part of resolving the identity below,
    so callers do not need to stack a separate ``require_authentication``
    decorator alongside this one for the common case.

    Args:
        permission: The permission required.
        identity_getter: A callable, invoked with the wrapped function's
            own ``*args``/``**kwargs``, that returns the current
            ``AuthenticatedIdentity`` or ``None``.

    Returns:
        A decorator that raises before invoking the wrapped function if
        the current caller is not authenticated or does not hold
        ``permission``.

    Raises:
        MissingCredentialsError: If no identity is present.
        SessionExpiredError: If the identity's token has expired.
        PermissionDeniedError: If the identity's role does not carry
            ``permission``.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            identity = _resolve_identity_or_raise(identity_getter, args, kwargs)
            authorization.authorize_permission(identity, permission)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def require_role_decorator(
    *allowed_roles: UserRole, identity_getter: IdentityGetter
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator enforcing that the current caller's role is among a
    fixed set of explicitly permitted roles.

    Args:
        *allowed_roles: The roles permitted to invoke the wrapped
            function.
        identity_getter: A callable, invoked with the wrapped function's
            own ``*args``/``**kwargs``, that returns the current
            ``AuthenticatedIdentity`` or ``None``.

    Returns:
        A decorator that raises before invoking the wrapped function if
        the current caller is not authenticated or their role is not in
        ``allowed_roles``.

    Raises:
        MissingCredentialsError: If no identity is present.
        SessionExpiredError: If the identity's token has expired.
        RoleNotPermittedError: If the identity's role is not in
            ``allowed_roles``.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            identity = _resolve_identity_or_raise(identity_getter, args, kwargs)
            authorization.authorize_role(identity, *allowed_roles)
            return func(*args, **kwargs)

        return wrapper

    return decorator