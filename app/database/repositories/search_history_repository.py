"""Repository for the ``search_history`` table.

An append-only log of one user's own past searches, powering "recent
searches" suggestions in the enterprise-wide search UI. Per the
migration's own docstring, this table has no retention/cleanup job in
this pass — a disclosed, deliberate scope boundary matching this
codebase's existing ``audit_logs``/``jobs`` precedent for other
append-only tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.repositories.base_repository import BaseRepository, parse_datetime, parse_uuid

__all__ = ["SearchHistoryRecord", "SearchHistoryRepository"]


@dataclass(frozen=True, slots=True)
class SearchHistoryRecord:
    """An immutable, persistence-level representation of one ``search_history`` row.

    Attributes:
        id: Primary key.
        user_id: The user who performed this search.
        company_id: The user's company (tenant).
        query_text: The search term that was entered.
        entity_types: The entity-type restriction that was applied, if any.
        result_count: How many results this search returned.
        created_at: When the search was performed.
    """

    id: UUID
    user_id: UUID
    company_id: UUID
    query_text: str
    entity_types: list[str] | None
    result_count: int
    created_at: datetime


def _map_search_history_row(row: dict[str, Any]) -> SearchHistoryRecord:
    """Map a raw Supabase row dict into a ``SearchHistoryRecord``."""
    return SearchHistoryRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        user_id=parse_uuid(row["user_id"]),  # type: ignore[arg-type]
        company_id=parse_uuid(row["company_id"]),  # type: ignore[arg-type]
        query_text=row["query_text"],
        entity_types=row.get("entity_types"),
        result_count=int(row["result_count"]),
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


class SearchHistoryRepository(BaseRepository[SearchHistoryRecord]):
    """Persistence operations for the ``search_history`` table."""

    table_name = "search_history"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def record(
        self,
        *,
        user_id: UUID,
        company_id: UUID,
        query_text: str,
        entity_types: list[str] | None,
        result_count: int,
    ) -> SearchHistoryRecord:
        """Append one search-history entry.

        Args:
            user_id: The user who performed the search.
            company_id: The user's company (tenant).
            query_text: The search term that was entered.
            entity_types: The entity-type restriction that was applied,
                if any.
            result_count: How many results the search returned.

        Returns:
            The newly created ``SearchHistoryRecord``.
        """
        values: dict[str, Any] = {
            "user_id": str(user_id),
            "company_id": str(company_id),
            "query_text": query_text,
            "entity_types": entity_types,
            "result_count": result_count,
        }
        return self.insert(values, mapper=_map_search_history_row)

    def list_recent(
        self, user_id: UUID, *, company_id: UUID, limit: int = 10
    ) -> list[SearchHistoryRecord]:
        """List a user's most recent, de-duplicated search queries.

        Fetches the last ``limit * 3`` raw entries (a query typed
        repeatedly in one session would otherwise crowd out older,
        distinct queries) and de-duplicates by ``query_text`` in Python,
        preserving recency order — the same "narrow projection + Python
        aggregation" convention used throughout this codebase, since
        PostgREST has no ``DISTINCT ON``.

        Args:
            user_id: The user's id.
            company_id: The user's company (tenant).
            limit: The maximum number of distinct queries to return.

        Returns:
            Up to ``limit`` of the user's most recent distinct search
            queries, newest first.
        """
        response = self._execute(
            self._select("*")
            .eq("user_id", str(user_id))
            .eq("company_id", str(company_id))
            .order("created_at", desc=True)
            .limit(limit * 3),
            operation="list_recent",
        )
        seen: set[str] = set()
        deduped: list[SearchHistoryRecord] = []
        for row in self._rows(response):
            record = _map_search_history_row(row)
            key = record.query_text.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(record)
            if len(deduped) >= limit:
                break
        return deduped

    def clear_for_user(self, user_id: UUID) -> int:
        """Delete every search-history entry for a user.

        Args:
            user_id: The user's id.

        Returns:
            The number of entries deleted (``0`` if the user had none).
        """
        response = self._execute(
            self._query().delete().eq("user_id", str(user_id)),
            operation="clear_for_user",
        )
        return len(self._rows(response))
