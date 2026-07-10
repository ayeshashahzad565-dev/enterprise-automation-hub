"""Role-based access control engine.

Per API-ADD Section 6 and DSD Section 9's Row-Level Security policy
table, this module is the Application-Layer half of EAH's defense-in-depth
authorization model — the same authorization decision RLS independently
enforces at the database level (per DSD Section 9.3's service-role/
anon-key distinction), expressed here as plain, pure functions over a
``UserRole`` and, where the rule is ownership-dependent, a small set of
boolean facts about the caller's relationship to the target resource
(e.g. "is this caller the request's own submitter?").

This module never queries a database or a repository to determine those
boolean facts itself — per this package's "no database access,
no repository logic" constraint, the caller (a future service layer) is
responsible for having already determined, e.g., "is_requester" or
"is_assigned_approver" from data it already holds, and passes that fact
in as a plain argument. This keeps every function here a pure,
trivially-unit-testable predicate.
"""

from __future__ import annotations

import logging

from app.auth.exceptions import PermissionDeniedError, RoleNotPermittedError
from app.auth.permissions import Permission, ROLE_PERMISSIONS
from app.models.enums import UserRole

__all__ = [
    "has_permission",
    "require_permission",
    "require_role",
    "can_view_request",
    "can_edit_request",
    "can_withdraw_request",
    "can_decide_stage",
    "can_moderate_comment",
    "can_remove_attachment",
    "can_manage_workflow_definitions",
    "can_view_audit_trail",
    "can_manage_user_roles",
]

logger = logging.getLogger(__name__)


def has_permission(role: UserRole, permission: Permission) -> bool:
    """Return whether a role unconditionally carries a given permission.

    Args:
        role: The role to check.
        permission: The permission to check for.

    Returns:
        ``True`` if ``permission`` is in ``role``'s permission set, per
        ``app.auth.permissions.ROLE_PERMISSIONS``.
    """
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def require_permission(role: UserRole, permission: Permission) -> None:
    """Enforce that a role carries a given permission, raising if not.

    Args:
        role: The role to check.
        permission: The permission required.

    Raises:
        PermissionDeniedError: If ``role`` does not carry ``permission``.
    """
    if not has_permission(role, permission):
        logger.warning(
            "Permission denied: role=%s permission=%s",
            role.value,
            permission.value,
            extra={"role": role.value, "permission": permission.value},
        )
        raise PermissionDeniedError(role.value, permission.value)


def require_role(role: UserRole, *allowed_roles: UserRole) -> None:
    """Enforce that a role is among a fixed set of explicitly permitted roles.

    Used for the small number of rules that are role-gated outright
    rather than expressed as a named permission (for example, an
    endpoint documented as "admin only" with no finer-grained permission
    distinction needed).

    Args:
        role: The role to check.
        *allowed_roles: The roles permitted for this action.

    Raises:
        RoleNotPermittedError: If ``role`` is not in ``allowed_roles``.
    """
    if role not in allowed_roles:
        logger.warning(
            "Role not permitted: role=%s allowed=%s",
            role.value,
            [r.value for r in allowed_roles],
            extra={"role": role.value},
        )
        raise RoleNotPermittedError(role.value, tuple(r.value for r in allowed_roles))


def can_view_request(
    role: UserRole, *, is_requester: bool, is_assigned_approver: bool
) -> bool:
    """Return whether a caller may view a specific request.

    Matches DSD Section 9.2's RLS policy table: the requester, an
    approver assigned to one of the request's stages, or an
    administrator may view it (API-ADD Section 19.3.3).

    Args:
        role: The caller's role.
        is_requester: Whether the caller submitted this request.
        is_assigned_approver: Whether the caller is assigned to a stage
            on this request.

    Returns:
        ``True`` if the caller may view this request.
    """
    if role is UserRole.ADMIN:
        return True
    return is_requester or is_assigned_approver


def can_edit_request(role: UserRole, *, is_requester: bool, request_is_pending: bool) -> bool:
    """Return whether a caller may edit a request's editable fields.

    Matches API-ADD Section 19.3.4: "Requester only, and only while
    status = pending." Notably, this is **not** granted to
    administrators — API-ADD Section 6.2 is explicit that even
    administrators are not given a shortcut to directly mutate request
    state outside the documented endpoints, so ``role`` is accepted for
    signature symmetry with the other functions in this module but does
    not itself grant this permission; only ``is_requester`` does.

    Args:
        role: The caller's role (unused in the decision, retained for
            API consistency and potential future logging).
        is_requester: Whether the caller submitted this request.
        request_is_pending: Whether the request's status is still
            ``pending``.

    Returns:
        ``True`` if the caller may edit this request.
    """
    del role  # Deliberately not part of this decision; see docstring.
    return is_requester and request_is_pending


