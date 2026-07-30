"""Routes for the public, unauthenticated invitation surface (Milestone 6).

Both handlers are thin wrappers over ``InvitationService``'s existing,
already-implemented ``validate_invitation_token``/``accept_invitation``
methods (Milestone 3) — no business logic is duplicated here. Neither
route takes an ``AuthenticatedIdentity`` dependency: the invitee holds no
Supabase session at this point, exactly as
``InvitationService.validate_invitation_token``/``accept_invitation``'s
own docstrings describe.

**Security: identical responses for every invalid-token case.** Per this
milestone's Security requirements, a caller must not be able to
distinguish "token not found" from "expired" from "revoked" from
"already accepted" from "malformed token" — any of those would let an
unauthenticated caller enumerate invitation state. Both handlers below
therefore catch exactly the two ``InvitationService`` exceptions that
correspond to "this token is not currently acceptable"
(``NotFoundError``, ``InvalidInvitationStateError``) and return one
fixed, generic response for all of them — deliberately *not* re-raising
so that the centralized ``app.api.exception_handlers`` mapping (which
gives ``NotFoundError`` a 404 with a resource-specific message and
``InvalidInvitationStateError`` a 422 with the actual current-state
detail, exactly right for the *admin* endpoints) never runs for these
two exceptions on this router.

Every other exception ``InvitationService`` can raise from these two
methods (``ConcurrencyError`` from an optimistic-locking race,
``SupabaseAdminOperationError`` from a Supabase Admin API failure, or any
other translated ``DatabaseError``) is deliberately left to propagate
unmodified to the standard, centralized exception handlers — per this
milestone's instruction to intercept only the invitation-state exceptions
the security requirement needs, not every possible failure. A genuine
infrastructure failure still gets its normal status code (409, 500, ...);
it just never has any invitation-specific detail to leak in the first
place.

**Rate limiting (Milestone 9).** Both routes carry
``dependencies=[Depends(enforce_invitation_rate_limit)]`` — a
per-caller-IP check (``app.api.rate_limiting``), the first rate limit
actually enforced anywhere in this codebase. Attached at the route level,
not as global middleware, so no other endpoint (admin or authenticated)
is ever affected by it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import get_invitation_service
from app.api.rate_limiting import enforce_invitation_rate_limit
from app.api.schemas.public_invitations import (
    InvitationAcceptBody,
    InvitationAcceptOut,
    InvitationValidateOut,
)
from app.services.exceptions import InvalidInvitationStateError, NotFoundError
from app.services.invitation_service import InvitationService
from app.utils.response import ErrorCode, build_error_response, build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(
    prefix="/invitations",
    tags=["public-invitations"],
    dependencies=[Depends(enforce_invitation_rate_limit)],
)

#: The single, fixed message returned for every invalid-token case. Never
#: varies by reason (not found / expired / revoked / accepted /
#: malformed) — see this module's docstring.
_GENERIC_INVALID_INVITATION_MESSAGE = "This invitation link is invalid or has expired."


def _generic_invalid_invitation_response(request: Request) -> JSONResponse:
    """Build the one fixed response used for every invalid-token case.

    Args:
        request: The current request, used only to read the correlation
            id ``RequestIDMiddleware`` already attached to
            ``request.state``.

    Returns:
        A ``404`` ``JSONResponse`` with a fixed ``RESOURCE_NOT_FOUND``
        body — identical in status, code, and message regardless of why
        the token is unacceptable.
    """
    request_id = getattr(request.state, "request_id", None)
    body = build_error_response(
        ErrorCode.RESOURCE_NOT_FOUND, _GENERIC_INVALID_INVITATION_MESSAGE, request_id=request_id
    )
    return JSONResponse(content=body, status_code=404)


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/validate")
def validate_invitation(
    request: Request,
    token: str = Query(..., min_length=1, max_length=512),
    service: InvitationService = Depends(get_invitation_service),
) -> Any:
    """Validate whether an invitation token may be accepted. Public,
    unauthenticated. See ``InvitationService.validate_invitation_token``.
    """
    try:
        invitation = service.validate_invitation_token(token)
    except (NotFoundError, InvalidInvitationStateError):
        return _generic_invalid_invitation_response(request)

    out = InvitationValidateOut(
        email=invitation.email,
        full_name=invitation.full_name,
        role=invitation.role,
        department=invitation.department,
        expires_at=invitation.expires_at,
    )
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.post("/accept")
def accept_invitation(
    request: Request,
    body: InvitationAcceptBody,
    service: InvitationService = Depends(get_invitation_service),
) -> Any:
    """Accept an invitation: create the invitee's Supabase Auth user and
    mark the invitation accepted. Public, unauthenticated. See
    ``InvitationService.accept_invitation``.
    """
    try:
        accepted = service.accept_invitation(body.token, password=body.password)
    except (NotFoundError, InvalidInvitationStateError):
        return _generic_invalid_invitation_response(request)

    out = InvitationAcceptOut(email=accepted.email, full_name=accepted.full_name)
    return build_success_response(serialize(out), request_id=_request_id_of(request))
