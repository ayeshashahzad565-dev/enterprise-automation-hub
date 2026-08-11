"""Repository for the ``workflow_definitions`` and ``workflow_stages`` tables.

Per DSD Sections 3.2 and 3.4, and WEDD Section 2.1, this module serves the
Workflow Engine's structural needs: resolving and versioning workflow
definitions, and generating/reading the ordered stage sequence for a given
request. ``StageStatus`` is re-exported here from ``app.models.enums``
(the single canonical definition, per DSD Section 1.5) purely for
backward compatibility with existing call sites that import it from this
module (``approval_repository`` does), alongside two repository classes:

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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.exceptions import InvalidQueryError, RecordNotFoundError
from app.database.repositories.base_repository import (
    BaseRepository,
    Page,
    PagedResult,
    escape_ilike_special_characters,
    parse_datetime,
    parse_uuid,
)
from app.models.enums import StageStatus, UserRole

logger = logging.getLogger(__name__)

__all__ = [
    "StageStatus",
    "UserRole",
    "WorkflowDefinitionRecord",
    "WorkflowStageRecord",
    "WorkflowDefinitionRepository",
    "WorkflowStageRepository",
]


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
        created_by: The administrator who authored this version, or
            ``None`` if that profile has since been hard-deleted
            (``workflow_definitions.created_by`` is ``ON DELETE SET
            NULL`` against ``profiles.id`` — ``0020_profile_lifecycle``).
        row_version: The optimistic-locking column for this table (DSD
            Section 3.9), distinct from the business ``version`` field
            above.
        created_at: Record creation timestamp.
        company_id: The company (tenant) this definition belongs to.
    """

    id: UUID
    request_type: str
    version: int
    definition: dict[str, Any]
    is_active: bool
    created_by: UUID | None
    row_version: int
    created_at: datetime
    company_id: UUID


def _map_workflow_definition_row(row: dict[str, Any]) -> WorkflowDefinitionRecord:
    """Map a raw Supabase row dict into a ``WorkflowDefinitionRecord``."""
    return WorkflowDefinitionRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        request_type=row["request_type"],
        version=row["version"],
        definition=row["definition"],
        is_active=row["is_active"],
        created_by=parse_uuid(row.get("created_by")),
        row_version=row["row_version"],
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
        company_id=parse_uuid(row["company_id"]),  # type: ignore[arg-type]
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
        company_id: The company (tenant) this stage belongs to,
            denormalized from the parent request — needed because
            ``ApprovalRepository.list_pending_for_approver``/
            ``list_overdue_stages`` query stages directly, with no
            ``request_id`` in hand to join through.
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
    company_id: UUID


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
        company_id=parse_uuid(row["company_id"]),  # type: ignore[arg-type]
    )