def can_withdraw_request(
    role: UserRole, *, is_requester: bool, request_is_pending: bool
) -> bool:
    """Return whether a caller may withdraw (soft-delete) a request.

    Matches API-ADD Section 19.3.5: "Requester, only while status =
    pending; or admin, at any status."

    Args:
        role: The caller's role.
        is_requester: Whether the caller submitted this request.
        request_is_pending: Whether the request's status is still
            ``pending``.

    Returns:
        ``True`` if the caller may withdraw this request.
    """
    if role is UserRole.ADMIN:
        return True
    return is_requester and request_is_pending


def can_decide_stage(
    role: UserRole,
    *,
    is_resolved_assignee: bool,
    is_role_eligible: bool,
    stage_is_pending: bool,
) -> bool:
    """Return whether a caller may approve or reject a workflow stage.

    Matches API-ADD Section 19.5.1: "approver/admin, resolved assignee or
    role-eligible, only while status = pending."

    Args:
        role: The caller's role.
        is_resolved_assignee: Whether the caller is the stage's specific
            ``assigned_to`` user.
        is_role_eligible: Whether the caller's role matches the stage's
            ``assigned_role`` (used for ``department_queue``-style
            stages with no specific assignee, per WEDD Section 7.3).
        stage_is_pending: Whether the stage's status is still ``pending``.

    Returns:
        ``True`` if the caller may decide this stage.
    """
    if role not in (UserRole.APPROVER, UserRole.ADMIN):
        return False
    if not stage_is_pending:
        return False
    return is_resolved_assignee or is_role_eligible


def can_moderate_comment(role: UserRole) -> bool:
    """Return whether a caller may administratively remove a comment.

    Matches API-ADD Section 19.6.3: "admin only."

    Args:
        role: The caller's role.

    Returns:
        ``True`` if ``role`` is ``UserRole.ADMIN``.
    """
    return role is UserRole.ADMIN


def can_remove_attachment(
    role: UserRole, *, is_uploader: bool, request_is_pending: bool
) -> bool:
    """Return whether a caller may remove an attachment.

    Matches API-ADD Section 19.7.4: "The original uploader (while the
    request is still pending), or admin."

    Args:
        role: The caller's role.
        is_uploader: Whether the caller uploaded this attachment.
        request_is_pending: Whether the parent request's status is still
            ``pending``.

    Returns:
        ``True`` if the caller may remove this attachment.
    """
    if role is UserRole.ADMIN:
        return True
    return is_uploader and request_is_pending


def can_manage_workflow_definitions(role: UserRole) -> bool:
    """Return whether a caller may create, edit, or activate workflow
    definitions.

    Matches API-ADD Section 19.9: "admin only" for every mutating
    workflow-definition endpoint.

    Args:
        role: The caller's role.

    Returns:
        ``True`` if ``role`` is ``UserRole.ADMIN``.
    """
    return role is UserRole.ADMIN


def can_view_audit_trail(
    role: UserRole, *, is_requester: bool, is_assigned_approver: bool
) -> bool:
    """Return whether a caller may view a request's audit trail.

    Matches API-ADD Section 19.10.1: "Same visibility as the parent
    request" — reusing the identical rule as ``can_view_request``.

    Args:
        role: The caller's role.
        is_requester: Whether the caller submitted the related request.
        is_assigned_approver: Whether the caller is assigned to a stage
            on the related request.

    Returns:
        ``True`` if the caller may view this audit trail.
    """
    return can_view_request(
        role, is_requester=is_requester, is_assigned_approver=is_assigned_approver
    )


def can_manage_user_roles(role: UserRole) -> bool:
    """Return whether a caller may change another user's role or
    department.

    Matches API-ADD Section 19.2.2: "Only admin may update role or
    department for any profile."

    Args:
        role: The caller's role.

    Returns:
        ``True`` if ``role`` is ``UserRole.ADMIN``.
    """
    return role is UserRole.ADMIN