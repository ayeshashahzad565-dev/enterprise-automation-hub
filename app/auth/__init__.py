"""Authentication and Authorization Layer for the Enterprise Automation Hub.

Per the Architecture Design Document and API Design Document, this
package provides:

- **Authentication** (``authentication``): identity establishment from
  already-verified claims — deliberately independent of any database or
  network access, since actual credential verification against Supabase
  Auth belongs to a future service-layer package. JWT validation over
  HTTP is stateless (API-ADD Section 5.5/5.6), so no server-side session
  store is used.
- **Authorization** (``permissions``, ``rbac``, ``authorization``): the
  fixed permission catalog (``permissions``), the pure, role-based and
  ownership-aware predicate functions realizing API-ADD Section 6's rules
  and DSD Section 9's Row-Level Security policies (``rbac``), and the
  identity-aware enforcement layer that bridges the two with
  ``AuthenticatedIdentity`` (``authorization``).
- **Composition** (``decorators``, ``middleware``): reusable,
  dependency-injectable enforcement mechanisms built on top of
  ``authorization``, kept as a thin composition layer rather than
  introducing any new authorization logic of its own.
- **Password handling** (``password``): a narrowly-scoped, standard-
  library-only hashing utility, explicitly not used for Supabase-managed
  user credentials in the current baseline (see that module's docstring
  for the full rationale).
- **Exceptions** (``exceptions``): a hierarchy that keeps authentication
  failures and authorization failures in entirely separate branches,
  per this package's core design constraint.

This package has no dependency on ``app.database`` and performs no
persistence or network access of any kind.
"""

from __future__ import annotations

from app.auth.authentication import (
    AuthenticatedIdentity,
    decode_jwt_payload_unverified,
    extract_bearer_token,
)
from app.auth.authorization import (
    authorize_attachment_removal,
    authorize_audit_trail_view,
    authorize_comment_moderation,
    authorize_permission,
    authorize_request_edit,
    authorize_request_view,
    authorize_request_withdrawal,
    authorize_role,
    authorize_stage_decision,
    authorize_user_role_management,
    authorize_workflow_definition_management,
)
from app.auth.decorators import (
    require_authentication,
    require_permission_decorator,
    require_role_decorator,
)
from app.auth.exceptions import (
    AuthenticationError,
    AuthError,
    AuthorizationError,
    CredentialValidationError,
    InvalidTokenError,
    MalformedAuthorizationHeaderError,
    MissingCredentialsError,
    OwnershipRequiredError,
    PermissionDeniedError,
    RoleNotPermittedError,
    SessionExpiredError,
    SessionNotFoundError,
    TokenExpiredError,
)
from app.auth.middleware import (
    AuthenticationMiddleware,
    AuthorizationMiddleware,
    Middleware,
    MiddlewarePipeline,
    RequestContext,
)
from app.auth.password import hash_password, validate_password_shape, verify_password
from app.auth.permissions import ROLE_PERMISSIONS, Permission
from app.auth.rbac import (
    can_decide_stage,
    can_edit_request,
    can_manage_user_roles,
    can_manage_workflow_definitions,
    can_moderate_comment,
    can_remove_attachment,
    can_view_audit_trail,
    can_view_request,
    can_withdraw_request,
    has_permission,
    require_permission,
    require_role,
)

__all__ = [
    # authentication
    "AuthenticatedIdentity",
    "decode_jwt_payload_unverified",
    "extract_bearer_token",
    # authorization
    "authorize_attachment_removal",
    "authorize_audit_trail_view",
    "authorize_comment_moderation",
    "authorize_permission",
    "authorize_request_edit",
    "authorize_request_view",
    "authorize_request_withdrawal",
    "authorize_role",
    "authorize_stage_decision",
    "authorize_user_role_management",
    "authorize_workflow_definition_management",
    # decorators
    "require_authentication",
    "require_permission_decorator",
    "require_role_decorator",
    # exceptions
    "AuthError",
    "AuthenticationError",
    "AuthorizationError",
    "CredentialValidationError",
    "InvalidTokenError",
    "MalformedAuthorizationHeaderError",
    "MissingCredentialsError",
    "OwnershipRequiredError",
    "PermissionDeniedError",
    "RoleNotPermittedError",
    "SessionExpiredError",
    "SessionNotFoundError",
    "TokenExpiredError",
    # middleware
    "AuthenticationMiddleware",
    "AuthorizationMiddleware",
    "Middleware",
    "MiddlewarePipeline",
    "RequestContext",
    # password
    "hash_password",
    "validate_password_shape",
    "verify_password",
    # permissions
    "Permission",
    "ROLE_PERMISSIONS",
    # rbac
    "can_decide_stage",
    "can_edit_request",
    "can_manage_user_roles",
    "can_manage_workflow_definitions",
    "can_moderate_comment",
    "can_remove_attachment",
    "can_view_audit_trail",
    "can_view_request",
    "can_withdraw_request",
    "has_permission",
    "require_permission",
    "require_role",
]
