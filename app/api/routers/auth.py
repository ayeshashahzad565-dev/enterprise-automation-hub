"""``GET /api/v1/auth/me``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_current_identity, get_resources
from app.auth.authentication import AuthenticatedIdentity
from app.bootstrap import ApplicationResources
from app.database.exceptions import DatabaseError
from app.services.exceptions import translate_database_error
from app.services.request_service import map_profile_record_to_domain
from app.utils.response import build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def get_current_user(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """Return the profile and role of the currently authenticated caller.

    Matches ``docs/api_design.md`` Section 19.1.3: authenticated (any
    role), returns the ``Profile`` schema (Section 10.1).

    ``AuthenticatedIdentity`` (built from the bearer token's claims) does
    not carry ``full_name``/``department`` — this reads
    ``ProfileRepository.get_by_id`` directly, since no dedicated "get my
    own profile" Application Service method exists anywhere in this
    codebase, mirroring the same direct-repository-read precedent
    ``app.py``'s ``SupabaseAuthGateway._build_auth_result`` already
    established for this exact narrow need. Any ``DatabaseError`` this
    read could raise is translated via the existing
    ``app.services.exceptions.translate_database_error``, exactly as
    every Application Service already does for a direct repository call,
    so it is handled by the same centralized ``EAHError`` exception
    handler as everything else.

    Args:
        request: The current request, used only to read the correlation
            id ``RequestIDMiddleware`` already attached.
        identity: The caller's already-verified identity.
        resources: The process-wide resource bundle.

    Returns:
        The standard success envelope wrapping the caller's ``Profile``.
    """
    try:
        record = resources.profile_repo.get_by_id(identity.user_id)
    except DatabaseError as exc:
        raise translate_database_error(exc) from exc

    profile = map_profile_record_to_domain(record)
    request_id = getattr(request.state, "request_id", None)
    return build_success_response(serialize(profile), request_id=request_id)
