"""Repository for the ``profiles`` table.

Per DSD Section 3.1, ``profiles`` extends Supabase's ``auth.users`` with
application-specific identity attributes (role, department, display name)
required for authorization and display. This module defines the
``UserRole`` enum shared throughout the rest of ``app.database`` (imported
by ``workflow_repository`` and ``approval_repository`` wherever a role
needs to be referenced), and the ``ProfileRepository`` class.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
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


class UserRole(str, Enum):
    """The three roles fixed by DSD Section 1.5's ``user_role`` enum.

    Values are lowercase strings matching the native PostgreSQL enum
    exactly (DSD Section 3.3's enum-conventions rationale), so that a
    ``UserRole`` member's ``.value`` can be sent directly to Supabase
    without translation.
    """

    EMPLOYEE = "employee"
    APPROVER = "approver"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    """An immutable, persistence-level representation of one ``profiles`` row.

    This is a thin data-transfer object mirroring the table's columns
    exactly (DSD Section 3.1) — it performs no validation and enforces no
    business rule; that is the responsibility of the corresponding Domain
    Layer model (``src/models``), which this record is intended to be
    mapped into by the Application Layer.

    Attributes:
        id: Primary key, equal to the corresponding ``auth.users.id``.
        full_name: Display name.
        role: The user's RBAC role.
        department: Organizational department, if set.
        version: Optimistic-locking row version (DSD Section 3.9).
        created_at: Record creation timestamp.
        updated_at: Last modification timestamp.
    """

    id: UUID
    full_name: str
    role: UserRole
    department: str | None
    version: int
    created_at: datetime
    updated_at: datetime


def _map_profile_row(row: dict[str, Any]) -> ProfileRecord:
    """Map a raw Supabase row dict into a ``ProfileRecord``."""
    return ProfileRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        full_name=row["full_name"],
        role=UserRole(row["role"]),
        department=row.get("department"),
        version=row["version"],
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
        updated_at=parse_datetime(row["updated_at"]),  # type: ignore[arg-type]
    )


class ProfileRepository(BaseRepository[ProfileRecord]):
    """Persistence operations for the ``profiles`` table.

    Corresponds to the ``AuthService``'s persistence needs described in
    the ADD, and to the ``AssignmentResolver``'s manager/department
    lookups described in WEDD Section 7.
    """

    table_name = "profiles"

    def __init__(self, client: DatabaseClient) -> None:
        super().__init__(client)

    def get_by_id(self, profile_id: UUID) -> ProfileRecord:  # type: ignore[override]
        """Fetch a profile by its id.

        Args:
            profile_id: The profile's ``id`` (equal to ``auth.users.id``).

        Returns:
            The matching ``ProfileRecord``.

        Raises:
            RecordNotFoundError: If no profile with this id exists or is
                visible under the current client's Row-Level Security
                context (DSD Section 9.2).
        """
        return super().get_by_id(profile_id, mapper=_map_profile_row)

    def find_by_id(self, profile_id: UUID) -> ProfileRecord | None:  # type: ignore[override]
        """Fetch a profile by its id, tolerating absence.

        Args:
            profile_id: The profile's ``id``.

        Returns:
            The matching ``ProfileRecord``, or ``None`` if not found.
        """
        return super().find_by_id(profile_id, mapper=_map_profile_row)

    def create_profile(
        self,
        *,
        profile_id: UUID,
        full_name: str,
        role: UserRole = UserRole.EMPLOYEE,
        department: str | None = None,
    ) -> ProfileRecord:
        """Insert a new profile row.

        In normal production operation this row is created automatically
        by a Supabase trigger the first time a user authenticates (DSD
        Section 3.1's business rule); this method exists for the cases
        where the Application Layer or test fixtures need to create one
        directly (for example, seeding test data per TSD Section 11).

        Args:
            profile_id: The profile's ``id``, matching an existing
                ``auth.users.id``.
            full_name: The display name to store.
            role: The initial RBAC role. Defaults to ``UserRole.EMPLOYEE``,
                matching the column's database default (DSD Section 3.1).
            department: The initial department, if known.

        Returns:
            The newly created ``ProfileRecord``.

        Raises:
            ConstraintViolationError: If ``profile_id`` does not resolve
                to an existing ``auth.users`` row (foreign key violation),
                or a profile with this id already exists.
        """
        values: dict[str, Any] = {
            "id": str(profile_id),
            "full_name": full_name,
            "role": role.value,
            "department": department,
        }
        return self.insert(values, mapper=_map_profile_row)

    def update_profile(
        self,
        profile_id: UUID,
        *,
        expected_version: int,
        full_name: str | None = None,
        role: UserRole | None = None,
        department: str | None = None,
    ) -> ProfileRecord:
        """Update mutable profile fields under optimistic-locking control.

        Only the fields explicitly passed (non-``None``) are included in
        the update payload, per the partial-merge-patch semantics
        established in API-ADD Section 3.6; a caller wishing to clear
        ``department`` must pass an empty string, since ``None`` here
        means "leave unchanged," consistent with that same convention.

        Args:
            profile_id: The profile's ``id``.
            expected_version: The version last observed by the caller.
            full_name: The new display name, if changing.
            role: The new RBAC role, if changing. Role changes are
                restricted to administrators at the Application Layer
                (API-ADD Section 19.2.2); this repository enforces no
                such restriction itself.
            department: The new department, if changing.

        Returns:
            The updated ``ProfileRecord``.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version.
            InvalidQueryError: If no field to update was provided.
        """
        values: dict[str, Any] = {}
        if full_name is not None:
            values["full_name"] = full_name
        if role is not None:
            values["role"] = role.value
        if department is not None:
            values["department"] = department
        if not values:
            raise InvalidQueryError(
                "update_profile requires at least one field to update."
            )
        return self.update_with_optimistic_lock(
            profile_id,
            expected_version=expected_version,
            values=values,
            mapper=_map_profile_row,
        )

    def list_by_role(
        self,
        role: UserRole,
        *,
        department: str | None = None,
        page: Page = Page(),
    ) -> PagedResult[ProfileRecord]:
        """List profiles matching a given role, optionally scoped to a department.

        Used by ``AssignmentResolver`` (WEDD Section 7.3) to resolve the
        eligible pool for a ``department_queue`` assignment strategy.

        Args:
            role: The role to filter by.
            department: If provided, further restricts results to this
                department.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching profiles.
        """
        builder = self._query().eq("role", role.value)
        if department is not None:
            builder = builder.eq("department", department)
        builder = builder.order("full_name")
        return self.paginate(builder, page, mapper=_map_profile_row)