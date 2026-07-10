"""Repository for the ``workflow_definitions`` and ``workflow_stages`` tables.

Per DSD Sections 3.2 and 3.4, and WEDD Section 2.1, this module serves the
Workflow Engine's structural needs: resolving and versioning workflow
definitions, and generating/reading the ordered stage sequence for a given
request. It defines the ``StageStatus`` enum (imported by
``approval_repository`` wherever a stage's decision status needs to be
referenced) and two repository classes:

- ``WorkflowDefinitionRepository`` — definitions and their versioning
  lifecycle (creation, activation).
- ``WorkflowStageRepository`` — stage generation and read access.

Decision-specific *mutations* of a stage (approve, reject, escalate) live
in ``approval_repository.py``, not here, matching the WEDD's own
separation between the Workflow Engine's stage-generation responsibility
and the Approval Engine's decision-processing responsibility (WEDD
Sections 2.1 and 6.1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.exceptions import ConcurrentUpdateError, InvalidQueryError
from app.database.repositories.base_repository import (
    BaseRepository,
    Page,
    PagedResult,
    parse_datetime,
    parse_uuid,
)
from app.database.repositories.user_repository import UserRole

logger = logging.getLogger(__name__)


class StageStatus(str, Enum):
    """The four values fixed by DSD Section 1.5's ``stage_status`` enum."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class WorkflowDefinitionRecord:
    """An immutable, persistence-level representation of one
    ``workflow_definitions`` row (DSD Section 3.2).

    Attributes:
        id: Primary key.
        request_type: The request type this definition governs.
        version: The business-level, monotonically increasing version
            number for this ``request_type`` (distinct from
            ``row_version`` below).
        definition: The structured JSON document describing stages and
            assignment rules (DSD Section 5, WEDD Section 3).
        is_active: Whether this version currently governs new requests of
            this type.
        created_by: The administrator who authored this version.
        row_version: The optimistic-locking column for this table (DSD
            Section 3.9), distinct from the business ``version`` field
            above.
        created_at: Record creation timestamp.
    """

    id: UUID
    request_type: str
    version: int
    definition: dict[str, Any]
    is_active: bool
    created_by: UUID
    row_version: int
    created_at: datetime


def _map_workflow_definition_row(row: dict[str, Any]) -> WorkflowDefinitionRecord:
    """Map a raw Supabase row dict into a ``WorkflowDefinitionRecord``."""
    return WorkflowDefinitionRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        request_type=row["request_type"],
        version=row["version"],
        definition=row["definition"],
        is_active=row["is_active"],
        created_by=parse_uuid(row["created_by"]),  # type: ignore[arg-type]
        row_version=row["row_version"],
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


@dataclass(frozen=True, slots=True)
class WorkflowStageRecord:
    """An immutable, persistence-level representation of one
    ``workflow_stages`` row (DSD Section 3.4).

    Attributes:
        id: Primary key.
        request_id: The request this stage belongs to.
        stage_order: 1-indexed position within the approval chain.
        stage_name: Human-readable stage label.
        assigned_role: The role eligible to act on this stage, if not
            assigned to a specific user.
        assigned_to: The specific user assigned to this stage, if resolved.
        status: The stage's current decision status.
        decided_by: The user who made the decision, if any.
        decided_at: The decision timestamp, if any.
        decision_note: An optional note provided at decision time.
        version: Optimistic-locking row version.
        created_at: Stage creation timestamp.
    """

    id: UUID
    request_id: UUID
    stage_order: int
    stage_name: str
    assigned_role: UserRole | None
    assigned_to: UUID | None
    status: StageStatus
    decided_by: UUID | None
    decided_at: datetime | None
    decision_note: str | None
    version: int
    created_at: datetime


