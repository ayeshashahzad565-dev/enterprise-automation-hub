"""HTTP schemas for the ``search`` resource (enterprise-wide search)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field

from app.models.base import EAHBaseModel, UTCDatetime

__all__ = [
    "SearchResultOut",
    "SavedFilterOut",
    "CreateSavedFilterBody",
    "SearchHistoryEntryOut",
]


class SearchResultOut(EAHBaseModel):
    """One row of a search result.

    A thinner contract than ``app.services.search_service.SearchResultItem``
    itself: ``stage`` (a full ``WorkflowStage``) is flattened down to
    ``stage_id``/``stage_name`` rather than re-exposing an internal
    domain object wholesale — a caller that wants the full stage still
    has ``stage_id`` to fetch it through the existing approvals API.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_type: str
    id: UUID
    title: str
    subtitle: str
    snippet: str
    score: float
    created_at: UTCDatetime
    request_id: UUID | None
    stage_id: UUID | None
    stage_name: str | None
    request_type: str | None


class SavedFilterOut(EAHBaseModel):
    """Wraps ``app.models.search.SavedFilter``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    id: UUID
    user_id: UUID
    name: str
    query_text: str
    entity_types: list[str] | None
    filters: dict[str, Any]
    created_at: UTCDatetime
    updated_at: UTCDatetime


class CreateSavedFilterBody(EAHBaseModel):
    """Body for ``POST /search/saved-filters``."""

    name: str = Field(min_length=1, max_length=100)
    query_text: str = Field(default="", max_length=500)
    entity_types: list[str] | None = None
    filters: dict[str, Any] = Field(default_factory=dict)


class SearchHistoryEntryOut(EAHBaseModel):
    """Wraps ``app.models.search.SearchHistoryEntry``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    id: UUID
    query_text: str
    entity_types: list[str] | None
    result_count: int
    created_at: UTCDatetime
