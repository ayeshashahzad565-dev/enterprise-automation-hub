"""Identity-aware authorization enforcement.

This module bridges ``app.auth.authentication.AuthenticatedIdentity``
(the outcome of authentication) with ``app.auth.rbac``'s pure, role-based
and ownership-aware predicate functions (the outcome of authorization
logic), so that enforcement code — decorators, middleware, and any future
service-layer caller — operates on a single, already-authenticated
identity object rather than manually unpacking ``identity.role`` at every
call site and re-implementing the "has this identity's token already
expired" check that must precede every authorization decision.

Per this package's core design constraint that authorization remains
completely separate from authentication, this module still performs no
authentication of its own: every function here assumes ``identity`` has
already been produced by ``AuthenticatedIdentity.from_claims`` (or
equivalent verified construction) and only adds the one authorization-
adjacent check that legitimately depends on the identity object itself —
expiry — before delegating the actual permission decision to
``app.auth.rbac``, which knows nothing about ``AuthenticatedIdentity`` and
operates on a bare ``UserRole`` instead. That layering is deliberate:
``rbac.py`` remains testable with nothing but a ``UserRole`` value, and
this module is the only place in the package that needs both concepts at
once.

Every enforcement function here follows one shape: consult the
corresponding ``rbac`` predicate, and raise a precise, typed exception
(``PermissionDeniedError``, ``RoleNotPermittedError``, or
``OwnershipRequiredError``) if it returns ``False``. None of these
functions perform persistence access; the ownership-related boolean
facts they consult (``is_requester``, ``is_assigned_approver``, etc.)
must already have been determined by the caller from data it holds, per
this package's "no database access" constraint.
"""

from __future__ import annotations

import logging

from app.auth import rbac
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import OwnershipRequiredError, SessionExpiredError
from app.auth.permissions import Permission
from app.models.enums import UserRole

__all__ = [
    "authorize_permission",
    "authorize_role",
    "authorize_request_view",
    "authorize_request_edit",
    "authorize_request_withdrawal",
    "authorize_stage_decision",
    "authorize_comment_moderation",
    "authorize_attachment_removal",
    "authorize_workflow_definition_management",
    "authorize_audit_trail_view",
    "authorize_user_role_management",
    "authorize_platform_admin",
]

logger = logging.getLogger(__name__)


def _ensure_not_expired(identity: AuthenticatedIdentity) -> None:
    """Raise if an identity's token has already expired.

    Every function in this module calls this first, since an expired
    identity has no valid authorization decision to make on its behalf —
    per API-ADD Section 5.3, an expired token never reaches an
    Application Service method, and this module holds that same line at
    the authorization boundary.

    Args:
        identity: The identity to check.

    Raises:
        SessionExpiredError: If ``identity.is_expired`` is ``True``.
    """
    if identity.is_expired:
        raise SessionExpiredError()


def authorize_permission(identity: AuthenticatedIdentity, permission: Permission) -> None:
    """Enforce that an identity's role carries a given permission.

    Args:
        identity: The already-authenticated caller.
        permission: The permission required.

    Raises:
        SessionExpiredError: If ``identity``'s token has expired.
        PermissionDeniedError: If ``identity.role`` does not carry
            ``permission``.
    """
    _ensure_not_expired(identity)
    rbac.require_permission(identity.role, permission)


def authorize_role(identity: AuthenticatedIdentity, *allowed_roles: UserRole) -> None:
    """Enforce that an identity's role is among a fixed set of permitted roles.

    Args:
        identity: The already-authenticated caller.
        *allowed_roles: The roles permitted for this action.

    Raises:
        SessionExpiredError: If ``identity``'s token has expired.
        RoleNotPermittedError: If ``identity.role`` is not in
            ``allowed_roles``.
    """
    _ensure_not_expired(identity)
    rbac.require_role(identity.role, *allowed_roles)


