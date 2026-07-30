"""Repository for the ``profiles`` table.

Per DSD Section 3.1, ``profiles`` extends Supabase's ``auth.users`` with
application-specific identity attributes (role, department, display name)
required for authorization and display. ``UserRole`` is re-exported here
from ``app.models.enums`` (the single canonical definition, per DSD
Section 1.5) purely for backward compatibility with existing call sites
that import it from this module — ``workflow_repository`` and
``approval_repository`` both do — as well as the ``ProfileRepository``
class.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
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
    escape_ilike_special_characters,
    parse_datetime,
    parse_uuid,
)
from app.models.enums import UserRole

logger = logging.getLogger(__name__)

__all__ = ["UserRole", "ProfileRecord", "ProfileRepository"]


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
        company_id: The company (tenant) this profile belongs to.
        is_platform_admin: Whether this profile carries platform-level
            administrative capability, orthogonal to ``role``.
        is_active: Whether this profile may currently authenticate.
            Reversible — see ``ProfileRepository.update_profile``. Checked
            on every request by
            ``app.auth.supabase_verifier.SupabaseTokenVerifier``, mirroring
            how ``companies.is_active`` already gates an entire tenant.
        deleted_at: When this profile was erased (GDPR right-to-erasure),
            if ever. Unlike ``companies.deleted_at``, this is
            **irreversible**: erasure also overwrites ``full_name``/
            ``department`` (see ``ProfileRepository.erase``), so there is
            no ``restore`` counterpart.
        deleted_by: The admin who performed the erasure, if any.
    """

    id: UUID
    full_name: str
    role: UserRole
    department: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    company_id: UUID
    is_platform_admin: bool
    is_active: bool
    deleted_at: datetime | None
    deleted_by: UUID | None


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
        company_id=parse_uuid(row["company_id"]),  # type: ignore[arg-type]
        is_platform_admin=bool(row.get("is_platform_admin", False)),
        is_active=bool(row.get("is_active", True)),
        deleted_at=parse_datetime(row.get("deleted_at")),
        deleted_by=parse_uuid(row.get("deleted_by")),
    )


