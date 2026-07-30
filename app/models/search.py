"""Domain models for enterprise-wide search's saved filters and search history.

``SearchResultItem`` itself (the actual search-result row shape) remains
defined in ``app.services.search_service`` — a plain ``dataclass``, not a
Pydantic model, matching that module's own stated reasoning (a query
result assembled in-process, never persisted, never a PATCH target).
This module covers only the two persisted, user-owned concepts: a saved
filter and a search-history entry.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from app.models.base import IdentifiedModel, TimestampedModel, UpdatableTimestampModel

__all__ = ["SavedFilter", "SearchHistoryEntry"]


class SavedFilter(IdentifiedModel, UpdatableTimestampModel):
    """A user's own named, reusable search.

    Attributes:
        user_id: The owning user.
        name: The filter's display name, unique per user.
        query_text: The saved free-text query.
        entity_types: The saved entity-type restriction, or ``None`` for
            "search every entity type."
        filters: The saved advanced-filter payload (date range, status,
            role, etc.) — opaque to the backend, interpreted by the
            frontend that wrote it.
    """

    user_id: UUID
    name: str
    query_text: str
    entity_types: list[str] | None = None
    filters: dict[str, Any] = Field(default_factory=dict)


class SearchHistoryEntry(IdentifiedModel, TimestampedModel):
    """One past search a user performed.

    Attributes:
        user_id: The user who performed this search.
        query_text: The search term that was entered.
        entity_types: The entity-type restriction that was applied, if any.
        result_count: How many results this search returned.
    """

    user_id: UUID
    query_text: str
    entity_types: list[str] | None = None
    result_count: int
