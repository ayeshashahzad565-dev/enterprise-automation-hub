"""Repository for the ``companies`` table.

The tenant boundary every other table's ``company_id`` references. Reads
and writes here are gated entirely at the Application Layer
(``CompanyService``, via ``authorize_platform_admin``) — this repository
enforces no scoping of its own, matching every other repository in this
package.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.exceptions import InvalidQueryError
from app.database.repositories.base_repository import (
    BaseRepository,
    Page,
    PagedResult,
    parse_datetime,
    parse_uuid,
)

logger = logging.getLogger(__name__)

__all__ = ["CompanyRecord", "CompanyRepository"]


@dataclass(frozen=True, slots=True)
class CompanyRecord:
    """An immutable, persistence-level representation of one ``companies`` row.

    Attributes:
        id: Primary key.
        name: The company's display name.
        slug: A unique, URL-safe identifier.
        is_active: Whether this company may still be used.
        contact_email: The tenant's primary contact address, if recorded.
        notes: Free-text platform-admin notes about this tenant, if any.
        version: Optimistic-locking row version.
        created_at: Record creation timestamp.
        updated_at: Last modification timestamp.
        deleted_at: Soft-deletion timestamp, if this company was removed.
        deleted_by: The platform admin who removed it, if soft-deleted.
    """

    id: UUID
    name: str
    slug: str
    is_active: bool
    contact_email: str | None
    notes: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    deleted_by: UUID | None


def _map_company_row(row: dict[str, Any]) -> CompanyRecord:
    """Map a raw Supabase row dict into a ``CompanyRecord``."""
    return CompanyRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        name=row["name"],
        slug=row["slug"],
        is_active=row["is_active"],
        contact_email=row.get("contact_email"),
        notes=row.get("notes"),
        version=row["version"],
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
        updated_at=parse_datetime(row["updated_at"]),  # type: ignore[arg-type]
        deleted_at=parse_datetime(row.get("deleted_at")),
        deleted_by=parse_uuid(row.get("deleted_by")),
    )


class CompanyRepository(BaseRepository[CompanyRecord]):
    """Persistence operations for the ``companies`` table."""

    table_name = "companies"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def get_by_id(self, company_id: UUID) -> CompanyRecord:  # type: ignore[override]
        """Fetch a company by its id.

        Args:
            company_id: The company's ``id``.

        Returns:
            The matching ``CompanyRecord``.

        Raises:
            RecordNotFoundError: If no company with this id exists.
        """
        return super().get_by_id(company_id, mapper=_map_company_row)

    def find_by_id(self, company_id: UUID) -> CompanyRecord | None:  # type: ignore[override]
        """Fetch a company by its id, tolerating absence."""
        return super().find_by_id(company_id, mapper=_map_company_row)

    def create_company(self, *, name: str, slug: str) -> CompanyRecord:
        """Insert a new, active company row.

        Args:
            name: The company's display name.
            slug: A unique, URL-safe identifier, computed by the caller
                (``CompanyService``).

        Returns:
            The newly created ``CompanyRecord``.

        Raises:
            ConstraintViolationError: If ``slug`` is not unique.
        """
        values: dict[str, Any] = {"name": name, "slug": slug}
        return self.insert(values, mapper=_map_company_row)

    def update_company(
        self,
        company_id: UUID,
        *,
        expected_version: int,
        name: str | None = None,
        is_active: bool | None = None,
        contact_email: str | None = None,
        notes: str | None = None,
    ) -> CompanyRecord:
        """Update a company's mutable fields under optimistic-locking control.

        Args:
            company_id: The company's ``id``.
            expected_version: The version last observed by the caller.
            name: The new display name, if changing.
            is_active: The new active status, if changing.
            contact_email: The new contact email, if changing. Pass an
                empty string to clear it — ``None`` means "leave
                unchanged", matching every other optional field here.
            notes: The new notes, if changing. Same empty-string-to-clear
                convention as ``contact_email``.

        Returns:
            The updated ``CompanyRecord``.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version.
            InvalidQueryError: If no field to update was provided.
        """
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if is_active is not None:
            values["is_active"] = is_active
        if contact_email is not None:
            values["contact_email"] = contact_email
        if notes is not None:
            values["notes"] = notes
        if not values:
            raise InvalidQueryError("update_company requires at least one field to update.")
        return self.update_with_optimistic_lock(
            company_id,
            expected_version=expected_version,
            values=values,
            mapper=_map_company_row,
        )

    def soft_delete(self, company_id: UUID, *, expected_version: int, deleted_by: UUID) -> CompanyRecord:
        """Soft-delete a company: retains every row it owns, blocks access.

        Mirrors ``RequestRepository.soft_delete``'s exact shape. Never
        removes the row; populates ``deleted_at``/``deleted_by`` only —
        access is actually blocked by
        ``app.auth.supabase_verifier.SupabaseTokenVerifier`` checking this
        flag on every request, not by anything at the persistence layer.

        Args:
            company_id: The company's ``id``.
            expected_version: The version last observed by the caller.
            deleted_by: The platform admin performing the deletion.

        Returns:
            The updated ``CompanyRecord``, with ``deleted_at`` populated.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version.
        """
        values: dict[str, Any] = {
            "deleted_at": datetime.now().astimezone().isoformat(),
            "deleted_by": str(deleted_by),
        }
        return self.update_with_optimistic_lock(
            company_id, expected_version=expected_version, values=values, mapper=_map_company_row
        )

    def restore(self, company_id: UUID, *, expected_version: int) -> CompanyRecord:
        """Reverse a soft-deletion, restoring the company to the active list.

        Args:
            company_id: The company's ``id``.
            expected_version: The version last observed by the caller.

        Returns:
            The updated ``CompanyRecord``, with ``deleted_at``/``deleted_by``
            cleared.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version.
        """
        values: dict[str, Any] = {"deleted_at": None, "deleted_by": None}
        return self.update_with_optimistic_lock(
            company_id, expected_version=expected_version, values=values, mapper=_map_company_row
        )

    def list_companies(
        self, *, include_deleted: bool = False, page: Page = Page()
    ) -> PagedResult[CompanyRecord]:
        """List every company, newest first.

        Args:
            include_deleted: Whether to include soft-deleted companies.
                Defaults to ``False`` (the platform admin's ordinary,
                active view), matching ``requests``' own soft-delete list
                convention.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of companies.
        """
        builder = self._select("*", count="exact")
        if not include_deleted:
            builder = builder.is_("deleted_at", "null")
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_company_row)

    def count_companies(
        self, *, is_active: bool | None = None, include_deleted: bool = False
    ) -> int:
        """Count companies, optionally restricted to active/inactive.

        Args:
            is_active: Restrict to active (``True``) or inactive
                (``False``) companies, if provided.
            include_deleted: Whether to include soft-deleted companies.

        Returns:
            The matching company count.
        """
        builder = self._select("id", count="exact")
        if not include_deleted:
            builder = builder.is_("deleted_at", "null")
        if is_active is not None:
            builder = builder.eq("is_active", is_active)
        return self.count(builder)
