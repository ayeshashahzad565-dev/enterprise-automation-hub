"""Standardized API response construction.

Per API-ADD Sections 9 and 11, every response this system produces —
success or error, single-resource or list — follows one of a small,
fixed set of JSON shapes. This module provides the builder functions for
each shape, so that every layer of the codebase that needs to produce a
response-shaped payload does so identically, rather than each call site
constructing the ``data``/``pagination``/``meta``/``error`` envelope by
hand.

This module has no dependency on any specific web framework — the dicts
it returns are plain, JSON-serializable Python data, ready to be handed
to whatever serializes an HTTP response in a future package, consistent
with API-ADD Section 1.2's description of the REST specification as a
contract layer independent of its physical transport.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from app.utils.datetime_utils import format_iso8601, utc_now
from app.utils.id_generator import generate_request_correlation_id
from app.utils.pagination import PaginationMetadata

__all__ = [
    "ErrorCode",
    "build_meta",
    "build_success_response",
    "build_list_response",
    "build_error_response",
]


class ErrorCode(str, Enum):
    """The closed catalog of application error codes, matching API-ADD
    Section 11.3 exactly.

    No response-building code anywhere in the system should introduce an
    ``error.code`` value not represented here.
    """

    MALFORMED_REQUEST = "MALFORMED_REQUEST"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    CONCURRENT_UPDATE = "CONCURRENT_UPDATE"
    DUPLICATE_ACTIVATION = "DUPLICATE_ACTIVATION"
    STAGE_ALREADY_DECIDED = "STAGE_ALREADY_DECIDED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_REQUEST_TYPE = "INVALID_REQUEST_TYPE"
    INVALID_WORKFLOW_DEFINITION = "INVALID_WORKFLOW_DEFINITION"
    UNKNOWN_ASSIGNEE = "UNKNOWN_ASSIGNEE"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    EMPTY_FILE = "EMPTY_FILE"
    IMMUTABLE_FIELD = "IMMUTABLE_FIELD"
    PARENT_COMMENT_NOT_FOUND = "PARENT_COMMENT_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def build_meta(*, request_id: str | None = None) -> dict[str, str]:
    """Build the ``meta`` object included on every response, success or error.

    Matches API-ADD Section 9: "Every response — success or error —
    includes a top-level meta object carrying at minimum a timestamp and
    request_id."

    Args:
        request_id: The correlation id to include. If not provided (for
            example, because the caller did not supply an
            ``X-Request-Id`` header to echo back, per API-ADD Section 8),
            a new one is generated.

    Returns:
        A dict with keys ``timestamp`` (ISO-8601 UTC) and ``request_id``.
    """
    return {
        "timestamp": format_iso8601(utc_now()),
        "request_id": request_id or generate_request_correlation_id(),
    }


def build_success_response(data: Any, *, request_id: str | None = None) -> dict[str, Any]:
    """Build a standard single-resource success response.

    Matches API-ADD Section 9's single-resource response example.

    Args:
        data: The already-serialized resource payload (typically the
            output of ``app.utils.serialization.serialize``).
        request_id: The correlation id to include, or ``None`` to
            generate one.

    Returns:
        A dict with keys ``data`` and ``meta``.
    """
    return {"data": data, "meta": build_meta(request_id=request_id)}


def build_list_response(
    items: list[Any],
    *,
    pagination: PaginationMetadata,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build a standard list (paginated) success response.

    Matches API-ADD Section 9's list response example.

    Args:
        items: The already-serialized list of resource payloads.
        pagination: The pagination metadata to include, typically built
            via ``app.utils.pagination.build_pagination_metadata``.
        request_id: The correlation id to include, or ``None`` to
            generate one.

    Returns:
        A dict with keys ``data``, ``pagination``, and ``meta``.
    """
    return {
        "data": items,
        "pagination": pagination.to_dict(),
        "meta": build_meta(request_id=request_id),
    }


def build_error_response(
    code: ErrorCode,
    message: str,
    *,
    details: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build a standard error response.

    Matches API-ADD Section 11.1's standard error format exactly.

    Args:
        code: The machine-readable error code, from the fixed
            ``ErrorCode`` catalog.
        message: A human-readable summary, safe to display in the UI.
        details: Optional, structured, field-level detail — populated
            primarily for ``VALIDATION_ERROR`` responses, per API-ADD
            Section 11.1.
        request_id: The correlation id to include, or ``None`` to
            generate one.

    Returns:
        A dict with keys ``error`` (itself containing ``code``,
        ``message``, and optionally ``details``) and ``meta``.
    """
    error_payload: dict[str, Any] = {"code": code.value, "message": message}
    if details is not None:
        error_payload["details"] = details
    return {"error": error_payload, "meta": build_meta(request_id=request_id)}