"""Routes for the ``admin-invitations`` resource: the Enterprise User
Onboarding admin-side invitation surface (Milestone 5).

Every handler is a thin wrapper over ``InvitationService``'s existing
methods (``create_invitation``, ``list_invitations``, ``get_invitation``,
``resend_invitation``, ``revoke_invitation``) — the service itself already
enforces admin-only authorization on every one of these methods
(``InvitationService._authorize_admin``), so, matching
``app.api.routers.workflow_definitions``'s identical rationale, no
authorization check is duplicated here; a non-admin caller's request
reaches the service and comes back as a translated
``PermissionDeniedError`` (403) exactly like every other admin-gated
service method in this codebase.

Only the five endpoints the approved architecture's Milestone 5 scope
lists are defined here: the public, unauthenticated ``validate``/``accept``
endpoints (``InvitationService.validate_invitation_token``/
``accept_invitation``) are explicitly out of this milestone's scope and
are not exposed by this router.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_current_identity, get_invitation_service
from app.api.schemas.admin_invitations import InvitationCreateBody, InvitationOut
from app.auth.authentication import AuthenticatedIdentity
from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database.repositories.base_repository import Page
from app.models.enums import EffectiveInvitationStatus
from app.services.invitation_service import InvitationService
from app.utils.pagination import build_pagination_metadata
from app.utils.response import build_list_response, build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["admin-invitations"])


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.post("/admin/invitations", status_code=201)
def create_invitation(
    request: Request,
    body: InvitationCreateBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: InvitationService = Depends(get_invitation_service),
) -> dict[str, Any]:
    """Create a new, pending invitation and (best-effort) email it. Admin
    only. See ``InvitationService.create_invitation``.
    """
    created = service.create_invitation(
        identity,
        email=body.email,
        full_name=body.full_name,
        role=body.role,
        department=body.department,
        company_id=body.company_id,
    )
    out = InvitationOut.model_validate(created)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/admin/invitations")
def list_invitations(
    request: Request,
    status: EffectiveInvitationStatus | None = Query(None),
    query: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: InvitationService = Depends(get_invitation_service),
) -> dict[str, Any]:
    """List invitations, optionally filtered by effective status and/or
    free-text search across email and full name. Admin only. See
    ``InvitationService.list_invitations``.
    """
    page_obj = Page(number=page, size=page_size)
    result = service.list_invitations(identity, status=status, query=query, page=page_obj)

    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    out = [serialize(InvitationOut.model_validate(item)) for item in result.items]
    return build_list_response(out, pagination=pagination, request_id=_request_id_of(request))


@router.get("/admin/invitations/{invitation_id}")
def get_invitation(
    request: Request,
    invitation_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: InvitationService = Depends(get_invitation_service),
) -> dict[str, Any]:
    """Fetch a single invitation by id. Admin only. See
    ``InvitationService.get_invitation``.
    """
    invitation = service.get_invitation(identity, invitation_id)
    out = InvitationOut.model_validate(invitation)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.post("/admin/invitations/{invitation_id}/resend")
def resend_invitation(
    request: Request,
    invitation_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: InvitationService = Depends(get_invitation_service),
) -> dict[str, Any]:
    """Resend a pending invitation: rotate its token, extend its expiry,
    and re-send its email. Admin only. See
    ``InvitationService.resend_invitation``.
    """
    resent = service.resend_invitation(identity, invitation_id)
    out = InvitationOut.model_validate(resent)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.post("/admin/invitations/{invitation_id}/revoke")
def revoke_invitation(
    request: Request,
    invitation_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: InvitationService = Depends(get_invitation_service),
) -> dict[str, Any]:
    """Revoke a pending invitation. Admin only. See
    ``InvitationService.revoke_invitation``.
    """
    revoked = service.revoke_invitation(identity, invitation_id)
    out = InvitationOut.model_validate(revoked)
    return build_success_response(serialize(out), request_id=_request_id_of(request))