def authorize_request_view(
    identity: AuthenticatedIdentity,
    *,
    is_requester: bool,
    is_assigned_approver: bool,
) -> None:
    """Enforce that an identity may view a specific request.

    Args:
        identity: The already-authenticated caller.
        is_requester: Whether the caller submitted this request.
        is_assigned_approver: Whether the caller is assigned to a stage
            on this request.

    Raises:
        SessionExpiredError: If ``identity``'s token has expired.
        OwnershipRequiredError: If the caller is neither the requester,
            an assigned approver, nor an administrator (API-ADD Section
            11.2 — callers translating this into an HTTP-shaped error
            should map it to ``404 RESOURCE_NOT_FOUND``, not ``403``, to
            avoid confirming the resource's existence to an unauthorized
            caller).
    """
    _ensure_not_expired(identity)
    if not rbac.can_view_request(
        identity.role, is_requester=is_requester, is_assigned_approver=is_assigned_approver
    ):
        raise OwnershipRequiredError("request")


def authorize_request_edit(
    identity: AuthenticatedIdentity, *, is_requester: bool, request_is_pending: bool
) -> None:
    """Enforce that an identity may edit a request's editable fields.

    Args:
        identity: The already-authenticated caller.
        is_requester: Whether the caller submitted this request.
        request_is_pending: Whether the request's status is still
            ``pending``.

    Raises:
        SessionExpiredError: If ``identity``'s token has expired.
        OwnershipRequiredError: If the caller is not the requester, or
            the request is no longer ``pending`` (API-ADD Section
            19.3.4 — not even an administrator is granted this shortcut,
            per ``rbac.can_edit_request``'s own documented rationale).
    """
    _ensure_not_expired(identity)
    if not rbac.can_edit_request(
        identity.role, is_requester=is_requester, request_is_pending=request_is_pending
    ):
        raise OwnershipRequiredError("request")


def authorize_request_withdrawal(
    identity: AuthenticatedIdentity, *, is_requester: bool, request_is_pending: bool
) -> None:
    """Enforce that an identity may withdraw (soft-delete) a request.

    Args:
        identity: The already-authenticated caller.
        is_requester: Whether the caller submitted this request.
        request_is_pending: Whether the request's status is still
            ``pending``.

    Raises:
        SessionExpiredError: If ``identity``'s token has expired.
        OwnershipRequiredError: If the caller is not the requester (while
            pending) and not an administrator (API-ADD Section 19.3.5).
    """
    _ensure_not_expired(identity)
    if not rbac.can_withdraw_request(
        identity.role, is_requester=is_requester, request_is_pending=request_is_pending
    ):
        raise OwnershipRequiredError("request")


def authorize_stage_decision(
    identity: AuthenticatedIdentity,
    *,
    is_resolved_assignee: bool,
    is_role_eligible: bool,
    stage_is_pending: bool,
) -> None:
    """Enforce that an identity may approve or reject a workflow stage.

    Args:
        identity: The already-authenticated caller.
        is_resolved_assignee: Whether the caller is the stage's specific
            ``assigned_to`` user.
        is_role_eligible: Whether the caller's role matches the stage's
            ``assigned_role`` (WEDD Section 7.3).
        stage_is_pending: Whether the stage's status is still ``pending``.

    Raises:
        SessionExpiredError: If ``identity``'s token has expired.
        OwnershipRequiredError: If the caller is not permitted to decide
            this stage (API-ADD Section 19.5.1).
    """
    _ensure_not_expired(identity)
    if not rbac.can_decide_stage(
        identity.role,
        is_resolved_assignee=is_resolved_assignee,
        is_role_eligible=is_role_eligible,
        stage_is_pending=stage_is_pending,
    ):
        raise OwnershipRequiredError("workflow stage")


def authorize_comment_moderation(identity: AuthenticatedIdentity) -> None:
    """Enforce that an identity may administratively remove a comment.

    Args:
        identity: The already-authenticated caller.

    Raises:
        SessionExpiredError: If ``identity``'s token has expired.
        PermissionDeniedError: If the caller is not an administrator
            (API-ADD Section 19.6.3).
    """
    _ensure_not_expired(identity)
    if not rbac.can_moderate_comment(identity.role):
        raise rbac_permission_denied(identity.role, "moderate_comment")


