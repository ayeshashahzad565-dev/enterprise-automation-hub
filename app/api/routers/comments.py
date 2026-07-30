"""Routes for the ``comments`` resource.

Thin wrappers over ``CommentService`` — see ``app.api.routers.requests``'s
module docstring for the general convention this file follows.

``add_comment`` additionally classifies a generic ``ValidationError``
raised for an invalid ``parent_comment_id`` into the more specific
``PARENT_COMMENT_NOT_FOUND`` error code, since ``CommentService`` has no
dedicated exception type for that case (see the Phase 2 migration plan's
"Known backend gaps" section, item 7) — a message-substring check against
``CommentService.add_comment``'s own current, stable raise message. If
that message ever changes, this degrades gracefully to the generic
``VALIDATION_ERROR`` code the global exception handler would have
produced anyway.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import get_comment_service, get_current_identity
from app.auth.authentication import AuthenticatedIdentity
from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database.repositories.base_repository import Page
from app.models.comment import CommentCreate
from app.services.comment_service import CommentService
from app.services.exceptions import ValidationError
from app.utils.pagination import build_pagination_metadata
from app.utils.response import (
    ErrorCode,
    build_error_response,
    build_list_response,
    build_success_response,
)
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["comments"])

_PARENT_NOT_FOUND_MESSAGE_MARKER = "parent_comment_id does not reference"


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/requests/{request_id}/comments")
def list_comments(
    request: Request,
    request_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: CommentService = Depends(get_comment_service),
) -> dict[str, Any]:
    """List a request's comment thread, oldest first. See
    ``CommentService.list_comments``."""
    result = service.list_comments(identity, request_id, page=Page(number=page, size=page_size))
    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    return build_list_response(
        [serialize(c) for c in result.items],
        pagination=pagination,
        request_id=_request_id_of(request),
    )


@router.post("/requests/{request_id}/comments", status_code=201)
def add_comment(
    request: Request,
    request_id: UUID,
    body: CommentCreate,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: CommentService = Depends(get_comment_service),
) -> Response:
    """Add a comment, or reply to one. See ``CommentService.add_comment``."""
    try:
        comment = service.add_comment(
            identity, request_id, body=body.body, parent_comment_id=body.parent_comment_id
        )
    except ValidationError as exc:
        if _PARENT_NOT_FOUND_MESSAGE_MARKER in exc.message:
            error_body = build_error_response(
                ErrorCode.PARENT_COMMENT_NOT_FOUND, exc.message, request_id=_request_id_of(request)
            )
            return JSONResponse(content=error_body, status_code=422)
        raise
    return JSONResponse(
        content=build_success_response(serialize(comment), request_id=_request_id_of(request)),
        status_code=201,
    )


@router.delete("/comments/{comment_id}", status_code=204)
def remove_comment(
    comment_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: CommentService = Depends(get_comment_service),
) -> Response:
    """Administrative removal (soft delete). See ``CommentService.remove_comment``."""
    service.remove_comment(identity, comment_id)
    return Response(status_code=204)