class WorkflowDefinitionRepository(BaseRepository[WorkflowDefinitionRecord]):
    """Persistence operations for the ``workflow_definitions`` table.

    Corresponds to the Workflow Engine's ``DefinitionResolver`` (WEDD
    Section 2.1) and the workflow-definition management endpoints in
    API-ADD Section 19.9.
    """

    table_name = "workflow_definitions"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

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

    def get_by_id_for_company(
        self, definition_id: UUID, *, company_id: UUID
    ) -> WorkflowDefinitionRecord:
        """Fetch a workflow definition by its id, scoped to a company.

        The tenant-safe counterpart to ``get_by_id``: a definition
        belonging to a different company is reported exactly as if it
        did not exist, rather than returned for the caller to check
        itself — so a service method using this method structurally
        cannot forget the cross-tenant check ``get_by_id`` alone leaves
        up to each call site.

        Args:
            definition_id: The definition's ``id``.
            company_id: The company (tenant) the definition must belong
                to.

        Returns:
            The matching ``WorkflowDefinitionRecord``.

        Raises:
            RecordNotFoundError: If no definition with this id exists,
                or it exists but belongs to a different company.
        """
        record = self.get_by_id(definition_id)
        if record.company_id != company_id:
            raise RecordNotFoundError("workflow_definition", definition_id)
        return record

    def list_by_ids(
        self, definition_ids: Sequence[UUID], *, company_id: UUID, page: Page = Page(size=100)
    ) -> PagedResult[WorkflowDefinitionRecord]:
        """Bulk-resolve a set of definition ids to their records, in one query.

        Used by ``OperationalAnalyticsEngine._resolve_definitions`` to
        resolve every distinct workflow definition referenced by a batch
        of stages with a single fetch per page, rather than one
        ``get_by_id`` call per definition id — matching the same
        bulk-resolution pattern ``RequestRepository.list_requests``'s
        ``request_ids`` filter already provides for requests.

        Args:
            definition_ids: The definition ids to resolve. An empty
                sequence returns an empty result without issuing a query.
            company_id: Restricts results to this company (tenant) —
                required, never optional.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of the matching definitions.
        """
        if not definition_ids:
            return PagedResult(items=[], page=page.number, page_size=page.size, total_records=0)
        builder = (
            self._select("*", count="exact")
            .eq("company_id", str(company_id))
            .in_("id", [str(i) for i in definition_ids])
        )
        return self.paginate(builder, page, mapper=_map_workflow_definition_row)

    def find_active_for_request_type(
        self, request_type: str, *, company_id: UUID
    ) -> WorkflowDefinitionRecord | None:
        """Resolve the single active definition for a request type, within a company.

        This is the exact operation ``DefinitionResolver`` performs at
        request-submission time (WEDD Section 5.3), using the partial
        index on ``(company_id, request_type) where is_active`` (DSD
        Section 10.1) to keep this a near-constant-time lookup.

        Args:
            request_type: The request type to resolve.
            company_id: The company (tenant) to resolve within — required,
                never optional, so a caller can never accidentally
                resolve a definition belonging to another company.

        Returns:
            The active ``WorkflowDefinitionRecord`` for this request
            type within this company, or ``None`` if no version is
            currently active — the trigger for API-ADD's ``422
            INVALID_REQUEST_TYPE``, raised at the Application Layer, not
            by this repository.
        """
        response = self._execute(
            self._query()
            .select("*")
            .eq("request_type", request_type)
            .eq("company_id", str(company_id))
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
        company_id: UUID,
    ) -> WorkflowDefinitionRecord:
        """Insert a new, inactive workflow definition version.

        Corresponds to ``POST /api/v1/workflow-definitions`` (API-ADD
        Section 19.9.1). The new row always has ``is_active = false``
        (WEDD Section 9.1); activation is a separate operation
        (``activate_definition``).

        Args:
            request_type: The request type this definition governs.
            version: The business version number for this request type.
                Uniqueness of ``(company_id, request_type, version)`` is
                enforced by the database (DSD Section 3.2).
            definition: The structured JSON document (already validated
                by the Application Layer per WEDD Section 13.1 before
                this method is called).
            created_by: The administrator authoring this version.
            company_id: The company (tenant) this definition belongs to —
                always the caller's own ``identity.company_id``.

        Returns:
            The newly created ``WorkflowDefinitionRecord``.

        Raises:
            ConstraintViolationError: If ``(company_id, request_type,
                version)`` is not unique, or ``created_by`` does not
                resolve to an existing profile.
        """
        values: dict[str, Any] = {
            "request_type": request_type,
            "version": version,
            "definition": definition,
            "is_active": False,
            "created_by": str(created_by),
            "company_id": str(company_id),
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

    def delete_inactive_definition(self, definition_id: UUID, *, company_id: UUID) -> None:
        """Hard-delete a workflow definition that has not been activated.

        The ``is_active = False`` predicate is applied in the delete
        itself (not checked as a separate read-then-delete step) as a
        defense-in-depth backstop to the Application Layer's own
        ``WorkflowEngine.validate_definition_edit`` check — an active
        definition can never be removed by this method even if that
        check were somehow bypassed. ``company_id`` is scoped the same
        way, so one company can never delete another's definition even
        if it somehow learns the id.

        Args:
            definition_id: The definition's ``id``.
            company_id: The company (tenant) the definition must belong
                to.

        Raises:
            RecordNotFoundError: If no inactive definition with this id
                exists for this company.
        """
        response = self._execute(
            self._query()
            .delete()
            .eq("id", str(definition_id))
            .eq("company_id", str(company_id))
            .eq("is_active", False),
            operation="delete_inactive_definition",
        )
        if not self._rows(response):
            raise RecordNotFoundError(self.table_name, definition_id)

    def activate_definition(
        self,
        definition_id: UUID,
        *,
        request_type: str,
        expected_row_version: int,
        company_id: UUID,
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
        current_active = self.find_active_for_request_type(request_type, company_id=company_id)
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
        company_id: UUID,
        request_type: str | None = None,
        is_active: bool | None = None,
        page: Page = Page(),
    ) -> PagedResult[WorkflowDefinitionRecord]:
        """List workflow definitions within a company, optionally filtered.

        Corresponds to ``GET /api/v1/workflow-definitions`` (API-ADD
        Section 19.9.4). Restricting non-administrators to active-only
        results is an Application Layer / RLS concern, not enforced here.

        Args:
            company_id: Restricts results to this company (tenant) —
                required, never optional.
            request_type: Restrict to this request type, if provided.
            is_active: Restrict to active or inactive definitions, if
                provided.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching definitions, newest first.
        """
        builder = self._select("*", count="exact").eq("company_id", str(company_id))
        if request_type is not None:
            builder = builder.eq("request_type", request_type)
        if is_active is not None:
            builder = builder.eq("is_active", is_active)
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_workflow_definition_row)

    def search_definitions(
        self,
        query_text: str,
        *,
        company_id: UUID,
        is_active: bool | None = None,
        page: Page = Page(),
    ) -> PagedResult[WorkflowDefinitionRecord]:
        """Free-text search across request types.

        Unlike ``list_definitions``, which requires an exact
        ``request_type`` to browse one type's version history, this
        matches ``request_type`` case-insensitively as a substring —
        the definition's own JSON document is not searched.

        Args:
            query_text: The search term.
            is_active: Restrict to active or inactive definitions, if
                provided — used by ``GlobalSearchService`` to restrict a
                non-administrator caller to active definitions only,
                mirroring ``WorkflowDefinitionService.list_versions``'s
                identical rule.
            page: The page to retrieve, newest first.

        Returns:
            A ``PagedResult`` of matching definitions.

        Raises:
            InvalidQueryError: If ``query_text`` is empty or whitespace-only.
        """
        if not query_text or not query_text.strip():
            raise InvalidQueryError("search_definitions requires a non-empty query_text.")
        pattern = f"%{escape_ilike_special_characters(query_text.strip())}%"
        builder = (
            self._select("*", count="exact")
            .ilike("request_type", pattern)
            .eq("company_id", str(company_id))
        )
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

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

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

    def get_by_id_for_company(self, stage_id: UUID, *, company_id: UUID) -> WorkflowStageRecord:
        """Fetch a stage by its id, scoped to a company.

        The tenant-safe counterpart to ``get_by_id`` — see
        ``WorkflowDefinitionRepository.get_by_id_for_company``'s
        docstring for the identical rationale.

        Args:
            stage_id: The stage's ``id``.
            company_id: The company (tenant) the stage must belong to.

        Returns:
            The matching ``WorkflowStageRecord``.

        Raises:
            RecordNotFoundError: If no stage with this id exists, or it
                exists but belongs to a different company.
        """
        record = self.get_by_id(stage_id)
        if record.company_id != company_id:
            raise RecordNotFoundError("workflow_stage", stage_id)
        return record

    def create_stage(
        self,
        *,
        request_id: UUID,
        stage_order: int,
        stage_name: str,
        company_id: UUID,
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
            company_id: The company (tenant) this stage belongs to —
                always copied from the parent request's own
                ``company_id`` by the calling service, never independently
                resolved.
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
            "company_id": str(company_id),
        }
        return self.insert(values, mapper=_map_workflow_stage_row)

    def delete_if_unchanged(self, stage_id: UUID, *, expected_version: int) -> bool:
        """Hard-delete a stage, but only if nothing has touched it since creation.

        The compensating counterpart to ``create_stage``, used exclusively
        by ``ApprovalService``'s ``TransactionContext`` when a later step
        in the same decision (the request-advancement update, or the audit
        write) fails after a next stage was already created — so a failed
        decision never leaves an orphaned, never-should-have-existed stage
        behind. ``workflow_stages`` has no soft-delete column (unlike
        ``requests``/``comments``), so this is a genuine ``DELETE``, not a
        tombstone — which is exactly why it is version-guarded rather than
        unconditional: in the narrow window between this stage's creation
        and the failure that triggered this rollback, another actor could
        in principle have already raced in and decided it (its version
        would then no longer match), in which case deleting it would
        destroy a genuine decision. Guarding by version turns that race
        into a safe no-op instead — the caller is expected to log when this
        returns ``False``, since it means the rest of the rollback for this
        decision is now incomplete (an inherent limitation of compensation-
        based orchestration without true database transactions, documented
        in ``docs/approval_recovery_strategy.md``).

        Args:
            stage_id: The stage's ``id``.
            expected_version: The version ``create_stage`` returned — this
                compensation only applies if nothing has touched the row
                since.

        Returns:
            ``True`` if the row was actually deleted, ``False`` if no row
            matched both ``stage_id`` and ``expected_version`` (already
            modified by something else, or already gone).
        """
        response = self._execute(
            self._query().delete().eq("id", str(stage_id)).eq("version", expected_version),
            operation="delete_if_unchanged",
        )
        return bool(self._rows(response))

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
        builder = (
            self._select("*", count="exact").eq("request_id", str(request_id)).order("stage_order")
        )
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
            self._select("*", count="exact")
            .eq("request_id", str(request_id))
            .neq("status", StageStatus.PENDING.value)
            .order("stage_order")
        )
        return self.paginate(builder, page, mapper=_map_workflow_stage_row)

    def list_decided(
        self,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        page: Page = Page(size=100),
    ) -> PagedResult[WorkflowStageRecord]:
        """List every approved-or-rejected stage within a company, newest first.

        The company-wide counterpart to ``list_decided_for_request``
        (which is scoped to one request) — added for the Operational
        Analytics Layer (Milestone 12), which needs row-level access to
        every decided stage in scope to compute approval-duration
        breakdowns (by stage, department, workflow), median approval
        time, and per-stage SLA-breach outcomes. No such broad,
        company-scoped read existed before this: ``ApprovalRepository``
        only ever queries ``status = 'pending'`` rows
        (``list_pending_for_approver``/``list_overdue_stages``). This
        mirrors ``list_overdue_stages``'s own shape and scoping
        discipline exactly, applied to the complementary "already
        decided" half of this table's rows.

        ``status in ('approved', 'rejected')`` matches
        ``AnalyticsRepository.approval_throughput``'s existing terminal-
        status filter exactly — ``StageStatus.SKIPPED`` is excluded
        because, per that enum's own docstring, no assignment strategy in
        the current baseline ever produces it.

        Args:
            company_id: Restricts results to this company (tenant) —
                required, never optional.
            created_after: Restrict to stages created at or after this
                timestamp, if provided.
            created_before: Restrict to stages created at or before this
                timestamp, if provided.
            page: The page to retrieve, newest first.

        Returns:
            A ``PagedResult`` of matching decided stages.
        """
        builder = self._scoped_query(company_id=company_id).in_(
            "status", [StageStatus.APPROVED.value, StageStatus.REJECTED.value]
        )
        if created_after is not None:
            builder = builder.gte("created_at", created_after.isoformat())
        if created_before is not None:
            builder = builder.lte("created_at", created_before.isoformat())
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_workflow_stage_row)