def authorize_attachment_removal(
    identity: AuthenticatedIdentity, *, is_uploader: bool, request_is_pending: bool
) -> None:
    """Enforce that an identity may remove an attachment.

    Args:
        identity: The already-authenticated caller.
        is_uploader: Whether the caller uploaded this attachment.
        request_is_pending: Whether the parent request's status is still
            ``pending``.

    Raises:
        SessionExpiredError: If ``identity``'s token has expired.
        OwnershipRequiredError: If the caller is neither the uploader
            (while the request is pending) nor an administrator (API-ADD
            Section 19.7.4).
    """
    _ensure_not_expired(identity)
    if not rbac.can_remove_attachment(
        identity.role, is_uploader=is_uploader, request_is_pending=request_is_pending
    ):
        raise OwnershipRequiredError("attachment")


def authorize_workflow_definition_management(identity: AuthenticatedIdentity) -> None:
    """Enforce that an identity may create, edit, or activate workflow definitions.

    Args:
        identity: The already-authenticated caller.

    Raises:
        SessionExpiredError: If ``identity``'s token has expired.
        PermissionDeniedError: If the caller is not an administrator
            (API-ADD Section 19.9).
    """
    _ensure_not_expired(identity)
    if not rbac.can_manage_workflow_definitions(identity.role):
        raise rbac_permission_denied(identity.role, "manage_workflow_definitions")


def authorize_audit_trail_view(
    identity: AuthenticatedIdentity,
    *,
    is_requester: bool,
    is_assigned_approver: bool,
) -> None:
    """Enforce that an identity may view a request's audit trail.

    Args:
        identity: The already-authenticated caller.
        is_requester: Whether the caller submitted the related request.
        is_assigned_approver: Whether the caller is assigned to a stage
            on the related request.

    Raises:
        SessionExpiredError: If ``identity``'s token has expired.
        OwnershipRequiredError: If the caller may not view this audit
            trail (API-ADD Section 19.10.1).
    """
    _ensure_not_expired(identity)
    if not rbac.can_view_audit_trail(
        identity.role, is_requester=is_requester, is_assigned_approver=is_assigned_approver
    ):
        raise OwnershipRequiredError("audit trail")


def authorize_user_role_management(identity: AuthenticatedIdentity) -> None:
    """Enforce that an identity may change another user's role or department.

    Args:
        identity: The already-authenticated caller.

    Raises:
        SessionExpiredError: If ``identity``'s token has expired.
        PermissionDeniedError: If the caller is not an administrator
            (API-ADD Section 19.2.2).
    """
    _ensure_not_expired(identity)
    if not rbac.can_manage_user_roles(identity.role):
        raise rbac_permission_denied(identity.role, "manage_user_roles")


def authorize_platform_admin(identity: AuthenticatedIdentity) -> None:
    """Enforce that an identity may perform a platform-only operation.

    Deliberately orthogonal to the ``UserRole``/``rbac`` system this
    module otherwise delegates to entirely: platform administration
    (creating/listing/deactivating a company; inviting a company's first
    user before it has any admin of its own) is a capability above
    company-scoped ``UserRole.ADMIN``, not a superset of it — a platform
    admin's own company-scoped business permissions are unaffected by
    this check, and this check grants nothing beyond the handful of
    platform-only endpoints that call it.

    Args:
        identity: The already-authenticated caller.

    Raises:
        SessionExpiredError: If ``identity``'s token has expired.
        PermissionDeniedError: If ``identity.is_platform_admin`` is
            ``False``.
    """
    _ensure_not_expired(identity)
    if not identity.is_platform_admin:
        raise rbac_permission_denied(identity.role, "platform_admin")


def rbac_permission_denied(role: UserRole, permission_name: str):
    """Construct a ``PermissionDeniedError`` for a role-only rbac predicate.

    Small internal helper so the three role-only enforcement functions
    above (comment moderation, workflow-definition management, user-role
    management — each backed by a plain ``UserRole``-returning predicate
    in ``rbac.py`` rather than a named ``Permission``) still raise the
    same ``PermissionDeniedError`` shape as ``authorize_permission``,
    rather than introducing a second exception shape for what is,
    conceptually, the same kind of failure.

    Args:
        role: The caller's role.
        permission_name: A short, human-readable name for the capability
            that was required, used only in the exception's message.

    Returns:
        A constructed, not-yet-raised ``PermissionDeniedError``.
    """
    from app.auth.exceptions import PermissionDeniedError

    return PermissionDeniedError(role.value, permission_name)
