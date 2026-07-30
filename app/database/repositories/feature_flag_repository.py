"""Repository for the ``feature_flags`` table.

Global (not per-tenant) flags, platform-admin managed. A small, fixed set
of rows in practice — every read method here returns the full set rather
than paginating.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.exceptions import InvalidQueryError
from app.database.repositories.base_repository import BaseRepository, parse_datetime, parse_uuid

logger = logging.getLogger(__name__)

__all__ = ["FeatureFlagRecord", "FeatureFlagRepository"]


@dataclass(frozen=True, slots=True)
class FeatureFlagRecord:
    """An immutable, persistence-level representation of one ``feature_flags`` row.

    Attributes:
        key: The flag's stable identifier (primary key).
        description: A human-readable description.
        enabled: Whether this flag is currently on.
        updated_at: Last modification timestamp.
        updated_by: The platform admin who last changed this flag, if any.
    """

    key: str
    description: str
    enabled: bool
    updated_at: datetime
    updated_by: UUID | None


def _map_flag_row(row: dict[str, Any]) -> FeatureFlagRecord:
    """Map a raw Supabase row dict into a ``FeatureFlagRecord``."""
    return FeatureFlagRecord(
        key=row["key"],
        description=row["description"],
        enabled=row["enabled"],
        updated_at=parse_datetime(row["updated_at"]),  # type: ignore[arg-type]
        updated_by=parse_uuid(row.get("updated_by")),
    )


class FeatureFlagRepository(BaseRepository[FeatureFlagRecord]):
    """Persistence operations for the ``feature_flags`` table."""

    table_name = "feature_flags"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def create(
        self, *, key: str, description: str, enabled: bool, updated_by: UUID | None
    ) -> FeatureFlagRecord:
        """Define a new feature flag.

        Args:
            key: The flag's stable identifier.
            description: A human-readable description.
            enabled: The flag's initial state.
            updated_by: The platform admin defining this flag.

        Returns:
            The newly created ``FeatureFlagRecord``.

        Raises:
            ConstraintViolationError: If ``key`` is not unique.
        """
        values: dict[str, Any] = {
            "key": key,
            "description": description,
            "enabled": enabled,
            "updated_by": str(updated_by) if updated_by else None,
        }
        return self.insert(values, mapper=_map_flag_row)

    def get_by_key(self, key: str) -> FeatureFlagRecord:  # type: ignore[override]
        """Fetch a flag by its key.

        Args:
            key: The flag's identifier.

        Returns:
            The matching ``FeatureFlagRecord``.

        Raises:
            RecordNotFoundError: If no flag with this key exists.
        """
        response = self._execute(
            self._query().select("*").eq("key", key).limit(1),
            operation="get_by_key",
        )
        row = self._single_row(response, identifier=key)
        return _map_flag_row(row)

    def list_all(self) -> list[FeatureFlagRecord]:
        """List every feature flag, alphabetically by key.

        Returns:
            Every ``FeatureFlagRecord``.
        """
        response = self._execute(
            self._select("*").order("key"),
            operation="list_all",
        )
        return [_map_flag_row(row) for row in self._rows(response)]

    def update(
        self,
        key: str,
        *,
        description: str | None = None,
        enabled: bool | None = None,
        updated_by: UUID | None = None,
    ) -> FeatureFlagRecord:
        """Update a flag's mutable fields.

        A plain, unconditional update (no optimistic locking): only
        platform admins ever write to this table, and a lost-update race
        between two platform admins toggling the same flag is an
        acceptable, extremely rare edge case for an informational-only
        flag, unlike a business-critical resource.

        Args:
            key: The flag's identifier.
            description: The new description, if changing.
            enabled: The new on/off state, if changing.
            updated_by: The platform admin performing this write.

        Returns:
            The updated ``FeatureFlagRecord``.

        Raises:
            InvalidQueryError: If no field to update was provided.
            RecordNotFoundError: If no flag with this key exists.
        """
        values: dict[str, Any] = {}
        if description is not None:
            values["description"] = description
        if enabled is not None:
            values["enabled"] = enabled
        if not values:
            raise InvalidQueryError("update requires at least one field to update.")
        values["updated_by"] = str(updated_by) if updated_by else None
        response = self._execute(
            self._query().update(values).eq("key", key),
            operation="update",
        )
        row = self._single_row(response, identifier=key)
        return _map_flag_row(row)
