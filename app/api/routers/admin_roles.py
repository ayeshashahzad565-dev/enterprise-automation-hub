"""Routes for the admin Roles & Permissions module: a read-only
rendering of the fixed role-to-permission matrix already defined in
``app.auth.permissions``.

No mutation endpoint exists here — RBAC capabilities are fixed in code
(``ROLE_PERMISSIONS``), not configurable data, so there is nothing to
write. This route reflects exactly what the backend already enforces; it
invents no permission that ``app.auth.rbac``/``app.auth.permissions``
does not already define.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_current_identity
from app.auth import rbac
from app.auth.authentication import AuthenticatedIdentity
from app.auth.permissions import ROLE_PERMISSIONS
from app.models.enums import UserRole
from app.utils.response import build_success_response

__all__ = ["router"]

router = APIRouter(tags=["admin-roles"])


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/admin/roles")
def list_role_permissions(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
) -> dict[str, Any]:
    """The fixed role -> permission matrix. Admin only. See
    ``app.auth.permissions.ROLE_PERMISSIONS``.
    """
    rbac.require_role(identity.role, UserRole.ADMIN)
    data = [
        {"role": role.value, "permissions": sorted(permission.value for permission in permissions)}
        for role, permissions in ROLE_PERMISSIONS.items()
    ]
    return build_success_response(data, request_id=_request_id_of(request))
