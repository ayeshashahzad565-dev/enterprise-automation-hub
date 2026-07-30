"""Repository for the ``saved_filters`` table.

Per the enterprise-wide search feature's saved-filters capability
(explicit user decision: backend-persisted, not ``localStorage``-only),
a saved filter is a user's own named, reusable search — query text plus
an optional entity-type restriction plus an arbitrary advanced-filter
payload (date ranges, status, role, etc.), stored as ``jsonb`` since its
shape varies per entity type and this repository has no reason to know
it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.exceptions import RecordNotFoundError
from app.database.repositories.base_repository import BaseRepository, parse_datetime, parse_uuid

__all__ = ["SavedFilterRecord", "SavedFilterRepository"]


@dataclass(frozen=True, slots=True)
class SavedFilterRecord:
    """An immutable, persistence-level representation of one ``saved_filters`` row.

    Attributes:
        id: Primary key.
        user_id: The user this saved filter belongs to.
        company_id: The user's company (tenant), carried for defense-in-
            depth scoping even though ``user_id`` alone already isolates
            one user's own rows.
        name: The filter's user-chosen display name, unique per user.
        query_text: The saved free-text query, if any.
        entity_types: The saved entity-type restriction, if any.
        filters: The saved advanced-filter payload (date range, status,
            role, etc.) — opaque to this repository.
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
    """

    id: UUID
    user_id: UUID
    company_id: UUID
    name: str
    query_text: str
    entity_types: list[str] | None
    filters: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _map_saved_filter_row(row: dict[str, Any]) -> SavedFilterRecord:
    """Map a raw Supabase row dict into a ``SavedFilterRecord``."""
    return SavedFilterRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        user_id=parse_uuid(row["user_id"]),  # type: ignore[arg-type]
        company_id=parse_uuid(row["company_id"]),  # type: ignore[arg-type]
        name=row["name"],
        query_text=row["query_text"],
        entity_types=row.get("entity_types"),
        filters=row.get("filters") or {},
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
        updated_at=parse_datetime(row["updated_at"]),  # type: ignore[arg-type]
    )


class SavedFilterRepository(BaseRepository[SavedFilterRecord]):
    """Persistence operations for the ``saved_filters`` table."""

    table_name = "saved_filters"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def list_for_user(self, user_id: UUID, *, company_id: UUID) -> list[SavedFilterRecord]:
        """List every saved filter belonging to a user.

        Args:
            user_id: The owning user's id.
            company_id: The user's company (tenant), applied as an
                additional predicate for defense-in-depth even though
                ``user_id`` alone already isolates the correct rows.

        Returns:
            The user's saved filters, most recently updated first.
        """
        response = self._execute(
            self._select("*")
            .eq("user_id", str(user_id))
            .eq("company_id", str(company_id))
            .order("updated_at", desc=True),
            operation="list_for_user",
        )
        return [_map_saved_filter_row(row) for row in self._rows(response)]

    def create(
        self,
        *,
        user_id: UUID,
        company_id: UUID,
        name: str,
        query_text: str,
        entity_types: list[str] | None,
        filters: dict[str, Any],
    ) -> SavedFilterRecord:
        """Insert a new saved filter.

        Args:
            user_id: The owning user's id.
            company_id: The user's company (tenant).
            name: The filter's display name (unique per user).
            query_text: The saved free-text query.
            entity_types: The saved entity-type restriction, if any.
            filters: The saved advanced-filter payload.

        Returns:
            The newly created ``SavedFilterRecord``.

        Raises:
            ConstraintViolationError: If ``name`` collides with an
                existing saved filter for this user.
        """
        values: dict[str, Any] = {
            "user_id": str(user_id),
            "company_id": str(company_id),
            "name": name,
            "query_text": query_text,
            "entity_types": entity_types,
            "filters": filters,
        }
        return self.insert(values, mapper=_map_saved_filter_row)

    def delete(self, filter_id: UUID, *, user_id: UUID) -> None:
        """Delete a saved filter, scoped to its owner.

        The ``user_id`` predicate is applied in the delete itself (not
        checked as a separate read-then-delete step), so one user can
        never delete another user's saved filter even if they somehow
        learn its id.

        Args:
            filter_id: The saved filter's ``id``.
            user_id: The caller's own id — must match the row's owner.

        Raises:
            RecordNotFoundError: If no saved filter with this id exists
                for this user.
        """
        response = self._execute(
            self._query().delete().eq("id", str(filter_id)).eq("user_id", str(user_id)),
            operation="delete",
        )
        if not self._rows(response):
            raise RecordNotFoundError(self.table_name, filter_id)
