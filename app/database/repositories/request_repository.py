"""Repository for the ``requests`` table.

Per DSD Section 3.3, ``requests`` is the central entity of the system — a
single business request submitted by an employee and tracked through to
completion. ``RequestStatus`` is re-exported here from
``app.models.enums`` (the single canonical definition, per DSD Section
1.5) purely for backward compatibility with existing call sites that
import it from this module, as well as the ``RequestRepository`` class.
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
    quote_postgrest_filter_value,
)
from app.models.enums import RequestStatus

logger = logging.getLogger(__name__)

__all__ = ["RequestStatus", "RequestRecord", "RequestRepository"]


@dataclass(frozen=True, slots=True)
class RequestRecord:
    """An immutable, persistence-level representation of one ``requests`` row.

    Mirrors DSD Section 3.3's column list exactly. Performs no validation
    and enforces no business rule — see ``ProfileRecord`` for the same
    caveat.

    Attributes:
        id: Primary key.
        requester_id: The submitting user's profile id.
        workflow_definition_id: The specific workflow definition version
            governing this request (WEDD Section 3.2, 9.6).
        request_type: Denormalized copy of the request type.
        title: Short human-readable summary.
        description: Full request details, if provided.
        department: Department the request was raised under, if provided.
        status: Current lifecycle status.
        current_stage_id: The stage currently awaiting action, if any.
        version: Optimistic-locking row version.
        deleted_at: Soft-deletion timestamp, if withdrawn (DSD Section 3.10).
        deleted_by: The user who withdrew/removed the request, if soft-deleted.
        created_at: Submission timestamp.
        updated_at: Last modification timestamp.
        completed_at: Timestamp of final approval, rejection, or completion.
        company_id: The company (tenant) this request belongs to,
            denormalized from the requester at creation time.
    """

    id: UUID
    requester_id: UUID
    workflow_definition_id: UUID
    request_type: str
    title: str
    description: str | None
    department: str | None
    status: RequestStatus
    current_stage_id: UUID | None
    version: int
    deleted_at: datetime | None
    deleted_by: UUID | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    company_id: UUID


def _map_request_row(row: dict[str, Any]) -> RequestRecord:
    """Map a raw Supabase row dict into a ``RequestRecord``."""
    return RequestRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        requester_id=parse_uuid(row["requester_id"]),  # type: ignore[arg-type]
        workflow_definition_id=parse_uuid(row["workflow_definition_id"]),  # type: ignore[arg-type]
        request_type=row["request_type"],
        title=row["title"],
        description=row.get("description"),
        department=row.get("department"),
        status=RequestStatus(row["status"]),
        current_stage_id=parse_uuid(row.get("current_stage_id")),
        version=row["version"],
        deleted_at=parse_datetime(row.get("deleted_at")),
        deleted_by=parse_uuid(row.get("deleted_by")),
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
        updated_at=parse_datetime(row["updated_at"]),  # type: ignore[arg-type]
        completed_at=parse_datetime(row.get("completed_at")),
        company_id=parse_uuid(row["company_id"]),  # type: ignore[arg-type]
    )


class RequestRepository(BaseRepository[RequestRecord]):
    """Persistence operations for the ``requests`` table.

    Corresponds to ``RequestService``'s persistence needs described in the
    ADD and WEDD Section 5.

    This table's Row-Level Security policies (DSD Section 9.2) are
    correctly written, but this repository deliberately stays on the
    service-role client (``always_use_injected_client=True``, see
    ``docs/tenant_isolation.md``) rather than the per-request, RLS-
    enforcing client: the approval flow updates a request's stage as the
    *approver*, not the requester, which the requester-or-admin-only
    update policy does not permit. Visibility/authorization scoping
    (requester/approver/admin role, and always company membership) is
    therefore performed entirely in the Application Layer
    (``RequestService``), which passes the resulting explicit filters
    (``company_id``, ``requester_id``, ``request_ids``) into this
    repository's methods — this class applies only the structural filters
    a caller explicitly requests, never an implicit "only my own rows"
    filter, but that is a statement about this class's own scope, not a
    claim that the database enforces the rest.
    """

    table_name = "requests"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def get_by_id(self, request_id: UUID) -> RequestRecord:  # type: ignore[override]
        """Fetch a request by its id.

        Args:
            request_id: The request's ``id``.

        Returns:
            The matching ``RequestRecord``.

        Raises:
            RecordNotFoundError: If no request with this id exists or is
                visible under the current client's RLS context.
        """
        return super().get_by_id(request_id, mapper=_map_request_row)

    def find_by_id(self, request_id: UUID) -> RequestRecord | None:  # type: ignore[override]
        """Fetch a request by its id, tolerating absence."""
        return super().find_by_id(request_id, mapper=_map_request_row)

    def create_request(
        self,
        *,
        requester_id: UUID,
        workflow_definition_id: UUID,
        request_type: str,
        title: str,
        company_id: UUID,
        description: str | None = None,
        department: str | None = None,
    ) -> RequestRecord:
        """Insert a new request row.

        This method performs only the ``requests`` insert itself. Per DSD
        Section 11 ("Request creation") and WEDD Section 5.4, this insert
        is one statement within a larger transaction that also creates
        the first ``workflow_stages`` row and updates
        ``current_stage_id`` — orchestrating that full transaction is the
        Application Layer's (``RequestService``'s) responsibility, using
        this repository and ``WorkflowStageRepository`` together, not
        this method's.

        Args:
            requester_id: The submitting user's profile id.
            workflow_definition_id: The resolved active workflow
                definition's id.
            request_type: The request type identifier.
            title: Short human-readable summary (1-200 characters,
                validated at the Domain Layer, not here).
            company_id: The company (tenant) this request belongs to —
                always the caller's own ``identity.company_id``, never
                client input.
            description: Full request details, if provided.
            department: Department the request was raised under, if
                provided.

        Returns:
            The newly created ``RequestRecord``, with
            ``status = RequestStatus.PENDING`` and ``current_stage_id =
            None`` (to be updated once the first stage is created).

        Raises:
            ConstraintViolationError: If ``requester_id`` or
                ``workflow_definition_id`` does not resolve to an
                existing row.
        """
        values: dict[str, Any] = {
            "requester_id": str(requester_id),
            "workflow_definition_id": str(workflow_definition_id),
            "request_type": request_type,
            "title": title,
            "description": description,
            "department": department,
            "status": RequestStatus.PENDING.value,
            "company_id": str(company_id),
        }
        return self.insert(values, mapper=_map_request_row)

    def set_current_stage(
        self,
        request_id: UUID,
        *,
        expected_version: int,
        current_stage_id: UUID | None,
        status: RequestStatus,
        completed_at: datetime | None = None,
    ) -> RequestRecord:
        """Advance a request's lifecycle pointer under optimistic-locking control.

        Used by the orchestrating Application Service (``ApprovalService``,
        per WEDD Section 6.2) after a stage decision, to point the request
        at its next stage, or to mark it terminal when no further stage
        exists (WEDD Section 6.5).

        Args:
            request_id: The request's ``id``.
            expected_version: The version last observed by the caller.
            current_stage_id: The new current stage, or ``None`` if the
                request has reached a terminal status.
            status: The new lifecycle status.
            completed_at: The completion timestamp, required when
                ``status`` is a terminal value (``COMPLETED`` or
                ``REJECTED``); ``None`` otherwise. Always written
                explicitly (including ``None``, which clears the column)
                rather than only when truthy — every forward transition
                that omits it does so on a row where it is already
                ``None``, so this is a no-op for them, but it is exactly
                what lets ``ApprovalService``'s compensating calls put a
                terminal transition's ``completed_at`` back to ``None``
                on rollback, not merely leave whatever the forward call
                set.

        Returns:
            The updated ``RequestRecord``.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version.
        """
        values: dict[str, Any] = {
            "current_stage_id": str(current_stage_id) if current_stage_id else None,
            "status": status.value,
            "completed_at": completed_at.isoformat() if completed_at is not None else None,
        }
        return self.update_with_optimistic_lock(
            request_id,
            expected_version=expected_version,
            values=values,
            mapper=_map_request_row,
        )

    def update_editable_fields(
        self,
        request_id: UUID,
        *,
        expected_version: int,
        title: str | None = None,
        description: str | None = None,
        department: str | None = None,
    ) -> RequestRecord:
        """Update the requester-editable fields of a still-pending request.

        Corresponds to ``PATCH /api/v1/requests/{id}`` (API-ADD Section
        19.3.4). This repository does not enforce that the request is
        still ``pending`` — that guard clause is the Application Layer's
        responsibility, evaluated before this method is called.

        Args:
            request_id: The request's ``id``.
            expected_version: The version last observed by the caller.
            title: The new title, if changing.
            description: The new description, if changing.
            department: The new department, if changing.

        Returns:
            The updated ``RequestRecord``.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version.
            InvalidQueryError: If no field to update was provided.
        """
        values: dict[str, Any] = {}
        if title is not None:
            values["title"] = title
        if description is not None:
            values["description"] = description
        if department is not None:
            values["department"] = department
        if not values:
            raise InvalidQueryError("update_editable_fields requires at least one field to update.")
        return self.update_with_optimistic_lock(
            request_id,
            expected_version=expected_version,
            values=values,
            mapper=_map_request_row,
        )

    def soft_delete(
        self,
        request_id: UUID,
        *,
        expected_version: int,
        deleted_by: UUID,
    ) -> RequestRecord:
        """Withdraw a request via soft deletion (DSD Section 3.10).

        Corresponds to ``DELETE /api/v1/requests/{id}`` (API-ADD Section
        19.3.5). This never removes the row; it populates ``deleted_at``
        and ``deleted_by`` only.

        Args:
            request_id: The request's ``id``.
            expected_version: The version last observed by the caller.
            deleted_by: The user performing the withdrawal.

        Returns:
            The updated ``RequestRecord``, with ``deleted_at`` populated.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version.
        """
        values: dict[str, Any] = {
            "deleted_at": datetime.now().astimezone().isoformat(),
            "deleted_by": str(deleted_by),
        }
        return self.update_with_optimistic_lock(
            request_id,
            expected_version=expected_version,
            values=values,
            mapper=_map_request_row,
        )

    def list_requests(
        self,
        *,
        company_id: UUID,
        status: RequestStatus | None = None,
        request_type: str | None = None,
        department: str | None = None,
        requester_id: UUID | None = None,
        request_ids: Sequence[UUID] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        include_deleted: bool = False,
        sort_descending_by_created_at: bool = True,
        page: Page = Page(),
    ) -> PagedResult[RequestRecord]:
        """List requests matching the given structural filters.

        This repository stays on the service-role client (see the class
        docstring), so RLS-based visibility scoping by requester/approver/
        admin role does not apply here — this method applies only the
        explicit filters passed in, corresponding to the query parameters
        documented in API-ADD Section 13, and ``RequestService``
        additionally computes and passes ``requester_id``/``request_ids``
        explicitly for the roles that need it (defense-in-depth, matching
        the discipline already applied throughout this package).

        Args:
            status: Restrict to this lifecycle status, if provided.
            request_type: Restrict to this request type, if provided.
            department: Restrict to this department, if provided.
            requester_id: Restrict to requests submitted by this user, if
                provided.
            request_ids: Restrict to exactly this set of request ids, if
                provided — used to scope an approver's view to requests
                with a stage assigned to them, computed by the caller.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.
            include_deleted: If ``False`` (the default), soft-deleted
                requests (``deleted_at IS NOT NULL``) are excluded, per
                DSD Section 3.10's default repository behavior. If
                ``True``, soft-deleted requests are included — used only
                by administrative views that explicitly need them.
            sort_descending_by_created_at: If ``True`` (the default),
                results are ordered newest-first, matching API-ADD
                Section 10's default sort for this resource.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching requests.
        """
        builder = self._scoped_query(company_id=company_id)
        if status is not None:
            builder = builder.eq("status", status.value)
        if request_type is not None:
            builder = builder.eq("request_type", request_type)
        if department is not None:
            builder = builder.eq("department", department)
        if requester_id is not None:
            builder = builder.eq("requester_id", str(requester_id))
        if request_ids is not None:
            builder = builder.in_("id", [str(i) for i in request_ids])
        if created_after is not None:
            builder = builder.gte("created_at", created_after.isoformat())
        if created_before is not None:
            builder = builder.lte("created_at", created_before.isoformat())
        if not include_deleted:
            builder = builder.is_("deleted_at", "null")
        builder = builder.order("created_at", desc=sort_descending_by_created_at)
        return self.paginate(builder, page, mapper=_map_request_row)

    def search_requests(
        self,
        query_text: str,
        *,
        company_id: UUID,
        requester_id: UUID | None = None,
        request_ids: Sequence[UUID] | None = None,
        include_deleted: bool = False,
        page: Page = Page(),
    ) -> PagedResult[RequestRecord]:
        """Free-text search across ``title`` and ``description``.

        Corresponds to ``GET /api/v1/requests/search`` (API-ADD Section
        19.3.6), which the API-ADD specifies as the same underlying
        operation as ``list_requests`` with a text filter rather than a
        separate resource.

        Matches either a literal substring (``ILIKE``, backed by the
        ``requests_title_trgm_idx``/``requests_description_trgm_idx``
        trigram indexes from ``0018_search_indexes``) or a stemmed word
        via the generated ``search_vector`` column (backed by
        ``requests_search_vector_idx``) — so, e.g., a query for "run"
        also matches a description containing "running", which substring
        matching alone would miss.

        Per Milestone 9's Search/Filter Injection audit: ``query_text``
        is escaped via ``escape_ilike_special_characters`` (literal
        ``%``/``_`` matching) and the resulting pattern is quoted via
        ``quote_postgrest_filter_value`` before being interpolated into
        the ``.or_()`` combined-filter string below — this repository
        runs on the service-role client (bypasses RLS), so an unescaped,
        unquoted ``query_text`` containing a comma/period/parenthesis
        could otherwise restructure the filter expression itself, not
        merely produce an unexpected substring match. The raw (unescaped)
        ``query_text`` is used for the ``search_vector`` clause instead —
        ``websearch_to_tsquery`` parses its own syntax (quoted phrases,
        ``-``/``or``), not ``ILIKE`` wildcards — but is still quoted via
        ``quote_postgrest_filter_value`` for the same filter-string-safety
        reason.

        Args:
            query_text: The search term. Matched case-insensitively
                against both ``title`` and ``description``.
            requester_id: Restrict to requests submitted by this user, if
                provided — applied as a query predicate (not a post-hoc
                Python filter) so pagination and ``total_records`` stay
                correct for a scoped caller.
            request_ids: Restrict to exactly this set of request ids, if
                provided — used to scope an approver's search to requests
                with a stage assigned to them, computed by the caller.
            include_deleted: Whether to include soft-deleted requests.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching requests, newest first.

        Raises:
            InvalidQueryError: If ``query_text`` is empty or whitespace-only.
        """
        if not query_text or not query_text.strip():
            raise InvalidQueryError("search_requests requires a non-empty query_text.")
        pattern = f"%{escape_ilike_special_characters(query_text.strip())}%"
        quoted_pattern = quote_postgrest_filter_value(pattern)
        quoted_query = quote_postgrest_filter_value(query_text.strip())
        builder = self._scoped_query(company_id=company_id).or_(
            f"title.ilike.{quoted_pattern},description.ilike.{quoted_pattern},"
            f"search_vector.wfts(english).{quoted_query}"
        )
        if requester_id is not None:
            builder = builder.eq("requester_id", str(requester_id))
        if request_ids is not None:
            builder = builder.in_("id", [str(i) for i in request_ids])
        if not include_deleted:
            builder = builder.is_("deleted_at", "null")
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_request_row)
