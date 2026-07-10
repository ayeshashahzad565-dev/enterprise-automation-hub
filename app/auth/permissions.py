"""The fixed catalog of application permissions and their role mapping.

Per API-ADD Section 6 (Authorization) and Section 6.2 (Permissions by
Role), this module defines every discrete permission the system
recognizes and the mapping from each of the three fixed roles
(``UserRole.EMPLOYEE``, ``UserRole.APPROVER``, ``UserRole.ADMIN``) to the
set of permissions that role carries unconditionally.

Permissions that additionally depend on resource ownership or assignment
(for example, "an employee may edit *their own* pending request") are
*not* fully expressible as a static role-to-permission mapping alone —
those ownership-aware rules are implemented as functions in
``app.auth.rbac``, which consults this module's role-level mapping as
its foundation and adds the ownership dimension on top.
"""

from __future__ import annotations

from enum import Enum, auto

from app.models.enums import UserRole

__all__ = ["Permission", "ROLE_PERMISSIONS"]


class Permission(str, Enum):
    """The fixed catalog of discrete permissions recognized by the system.

    Every permission corresponds to a specific capability described in
    API-ADD Section 6.2's per-role permission narrative.
    """

    # Requests
    CREATE_REQUEST = "create_request"
    VIEW_OWN_REQUEST = "view_own_request"
    VIEW_ASSIGNED_REQUEST = "view_assigned_request"
    VIEW_ALL_REQUESTS = "view_all_requests"
    EDIT_OWN_REQUEST = "edit_own_request"
    WITHDRAW_OWN_REQUEST = "withdraw_own_request"
    WITHDRAW_ANY_REQUEST = "withdraw_any_request"
    SEARCH_REQUESTS = "search_requests"

    # Approvals
    DECIDE_ASSIGNED_STAGE = "decide_assigned_stage"
    VIEW_PENDING_APPROVALS = "view_pending_approvals"

    # Comments
    COMMENT_ON_REQUEST = "comment_on_request"
    MODERATE_COMMENT = "moderate_comment"

    # Attachments
    UPLOAD_ATTACHMENT = "upload_attachment"
    REMOVE_OWN_ATTACHMENT = "remove_own_attachment"
    REMOVE_ANY_ATTACHMENT = "remove_any_attachment"

    # Notifications
    VIEW_NOTIFICATIONS = "view_notifications"
    VIEW_ALL_NOTIFICATIONS = "view_all_notifications"

    # Workflow definitions
    MANAGE_WORKFLOW_DEFINITIONS = "manage_workflow_definitions"
    VIEW_ACTIVE_WORKFLOW_DEFINITIONS = "view_active_workflow_definitions"

    # Audit
    VIEW_AUDIT_TRAIL_SCOPED = "view_audit_trail_scoped"
    VIEW_AUDIT_TRAIL_ALL = "view_audit_trail_all"

    # Administration
    MANAGE_USER_ROLES = "manage_user_roles"
    UPDATE_OWN_PROFILE = "update_own_profile"


#: The permissions available to an ``employee`` (submitter), matching
#: API-ADD Section 6.2's "Employee (Submitter)" description exactly.
_EMPLOYEE_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.CREATE_REQUEST,
        Permission.VIEW_OWN_REQUEST,
        Permission.EDIT_OWN_REQUEST,
        Permission.WITHDRAW_OWN_REQUEST,
        Permission.SEARCH_REQUESTS,
        Permission.COMMENT_ON_REQUEST,
        Permission.UPLOAD_ATTACHMENT,
        Permission.REMOVE_OWN_ATTACHMENT,
        Permission.VIEW_NOTIFICATIONS,
        Permission.VIEW_ACTIVE_WORKFLOW_DEFINITIONS,
        Permission.VIEW_AUDIT_TRAIL_SCOPED,
        Permission.UPDATE_OWN_PROFILE,
    }
)

#: The permissions available to an ``approver``: every Employee
#: permission, plus the additional capabilities API-ADD Section 6.2
#: describes for that role.
_APPROVER_PERMISSIONS: frozenset[Permission] = _EMPLOYEE_PERMISSIONS | frozenset(
    {
        Permission.VIEW_ASSIGNED_REQUEST,
        Permission.DECIDE_ASSIGNED_STAGE,
        Permission.VIEW_PENDING_APPROVALS,
    }
)

#: The permissions available to an ``admin``: every Approver permission,
#: plus the additional, organization-wide capabilities API-ADD Section
#: 6.2 describes for that role. Notably, this set does **not** include
#: ``EDIT_OWN_REQUEST``-style direct mutation of ``requests.status`` or
#: ``workflow_stages.status`` outside the Approval/Workflow endpoints —
#: API-ADD Section 6.2 is explicit that even administrators are "not
#: granted a shortcut to directly mutate" those fields.
_ADMIN_PERMISSIONS: frozenset[Permission] = _APPROVER_PERMISSIONS | frozenset(
    {
        Permission.VIEW_ALL_REQUESTS,
        Permission.WITHDRAW_ANY_REQUEST,
        Permission.MODERATE_COMMENT,
        Permission.REMOVE_ANY_ATTACHMENT,
        Permission.VIEW_ALL_NOTIFICATIONS,
        Permission.MANAGE_WORKFLOW_DEFINITIONS,
        Permission.VIEW_AUDIT_TRAIL_ALL,
        Permission.MANAGE_USER_ROLES,
    }
)

#: The authoritative mapping from role to its unconditional permission
#: set, matching API-ADD Section 6.2 exactly. This mapping is intentionally
#: immutable (``frozenset`` values) so it cannot be mutated at runtime by
#: any caller.
ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.EMPLOYEE: _EMPLOYEE_PERMISSIONS,
    UserRole.APPROVER: _APPROVER_PERMISSIONS,
    UserRole.ADMIN: _ADMIN_PERMISSIONS,
}