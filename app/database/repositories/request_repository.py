"""Repository for the ``requests`` table.

Per DSD Section 3.3, ``requests`` is the central entity of the system — a
single business request submitted by an employee and tracked through to
completion. This module defines the ``RequestStatus`` enum (imported
elsewhere in this package wherever a request's lifecycle status needs to
be referenced) and the ``RequestRepository`` class.
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


class RequestStatus(str, Enum):
    """The five values fixed by DSD Section 1.5's ``request_status`` enum.

    ``APPROVED`` is reserved for forward compatibility (WEDD Section 20.1)
    and is not reachable through any code path in the current baseline —
    ``COMPLETED`` is the terminal "approved" state a request actually
    reaches.
    """

    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


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
    )


class RequestRepository(BaseRepository[RequestRecord]):
    """Persistence operations for the ``requests`` table.

    Corresponds to ``RequestService``'s persistence needs described in the
    ADD and WEDD Section 5. Row-Level Security (DSD Section 9.2) is relied
    upon to scope which rows a given anon-key client can see; this
    repository applies only the structural filters a caller explicitly
    requests (status, type, department, date range), never an implicit
    "only my own rows" filter, since that scoping is the database's job,
    not this class's.
    """

    table_name = "requests"

    def __init__(self, client: DatabaseClient) -> None:
        super().__init__(client)

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
                ``REJECTED``); ``None`` otherwise.

        Returns:
            The updated ``RequestRecord``.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version.
        """
        values: dict[str, Any] = {
            "current_stage_id": str(current_stage_id) if current_stage_id else None,
            "status": status.value,
        }
        if completed_at is not None:
            values["completed_at"] = completed_at.isoformat()
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
            raise InvalidQueryError(
                "update_editable_fields requires at least one field to update."
            )
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
        status: RequestStatus | None = None,
        request_type: str | None = None,
        department: str | None = None,
        requester_id: UUID | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        include_deleted: bool = False,
        sort_descending_by_created_at: bool = True,
        page: Page = Page(),
    ) -> PagedResult[RequestRecord]:
        """List requests matching the given structural filters.

        Visibility scoping by requester/approver/admin role is performed
        entirely by Row-Level Security on the underlying connection (DSD
        Section 9.2) — this method applies only the explicit filters
        passed in, corresponding to the query parameters documented in
        API-ADD Section 13.

        Args:
            status: Restrict to this lifecycle status, if provided.
            request_type: Restrict to this request type, if provided.
            department: Restrict to this department, if provided.
            requester_id: Restrict to requests submitted by this user, if
                provided.
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
        builder = self._query()
        if status is not None:
            builder = builder.eq("status", status.value)
        if request_type is not None:
            builder = builder.eq("request_type", request_type)
        if department is not None:
            builder = builder.eq("department", department)
        if requester_id is not None:
            builder = builder.eq("requester_id", str(requester_id))
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
        include_deleted: bool = False,
        page: Page = Page(),
    ) -> PagedResult[RequestRecord]:
        """Free-text search across ``title`` and ``description``.

        Corresponds to ``GET /api/v1/requests/search`` (API-ADD Section
        19.3.6), which the API-ADD specifies as the same underlying
        operation as ``list_requests`` with a text filter rather than a
        separate resource.

        Args:
            query_text: The search term. Matched case-insensitively
                against both ``title`` and ``description``.
            include_deleted: Whether to include soft-deleted requests.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching requests, newest first.

        Raises:
            InvalidQueryError: If ``query_text`` is empty or whitespace-only.
        """
        if not query_text or not query_text.strip():
            raise InvalidQueryError("search_requests requires a non-empty query_text.")
        pattern = f"%{query_text.strip()}%"
        builder = self._query().or_(f"title.ilike.{pattern},description.ilike.{pattern}")
        if not include_deleted:
            builder = builder.is_("deleted_at", "null")
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_request_row)