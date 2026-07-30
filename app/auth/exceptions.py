"""Custom exception hierarchy for the app.auth package.

Per this package's core design constraint — authorization must be
completely separated from authentication — this module defines two
independent exception branches rooted in a common ``AuthError`` base
that carries no shared behavior beyond a message string:

- ``AuthenticationError`` and its subclasses: raised when *identity*
  cannot be established (missing, malformed, or expired credentials).
- ``AuthorizationError`` and its subclasses: raised when identity is
  established but the identified caller is not *permitted* to perform a
  given action.

A third, narrower branch, ``CredentialValidationError``, covers input
validation for a raw credential value (e.g. an empty password) prior to
it ever being forwarded to Supabase Auth — this is neither an
authentication failure (no identity check has occurred yet) nor an
authorization failure (no permission check is involved), so it is kept
distinct from both.

No other module in ``app.auth`` defines its own exception type.
"""

from __future__ import annotations


class AuthError(Exception):
    """Base class for every exception raised by the app.auth package.

    Attributes:
        message: A human-readable description of the failure.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{self.__class__.__name__}(message={self.message!r})"


# ---------------------------------------------------------------------------
# Authentication branch — identity establishment failures
# ---------------------------------------------------------------------------


class AuthenticationError(AuthError):
    """Base class for every failure to establish the caller's identity."""


class MissingCredentialsError(AuthenticationError):
    """Raised when no bearer token was supplied at all.

    Corresponds to API-ADD Section 11.3's ``AUTHENTICATION_REQUIRED``
    error code for the case of a wholly absent ``Authorization`` header.
    """

    def __init__(self) -> None:
        super().__init__("No bearer token was supplied in the Authorization header.")


class MalformedAuthorizationHeaderError(AuthenticationError):
    """Raised when an ``Authorization`` header is present but does not
    match the expected ``Bearer <token>`` scheme (API-ADD Section 3.2).

    Attributes:
        raw_value: The header's raw, unparsed value.
    """

    def __init__(self, raw_value: str) -> None:
        super().__init__("Authorization header is malformed; expected 'Bearer <token>'.")
        self.raw_value = raw_value


class InvalidTokenError(AuthenticationError):
    """Raised when a bearer token's claims cannot be resolved into a
    valid ``AuthenticatedIdentity`` — for example, missing a required
    claim such as ``sub`` or ``role``.
    """


class TokenExpiredError(AuthenticationError):
    """Raised when a token's claims indicate it has already expired.

    Attributes:
        expired_at: The token's expiry timestamp, for diagnostic context.
    """

    def __init__(self, expired_at: object) -> None:
        super().__init__(f"Token expired at {expired_at}.")
        self.expired_at = expired_at


class CompanyAccessRevokedError(AuthenticationError):
    """Raised when an otherwise-valid caller's company has been suspended
    or deleted by a platform admin.

    The caller's own credentials are fine — Supabase Auth and the
    ``profiles`` lookup both succeeded — but their tenant is no longer
    usable, which this package treats as an authentication-branch
    failure (the identity cannot be resolved into a *usable* identity),
    the same category ``SupabaseTokenVerifier`` already uses for "this
    account is not fully provisioned."

    Attributes:
        reason: A short, human-readable reason (``"suspended"`` or
            ``"deleted"``).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"This account's company has been {reason}. Contact an administrator.")
        self.reason = reason


class AccountAccessRevokedError(AuthenticationError):
    """Raised when an otherwise-valid caller's own profile has been
    deactivated or erased.

    Mirrors ``CompanyAccessRevokedError`` exactly, one level down: the
    caller's credentials and tenant are both fine, but their own account
    is not usable, per ``app.services.user_service.UserService.
    update_profile``/``erase_user``. Checked by
    ``SupabaseTokenVerifier`` on every request, so deactivation/erasure
    takes effect immediately rather than at next login.

    Attributes:
        reason: A short, human-readable reason (``"deactivated"`` or
            ``"erased"``).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"This account has been {reason}. Contact an administrator.")
        self.reason = reason


class SessionNotFoundError(AuthenticationError):
    """Raised when no active session exists where one was expected
    (API-ADD Section 5.6, ADD's session-handling description)."""

    def __init__(self) -> None:
        super().__init__("No active session was found.")


class SessionExpiredError(AuthenticationError):
    """Raised when an existing session's access token has expired and no
    valid refresh has occurred.
    """

    def __init__(self) -> None:
        super().__init__("The current session has expired.")


# ---------------------------------------------------------------------------
# Authorization branch — permission failures, identity already established
# ---------------------------------------------------------------------------


class AuthorizationError(AuthError):
    """Base class for every failure of an already-identified caller to be
    permitted a given action."""


class PermissionDeniedError(AuthorizationError):
    """Raised when an identified caller's role does not carry a required
    permission.

    Corresponds to API-ADD Section 11.3's ``PERMISSION_DENIED`` error
    code.

    Attributes:
        role: The caller's role, as a plain string (avoids a hard import
            dependency on ``app.models.enums.UserRole`` at the exception
            level).
        required_permission: The name of the permission that was
            required but not held.
    """

    def __init__(self, role: str, required_permission: str) -> None:
        super().__init__(
            f"Role '{role}' does not carry the required permission " f"'{required_permission}'."
        )
        self.role = role
        self.required_permission = required_permission


class RoleNotPermittedError(AuthorizationError):
    """Raised when an identified caller's role is not among a fixed set
    of roles explicitly permitted for a given action.

    Attributes:
        role: The caller's role.
        allowed_roles: The roles that would have been permitted.
    """

    def __init__(self, role: str, allowed_roles: tuple[str, ...]) -> None:
        super().__init__(f"Role '{role}' is not permitted; expected one of {allowed_roles}.")
        self.role = role
        self.allowed_roles = allowed_roles


class OwnershipRequiredError(AuthorizationError):
    """Raised when an action requires the caller to own, or be otherwise
    specifically associated with (e.g. an assigned approver), the target
    resource, and the caller is neither.

    Corresponds to API-ADD Section 11.2's rule that a resource outside
    the caller's visibility is reported as ``404 RESOURCE_NOT_FOUND``,
    not ``403``, to avoid confirming the resource's existence — callers
    of this package's RBAC functions are responsible for applying that
    translation; this exception itself only signals that the ownership
    check failed.
    """

    def __init__(self, resource: str) -> None:
        super().__init__(f"Caller is not the owner of, or associated with, this {resource}.")
        self.resource = resource


# ---------------------------------------------------------------------------
# Credential validation branch — neither authentication nor authorization
# ---------------------------------------------------------------------------


class CredentialValidationError(AuthError):
    """Raised when a raw credential value (e.g. a password) fails a
    shape-level validation rule prior to being forwarded to Supabase
    Auth.
    """