def _map_workflow_stage_row(row: dict[str, Any]) -> WorkflowStageRecord:
    """Map a raw Supabase row dict into a ``WorkflowStageRecord``."""
    assigned_role = row.get("assigned_role")
    return WorkflowStageRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        request_id=parse_uuid(row["request_id"]),  # type: ignore[arg-type]
        stage_order=row["stage_order"],
        stage_name=row["stage_name"],
        assigned_role=UserRole(assigned_role) if assigned_role else None,
        assigned_to=parse_uuid(row.get("assigned_to")),
        status=StageStatus(row["status"]),
        decided_by=parse_uuid(row.get("decided_by")),
        decided_at=parse_datetime(row.get("decided_at")),
        decision_note=row.get("decision_note"),
        version=row["version"],
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


class WorkflowDefinitionRepository(BaseRepository[WorkflowDefinitionRecord]):
    """Persistence operations for the ``workflow_definitions`` table.

    Corresponds to the Workflow Engine's ``DefinitionResolver`` (WEDD
    Section 2.1) and the workflow-definition management endpoints in
    API-ADD Section 19.9.
    """

    table_name = "workflow_definitions"

    def __init__(self, client: DatabaseClient) -> None:
        super().__init__(client)

    def get_by_id(self, definition_id: UUID) -> WorkflowDefinitionRecord:  # type: ignore[override]
        """Fetch a workflow definition by its id.

        Args:
            definition_id: The definition's ``id``.

        Returns:
            The matching ``WorkflowDefinitionRecord``.

        Raises:
            RecordNotFoundError: If no definition with this id exists.
        """
        return super().get_by_id(definition_id, mapper=_map_workflow_definition_row)

    def find_active_for_request_type(
        self, request_type: str
    ) -> WorkflowDefinitionRecord | None:
        """Resolve the single active definition for a request type.

        This is the exact operation ``DefinitionResolver`` performs at
        request-submission time (WEDD Section 5.3), using the partial
        index on ``is_active`` (DSD Section 10.1) to keep this a
        near-constant-time lookup.

        Args:
            request_type: The request type to resolve.

        Returns:
            The active ``WorkflowDefinitionRecord`` for this request
            type, or ``None`` if no version is currently active — the
            trigger for API-ADD's ``422 INVALID_REQUEST_TYPE``, raised at
            the Application Layer, not by this repository.
        """
        response = self._execute(
            self._query()
            .select("*")
            .eq("request_type", request_type)
            .eq("is_active", True)
            .limit(1),
            operation="find_active_for_request_type",
        )
        rows = self._rows(response)
        return _map_workflow_definition_row(rows[0]) if rows else None

    def create_definition(
        self,
        *,
        request_type: str,
        version: int,
        definition: dict[str, Any],
        created_by: UUID,
    ) -> WorkflowDefinitionRecord:
        """Insert a new, inactive workflow definition version.

        Corresponds to ``POST /api/v1/workflow-definitions`` (API-ADD
        Section 19.9.1). The new row always has ``is_active = false``
        (WEDD Section 9.1); activation is a separate operation
        (``activate_definition``).

        Args:
            request_type: The request type this definition governs.
            version: The business version number for this request type.
                Uniqueness of ``(request_type, version)`` is enforced by
                the database (DSD Section 3.2).
            definition: The structured JSON document (already validated
                by the Application Layer per WEDD Section 13.1 before
                this method is called).
            created_by: The administrator authoring this version.

        Returns:
            The newly created ``WorkflowDefinitionRecord``.

        Raises:
            ConstraintViolationError: If ``(request_type, version)`` is
                not unique, or ``created_by`` does not resolve to an
                existing profile.
        """
        values: dict[str, Any] = {
            "request_type": request_type,
            "version": version,
            "definition": definition,
            "is_active": False,
            "created_by": str(created_by),
        }
        return self.insert(values, mapper=_map_workflow_definition_row)

    def update_inactive_definition(
        self,
        definition_id: UUID,
        *,
        expected_row_version: int,
        definition: dict[str, Any],
    ) -> WorkflowDefinitionRecord:
        """Edit a definition that has not yet been activated.

        Corresponds to ``PATCH /api/v1/workflow-definitions/{id}``
        (API-ADD Section 19.9.2). This method does not itself verify that
        the target row is inactive — that check belongs to the
        Application Layer, since verifying it and then acting on it
        atomically is exactly what the optimistic-locking predicate below
        already provides: if the row was concurrently activated between
        the caller's read and this call, the version will have changed
        and this update is rejected.

        Args:
            definition_id: The definition's ``id``.
            expected_row_version: The ``row_version`` last observed by
                the caller.
            definition: The replacement JSON document.

        Returns:
            The updated ``WorkflowDefinitionRecord``.

        Raises:
            ConcurrentUpdateError: If ``expected_row_version`` no longer
                matches the row's current ``row_version``.
        """
        return self.update_with_optimistic_lock(
            definition_id,
            expected_version=expected_row_version,
            values={"definition": definition},
            mapper=_map_workflow_definition_row,
            version_column="row_version",
        )

    def activate_definition(
        self,
        definition_id: UUID,
        *,
        request_type: str,
        expected_row_version: int,
    ) -> WorkflowDefinitionRecord:
        """Activate a definition version, deactivating the prior active version.

        Corresponds to ``POST /api/v1/workflow-definitions/{id}/activate``
        (API-ADD Section 19.9.3) and the atomic transaction specified in
        DSD Section 11 ("Workflow definition activation") and WEDD
        Section 9.2. This method performs both halves of that transaction
        — deactivating whichever row is currently active for
        ``request_type`` (if any, and if it is not the target row itself)
        and activating the target row — and the caller (the orchestrating
        Application Service) is responsible for wrapping both calls in a
        single database transaction at the connection level.

        Args:
            definition_id: The definition's ``id`` to activate.
            request_type: The request type this definition governs, used
                to locate the currently active version to deactivate.
            expected_row_version: The ``row_version`` last observed by the
                caller for the target row.

        Returns:
            The newly activated ``WorkflowDefinitionRecord``.

        Raises:
            ConcurrentUpdateError: If ``expected_row_version`` no longer
                matches the target row's current ``row_version`` — for
                example, because a competing activation already
                succeeded (API-ADD's ``409 DUPLICATE_ACTIVATION``).
        """
        current_active = self.find_active_for_request_type(request_type)
        if current_active is not None and current_active.id != definition_id:
            self._execute(
                self._query()
                .update({"is_active": False, "row_version": current_active.row_version + 1})
                .eq("id", str(current_active.id))
                .eq("row_version", current_active.row_version),
                operation="deactivate_previous_definition",
            )
        return self.update_with_optimistic_lock(
            definition_id,
            expected_version=expected_row_version,
            values={"is_active": True},
            mapper=_map_workflow_definition_row,
            version_column="row_version",
        )

    def list_definitions(
        self,
        *,
        request_type: str | None = None,
        is_active: bool | None = None,
        page: Page = Page(),
    ) -> PagedResult[WorkflowDefinitionRecord]:
        """List workflow definitions, optionally filtered.

        Corresponds to ``GET /api/v1/workflow-definitions`` (API-ADD
        Section 19.9.4). Restricting non-administrators to active-only
        results is an Application Layer / RLS concern, not enforced here.

        Args:
            request_type: Restrict to this request type, if provided.
            is_active: Restrict to active or inactive definitions, if
                provided.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching definitions, newest first.
        """
        builder = self._query()
        if request_type is not None:
            builder = builder.eq("request_type", request_type)
        if is_active is not None:
            builder = builder.eq("is_active", is_active)
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_workflow_definition_row)