class ProfileRepository(BaseRepository[ProfileRecord]):
    """Persistence operations for the ``profiles`` table.

    Corresponds to the ``AuthService``'s persistence needs described in
    the ADD, and to the ``AssignmentResolver``'s manager/department
    lookups described in WEDD Section 7.
    """

    table_name = "profiles"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

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

    def find_by_ids(self, profile_ids: Sequence[UUID]) -> list[ProfileRecord]:
        """Bulk-resolve a set of profile ids to their records, in one query.

        Used by ``WorkflowDefinitionService._validate_assignees`` to
        resolve every ``specific_user`` stage assignee referenced by a
        definition with a single fetch, rather than one ``find_by_id``
        call per referenced id — the same bulk-resolution pattern
        ``WorkflowRepository.list_by_ids`` already provides for
        definitions.

        Args:
            profile_ids: The profile ids to resolve. An empty sequence
                returns an empty list without issuing a query. Ids with
                no matching row are simply absent from the result — this
                method never raises for a missing id.

        Returns:
            The matching ``ProfileRecord`` instances, in no particular
            order. May be shorter than ``profile_ids`` if some ids don't
            exist.
        """
        if not profile_ids:
            return []
        builder = self._select("*").in_("id", [str(i) for i in profile_ids])
        response = self._execute(builder, operation="find_by_ids")
        return [_map_profile_row(row) for row in self._rows(response)]

    def create_profile(
        self,
        *,
        profile_id: UUID,
        full_name: str,
        company_id: UUID,
        role: UserRole = UserRole.EMPLOYEE,
        department: str | None = None,
        is_platform_admin: bool = False,
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
            company_id: The company (tenant) this profile belongs to.
            role: The initial RBAC role. Defaults to ``UserRole.EMPLOYEE``,
                matching the column's database default (DSD Section 3.1).
            department: The initial department, if known.
            is_platform_admin: Whether this profile carries platform-level
                administrative capability. Defaults to ``False``.

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
            "company_id": str(company_id),
            "is_platform_admin": is_platform_admin,
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
        is_active: bool | None = None,
    ) -> ProfileRecord:
        """Update mutable profile fields under optimistic-locking control.

        Only the fields explicitly passed (non-``None``) are included in
        the update payload, per the partial-merge-patch semantics
        established in API-ADD Section 3.6; a caller wishing to clear
        ``department`` must pass an empty string, since ``None`` here
        means "leave unchanged," consistent with that same convention.
        Mirrors ``CompanyRepository.update_company``'s exact shape,
        including handling ``is_active`` as one more optional field on
        the same generic update rather than a dedicated method.

        Args:
            profile_id: The profile's ``id``.
            expected_version: The version last observed by the caller.
            full_name: The new display name, if changing.
            role: The new RBAC role, if changing. Role changes are
                restricted to administrators at the Application Layer
                (API-ADD Section 19.2.2); this repository enforces no
                such restriction itself.
            department: The new department, if changing.
            is_active: The new active status, if changing. Deactivation
                is reversible (unlike ``erase``) and touches no other
                column — see ``app.services.user_service.UserService.
                update_profile`` for the audit-event branching this
                enables.

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
        if is_active is not None:
            values["is_active"] = is_active
        if not values:
            raise InvalidQueryError("update_profile requires at least one field to update.")
        return self.update_with_optimistic_lock(
            profile_id,
            expected_version=expected_version,
            values=values,
            mapper=_map_profile_row,
        )

    def erase(
        self,
        profile_id: UUID,
        *,
        expected_version: int,
        deleted_by: UUID,
        anonymized_full_name: str,
    ) -> ProfileRecord:
        """Anonymize a profile: GDPR right-to-erasure.

        Never removes the row — every foreign key in this schema that
        must survive a user's departure (``audit_logs.actor_id``,
        ``requests.requester_id``, ``comments.author_id``,
        ``attachments.uploaded_by``) is ``ON DELETE RESTRICT``, making a
        genuine ``DELETE`` of a profile with any real history impossible
        by design (see ``0020_profile_lifecycle``'s migration docstring).
        Instead, this overwrites ``full_name``/``department`` (the only
        PII this table holds — email lives on Supabase's own
        ``auth.users`` and is scrubbed separately, by
        ``app.services.supabase_admin_client.SupabaseAuthAdminClient.
        anonymize_user``) and sets ``deleted_at``/``deleted_by``/
        ``is_active=False`` in one optimistic-locked update.

        Unlike ``CompanyRepository.soft_delete``, there is deliberately no
        ``restore`` counterpart: once ``full_name``/``department`` are
        overwritten, the original values are gone.

        Args:
            profile_id: The profile's ``id``.
            expected_version: The version last observed by the caller.
            deleted_by: The admin performing the erasure.
            anonymized_full_name: The replacement display name (computed
                by the caller — see ``UserService.erase_user`` — as a
                stable, deterministic placeholder derived from
                ``profile_id`` so distinct erased users remain
                distinguishable in historical records without exposing
                any real name).

        Returns:
            The updated ``ProfileRecord``, anonymized.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version.
        """
        values: dict[str, Any] = {
            "deleted_at": datetime.now().astimezone().isoformat(),
            "deleted_by": str(deleted_by),
            "is_active": False,
            "full_name": anonymized_full_name,
            "department": None,
        }
        return self.update_with_optimistic_lock(
            profile_id, expected_version=expected_version, values=values, mapper=_map_profile_row
        )

    def count_for_company(self, company_id: UUID) -> int:
        """Count every non-erased profile belonging to a company.

        Used by ``CompanyService.get_license`` to compute a license's
        informational ``seats_used`` figure — never enforced against
        ``seat_limit`` anywhere (see ``CompanyLicense``'s own docstring).
        Excludes erased profiles unconditionally (a GDPR-erased user
        should never count toward seat usage); deactivated-but-not-erased
        profiles still count, mirroring how a suspended (but not deleted)
        company still counts toward platform-wide totals elsewhere.

        Args:
            company_id: The company's id.

        Returns:
            The company's active (non-erased) user count.
        """
        builder = (
            self._select("id", count="exact")
            .eq("company_id", str(company_id))
            .is_("deleted_at", "null")
        )
        return self.count(builder)

    def list_by_role(
        self,
        role: UserRole,
        *,
        company_id: UUID,
        department: str | None = None,
        include_deleted: bool = False,
        page: Page = Page(),
    ) -> PagedResult[ProfileRecord]:
        """List profiles matching a given role within a company, optionally
        scoped to a department.

        Used by ``AssignmentResolver`` (WEDD Section 7.3) to resolve the
        eligible pool for a ``department_queue`` assignment strategy.

        Args:
            role: The role to filter by.
            company_id: Restricts results to this company (tenant) —
                required, never optional, so a caller can never
                accidentally issue an unscoped, cross-tenant query.
            department: If provided, further restricts results to this
                department.
            include_deleted: Whether to include erased profiles. Defaults
                to ``False`` (the ordinary admin directory view), mirroring
                ``CompanyRepository.list_companies``'s identical
                convention. Deactivated-but-not-erased profiles are always
                included regardless — only erasure hides a row here.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching profiles.
        """
        builder = (
            self._select("*", count="exact")
            .eq("role", role.value)
            .eq("company_id", str(company_id))
        )
        if department is not None:
            builder = builder.eq("department", department)
        if not include_deleted:
            builder = builder.is_("deleted_at", "null")
        builder = builder.order("full_name")
        return self.paginate(builder, page, mapper=_map_profile_row)

    def search_by_name(
        self,
        query_text: str,
        *,
        company_id: UUID,
        include_deleted: bool = False,
        page: Page = Page(),
    ) -> PagedResult[ProfileRecord]:
        """Free-text search across display names within a company.

        ``profiles`` carries no email column (email lives on Supabase's
        own ``auth.users``, outside this repository's table), so this
        matches only ``full_name`` — used by ``GlobalSearchService``'s
        administrator-only user search.

        Args:
            query_text: The search term.
            company_id: Restricts results to this company (tenant) —
                required, never optional, so a caller can never
                accidentally issue an unscoped, cross-tenant query.
            include_deleted: Whether to include erased profiles. Defaults
                to ``False`` — see ``list_by_role``'s identical parameter.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching profiles.

        Raises:
            InvalidQueryError: If ``query_text`` is empty or whitespace-only.
        """
        if not query_text or not query_text.strip():
            raise InvalidQueryError("search_by_name requires a non-empty query_text.")
        pattern = f"%{escape_ilike_special_characters(query_text.strip())}%"
        builder = (
            self._select("*", count="exact")
            .ilike("full_name", pattern)
            .eq("company_id", str(company_id))
        )
        if not include_deleted:
            builder = builder.is_("deleted_at", "null")
        builder = builder.order("full_name")
        return self.paginate(builder, page, mapper=_map_profile_row)
