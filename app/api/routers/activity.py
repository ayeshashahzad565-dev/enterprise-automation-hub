"""Routes for the caller's personal Activity feed.

Per the Phase 5 migration plan, this is the self-scoped counterpart to
``app.api.routers.analytics``'s admin-only, organization-wide
``GET /audit-logs`` — both are thin wrappers over the same
``AuditRepository.list_all`` (the same documented, narrow "no Application
Service exists for this org-wide read" exception that module's docstring
already explains), just scoped by ``actor_id=identity.user_id`` here
rather than left unscoped. ``list_all`` is reused directly rather than
the otherwise-unused ``AuditRepository.list_for_actor``, since ``list_all``
already supports the ``action``/date-range filters this feed also offers,
which ``list_for_actor`` does not.

No RBAC gate is applied: every role may see its own activity, since this
endpoint never exposes another user's data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_audit_repository, get_current_identity, get_profile_repository
from app.api.schemas.analytics import AuditLogEntryOut
from app.auth.authentication import AuthenticatedIdentity
from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database.exceptions import RecordNotFoundError
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page
from app.database.repositories.user_repository import ProfileRepository
from app.models.enums import AuditAction
from app.utils.pagination import build_pagination_metadata
from app.utils.response import build_list_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["activity"])


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/activity/mine")
def list_my_activity(
    request: Request,
    action: str | None = Query(None, max_length=100),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
) -> dict[str, Any]:
    """The caller's own activity feed. See ``AuditRepository.list_all``."""
    result = audit_repo.list_all(
        company_id=identity.company_id,
        actor_id=identity.user_id,
        action=action,
        created_after=created_after,
        created_before=created_before,
        page=Page(number=page, size=page_size),
    )

    actor_name: str | None
    try:
        actor_name = profile_repo.get_by_id(identity.user_id).full_name
    except RecordNotFoundError:
        actor_name = None

    items = [
        AuditLogEntryOut(
            id=entry.id,
            actor_id=entry.actor_id,
            actor_name=actor_name,
            request_id=entry.request_id,
            action=AuditAction(entry.action),
            metadata=entry.metadata,
            created_at=entry.created_at,
        )
        for entry in result.items
    ]

    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    return build_list_response(
        [serialize(item) for item in items],
        pagination=pagination,
        request_id=_request_id_of(request),
    )
