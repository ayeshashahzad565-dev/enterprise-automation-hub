"""Routes for the ``search`` resource: enterprise-wide search, saved
filters, and search history.

Thin wrappers over ``GlobalSearchService`` — see
``app.api.routers.requests``'s module docstring for the general
convention this file follows (a real, service-backed router, not the
``platform.py``-style "router-direct repository access" exception, since
``GlobalSearchService`` is a real Application Service with real
authorization logic of its own).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from app.api.dependencies import get_current_identity, get_search_service
from app.api.rate_limiting import enforce_search_rate_limit
from app.api.schemas.search import (
    CreateSavedFilterBody,
    SavedFilterOut,
    SearchHistoryEntryOut,
    SearchResultOut,
)
from app.auth.authentication import AuthenticatedIdentity
from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database.repositories.base_repository import Page
from app.services.search_service import GlobalSearchService, SearchResultItem
from app.utils.pagination import build_pagination_metadata
from app.utils.response import build_list_response, build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(prefix="/search", tags=["search"])

#: The maximum number of recent searches ``GET /search/history`` returns.
_RECENT_SEARCH_LIMIT = 10


def _request_id_of(request: Request) -> str | None:
    """Read the correlation id ``RequestIDMiddleware`` attached to this request."""
    return getattr(request.state, "request_id", None)


def _to_search_result_out(item: SearchResultItem) -> SearchResultOut:
    """Flatten a ``SearchResultItem`` into its thinner HTTP contract."""
    return SearchResultOut(
        entity_type=item.entity_type,
        id=item.id,
        title=item.title,
        subtitle=item.subtitle,
        snippet=item.snippet,
        score=item.score,
        created_at=item.created_at,
        request_id=item.request_id,
        stage_id=item.stage.id if item.stage is not None else None,
        stage_name=item.stage.stage_name if item.stage is not None else None,
        request_type=item.request_type,
    )


@router.get("", dependencies=[Depends(enforce_search_rate_limit)])
def search(
    request: Request,
    q: str = Query(..., min_length=1, alias="q"),
    entity_types: str | None = Query(None, description="Comma-separated list of entity types."),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: GlobalSearchService = Depends(get_search_service),
) -> dict[str, Any]:
    """Search every entity type the caller may see, ranked together. See
    ``GlobalSearchService.search``."""
    parsed_types = (
        [t.strip() for t in entity_types.split(",") if t.strip()] if entity_types else None
    )
    result = service.search(
        identity, q, entity_types=parsed_types, page=Page(number=page, size=page_size)
    )
    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    out = [serialize(_to_search_result_out(item)) for item in result.items]
    return build_list_response(out, pagination=pagination, request_id=_request_id_of(request))


@router.get("/saved-filters")
def list_saved_filters(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: GlobalSearchService = Depends(get_search_service),
) -> dict[str, Any]:
    """List the caller's own saved searches. See
    ``GlobalSearchService.list_saved_filters``."""
    filters = service.list_saved_filters(identity)
    out = [serialize(SavedFilterOut.model_validate(f)) for f in filters]
    return build_success_response(out, request_id=_request_id_of(request))


@router.post("/saved-filters", status_code=201)
def create_saved_filter(
    request: Request,
    body: CreateSavedFilterBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: GlobalSearchService = Depends(get_search_service),
) -> dict[str, Any]:
    """Save a named, reusable search. See ``GlobalSearchService.save_filter``."""
    created = service.save_filter(
        identity,
        name=body.name,
        query_text=body.query_text,
        entity_types=body.entity_types,
        filters=body.filters,
    )
    out = SavedFilterOut.model_validate(created)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.delete("/saved-filters/{filter_id}", status_code=204)
def delete_saved_filter(
    filter_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: GlobalSearchService = Depends(get_search_service),
) -> Response:
    """Delete one of the caller's own saved filters. See
    ``GlobalSearchService.delete_saved_filter``."""
    service.delete_saved_filter(identity, filter_id)
    return Response(status_code=204)


@router.get("/history")
def list_search_history(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: GlobalSearchService = Depends(get_search_service),
) -> dict[str, Any]:
    """List the caller's own recent searches. See
    ``GlobalSearchService.list_recent_searches``."""
    entries = service.list_recent_searches(identity, limit=_RECENT_SEARCH_LIMIT)
    out = [serialize(SearchHistoryEntryOut.model_validate(e)) for e in entries]
    return build_success_response(out, request_id=_request_id_of(request))


@router.delete("/history", status_code=204)
def clear_search_history(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: GlobalSearchService = Depends(get_search_service),
) -> Response:
    """Clear every one of the caller's own search-history entries. See
    ``GlobalSearchService.clear_search_history``."""
    service.clear_search_history(identity)
    return Response(status_code=204)