class WorkflowStageRepository(BaseRepository[WorkflowStageRecord]):
    """Persistence operations for the ``workflow_stages`` table.

    Corresponds to the Workflow Engine's ``StageGenerator`` (WEDD Section
    2.1) for stage creation and read access. Decision-specific mutations
    (approve/reject/escalate) live in ``ApprovalRepository``.
    """

    table_name = "workflow_stages"

    def __init__(self, client: DatabaseClient) -> None:
        super().__init__(client)

    def get_by_id(self, stage_id: UUID) -> WorkflowStageRecord:  # type: ignore[override]
        """Fetch a stage by its id.

        Args:
            stage_id: The stage's ``id``.

        Returns:
            The matching ``WorkflowStageRecord``.

        Raises:
            RecordNotFoundError: If no stage with this id exists or is
                visible under the current client's RLS context.
        """
        return super().get_by_id(stage_id, mapper=_map_workflow_stage_row)

    def create_stage(
        self,
        *,
        request_id: UUID,
        stage_order: int,
        stage_name: str,
        assigned_role: UserRole | None = None,
        assigned_to: UUID | None = None,
    ) -> WorkflowStageRecord:
        """Insert a new, pending stage row.

        Used both at request creation (WEDD Section 5.4, the first stage)
        and after an approval that advances to a further stage (WEDD
        Section 6.4). Assignment resolution (WEDD Section 7) must already
        have occurred before this method is called — this method performs
        only the insert, never assignment logic itself.

        Args:
            request_id: The request this stage belongs to.
            stage_order: The 1-indexed position of this stage within the
                approval chain. Uniqueness of ``(request_id,
                stage_order)`` is enforced by the database (DSD Section
                3.4), and ``stage_order > 0`` by a check constraint (DSD
                Section 4.1).
            stage_name: The human-readable stage label, copied from the
                workflow definition (WEDD Section 3.5).
            assigned_role: The role eligible to act on this stage, if not
                assigned to a specific user.
            assigned_to: The specific user assigned to this stage, if
                resolved.

        Returns:
            The newly created ``WorkflowStageRecord``, with
            ``status = StageStatus.PENDING``.

        Raises:
            ConstraintViolationError: If ``(request_id, stage_order)`` is
                not unique, ``stage_order <= 0``, or ``request_id``/
                ``assigned_to`` does not resolve to an existing row.
        """
        values: dict[str, Any] = {
            "request_id": str(request_id),
            "stage_order": stage_order,
            "stage_name": stage_name,
            "assigned_role": assigned_role.value if assigned_role else None,
            "assigned_to": str(assigned_to) if assigned_to else None,
            "status": StageStatus.PENDING.value,
        }
        return self.insert(values, mapper=_map_workflow_stage_row)

    def list_for_request(
        self, request_id: UUID, *, page: Page = Page(size=100)
    ) -> PagedResult[WorkflowStageRecord]:
        """List every stage for a request, in ascending stage order.

        Corresponds to ``GET /api/v1/requests/{id}/workflow`` (API-ADD
        Section 19.4.1).

        Args:
            request_id: The request's ``id``.
            page: The page to retrieve. Defaults to a page size of 100,
                since a request's full stage list is expected to be small
                and callers typically want it in a single page.

        Returns:
            A ``PagedResult`` of the request's stages, ordered by
            ``stage_order`` ascending.
        """
        builder = self._query().eq("request_id", str(request_id)).order("stage_order")
        return self.paginate(builder, page, mapper=_map_workflow_stage_row)

    def get_highest_stage_order(self, request_id: UUID) -> int:
        """Return the highest ``stage_order`` currently materialized for a request.

        Used by ``StageGenerator`` to determine the next stage's order
        value, per WEDD Section 13.2's defensive check that the next
        order is exactly one greater than the current highest.

        Args:
            request_id: The request's ``id``.

        Returns:
            The highest ``stage_order`` value among this request's
            stages, or ``0`` if no stage has been created yet.
        """
        response = self._execute(
            self._query()
            .select("stage_order")
            .eq("request_id", str(request_id))
            .order("stage_order", desc=True)
            .limit(1),
            operation="get_highest_stage_order",
        )
        rows = self._rows(response)
        return int(rows[0]["stage_order"]) if rows else 0

    def list_decided_for_request(
        self, request_id: UUID, *, page: Page = Page(size=100)
    ) -> PagedResult[WorkflowStageRecord]:
        """List only decided stages (approved, rejected, or skipped) for a request.

        Corresponds to ``GET /api/v1/requests/{id}/workflow/history``
        (API-ADD Section 19.4.3).

        Args:
            request_id: The request's ``id``.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of the request's decided stages, ordered by
            ``stage_order`` ascending.
        """
        builder = (
            self._query()
            .eq("request_id", str(request_id))
            .neq("status", StageStatus.PENDING.value)
            .order("stage_order")
        )
        return self.paginate(builder, page, mapper=_map_workflow_stage_row)