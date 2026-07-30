"""Routes for the ``attachments`` resource.

Thin wrappers over ``AttachmentService`` — see
``app.api.routers.requests``'s module docstring for the general
convention this file follows.

``upload_attachment``/``replace_attachment`` additionally classify a
generic ``ValidationError`` into the more specific ``INVALID_FILE_TYPE``/
``FILE_TOO_LARGE``/``EMPTY_FILE`` error codes, since neither
``AttachmentService`` nor ``app.utils.file_utils`` raises a dedicated
exception subclass for each case today (see the Phase 2 migration plan's
"Known backend gaps" section, item 7) — a message-substring check against
``app.utils.file_utils``'s current, stable raise messages. If those
messages ever change, this degrades gracefully to the generic
``VALIDATION_ERROR`` code the global exception handler would have
produced anyway.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import get_attachment_service, get_current_identity
from app.api.rate_limiting import enforce_upload_rate_limit
from app.auth.authentication import AuthenticatedIdentity
from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.config.security import MAX_ATTACHMENT_SIZE_BYTES
from app.database.repositories.base_repository import Page
from app.services.attachment_service import AttachmentService
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

router = APIRouter(tags=["attachments"])

#: Read size for ``_read_upload_bounded``'s chunked upload read.
_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024


async def _read_upload_bounded(
    file: UploadFile, *, max_size_bytes: int = MAX_ATTACHMENT_SIZE_BYTES
) -> bytes:
    """Read an upload's content in bounded chunks, capping memory use.

    ``UploadFile.read()`` with no size argument buffers the entire body
    into memory before ``AttachmentService``'s own ``validate_file_size``
    ever runs — an unbounded or falsely-labeled upload can exhaust
    process memory first. Reading in fixed-size chunks and aborting the
    moment the running total exceeds ``max_size_bytes`` bounds memory use
    to roughly ``max_size_bytes`` regardless of how large the actual
    request body is, independent of (and without trusting) any
    client-supplied ``Content-Length``.

    Args:
        file: The incoming upload.
        max_size_bytes: The configured maximum attachment size. Defaults
            to ``app.config.security.MAX_ATTACHMENT_SIZE_BYTES``.

    Returns:
        The file's full content, guaranteed to be no larger than
        ``max_size_bytes``.

    Raises:
        ValidationError: If the upload's content exceeds
            ``max_size_bytes`` — the same message shape
            ``app.utils.file_utils.validate_file_size`` raises, so
            ``_classify_file_validation_message`` still classifies it as
            ``FILE_TOO_LARGE``.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size_bytes:
            raise ValidationError(f"File size exceeds the maximum of {max_size_bytes} bytes.")
        chunks.append(chunk)
    return b"".join(chunks)


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _classify_file_validation_message(message: str) -> ErrorCode:
    """Map a generic file-validation message to the specific error code it matches."""
    if (
        "is not permitted for attachments" in message
        or "does not match its declared type" in message
    ):
        return ErrorCode.INVALID_FILE_TYPE
    if "exceeds the maximum of" in message:
        return ErrorCode.FILE_TOO_LARGE
    if "must be positive" in message:
        return ErrorCode.EMPTY_FILE
    return ErrorCode.VALIDATION_ERROR


def _file_validation_response(request: Request, exc: ValidationError) -> JSONResponse:
    code = _classify_file_validation_message(exc.message)
    body = build_error_response(code, exc.message, request_id=_request_id_of(request))
    return JSONResponse(content=body, status_code=422)


@router.get("/requests/{request_id}/attachments")
def list_attachments(
    request: Request,
    request_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AttachmentService = Depends(get_attachment_service),
) -> dict[str, Any]:
    """List attachment metadata for a request. See
    ``AttachmentService.list_attachments``."""
    result = service.list_attachments(identity, request_id, page=Page(number=page, size=page_size))
    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    return build_list_response(
        [serialize(a) for a in result.items],
        pagination=pagination,
        request_id=_request_id_of(request),
    )


@router.post(
    "/requests/{request_id}/attachments",
    status_code=201,
    dependencies=[Depends(enforce_upload_rate_limit)],
)
async def upload_attachment(
    request: Request,
    request_id: UUID,
    file: UploadFile = File(...),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AttachmentService = Depends(get_attachment_service),
) -> Response:
    """Upload a file against a request. See ``AttachmentService.upload_attachment``."""
    try:
        content = await _read_upload_bounded(file)
    except ValidationError as exc:
        return _file_validation_response(request, exc)
    try:
        attachment = service.upload_attachment(
            identity,
            request_id,
            file_name=file.filename or "unnamed",
            content_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except ValidationError as exc:
        return _file_validation_response(request, exc)
    return JSONResponse(
        content=build_success_response(serialize(attachment), request_id=_request_id_of(request)),
        status_code=201,
    )


@router.put("/attachments/{attachment_id}", dependencies=[Depends(enforce_upload_rate_limit)])
async def replace_attachment(
    request: Request,
    attachment_id: UUID,
    file: UploadFile = File(...),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AttachmentService = Depends(get_attachment_service),
) -> Response:
    """Upload a new version of an attachment, superseding the old one.

    Not documented in ``docs/api_design.md`` Section 19.7, but a fully
    implemented, existing ``AttachmentService`` capability — exposed here
    for the Edit-Request "replace file" action. See
    ``AttachmentService.replace_attachment``.
    """
    try:
        content = await _read_upload_bounded(file)
    except ValidationError as exc:
        return _file_validation_response(request, exc)
    try:
        attachment = service.replace_attachment(
            identity,
            attachment_id,
            file_name=file.filename or "unnamed",
            content_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except ValidationError as exc:
        return _file_validation_response(request, exc)
    return JSONResponse(
        content=build_success_response(serialize(attachment), request_id=_request_id_of(request))
    )


@router.get("/attachments/{attachment_id}/download")
def get_download_url(
    request: Request,
    attachment_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AttachmentService = Depends(get_attachment_service),
) -> dict[str, Any]:
    """Retrieve a short-lived signed Storage URL. See
    ``AttachmentService.get_download_url``."""
    url = service.get_download_url(identity, attachment_id)
    return build_success_response({"url": url}, request_id=_request_id_of(request))


@router.delete("/attachments/{attachment_id}", status_code=204)
def remove_attachment(
    attachment_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AttachmentService = Depends(get_attachment_service),
) -> Response:
    """Remove an attachment (soft delete). See ``AttachmentService.remove_attachment``."""
    service.remove_attachment(identity, attachment_id)
    return Response(status_code=204)
