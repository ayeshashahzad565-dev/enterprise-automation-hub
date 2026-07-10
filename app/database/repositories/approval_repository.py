"""Repository for decision-specific mutations on ``workflow_stages``.

This module is deliberately separate from ``workflow_repository.py``,
mirroring the WEDD's own separation (WEDD Sections 2.1 and 6.1) between
the Workflow Engine's stage-*generation* responsibility and the Approval
Engine's decision-*processing* responsibility. Every method here mutates
an existing stage's decision state (approve, reject, or escalate) under
optimistic-locking control, or serves the approver-facing and
Scheduler-facing read queries those mutations depend on.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.exceptions import ConcurrentUpdateError, InvalidQueryError
from app.database.repositories.base_repository import BaseRepository, Page, PagedResult
from app.database.repositories.user_repository import UserRole
from app.database.repositories.workflow_repository import (
    StageStatus,
    WorkflowStageRecord,
    _map_workflow_stage_row,
)

logger = logging.getLogger(__name__)


class ApprovalRepository(BaseRepository[WorkflowStageRecord]):
    """Persistence operations for deciding, escalating, and querying
    ``workflow_stages`` rows.

    Corresponds to ``ApprovalService``'s persistence needs (WEDD Section
    6) and the Scheduler's Escalation Check job (WEDD Section 8).
    """

    table_name = "workflow_stages"

    def __init__(self, client: DatabaseClient) -> None:
        super().__init__(client)

    def approve_stage(
        self,
        stage_id: UUID,
        *,
        expected_version: int,
        decided_by: UUID,
        decision_note: str | None = None,
    ) -> WorkflowStageRecord:
        """Record an approval decision under optimistic-locking control.

        Issues the conditional update specified in WEDD Section 6.2 and
        DSD Section 3.9: ``UPDATE workflow_stages SET status='approved',
        decided_by, decided_at, decision_note, version = version + 1
        WHERE id = :stage_id AND version = :expected_version``. This
        method does not verify the stage was ``pending`` beforehand, nor
        that ``decided_by`` is authorized to decide it — both are
        Application Layer guard clauses (WEDD Section 6.2, API-ADD
        Section 6.3) evaluated before this method is called. The
        optimistic-locking predicate is what makes a stale or duplicate
        call safe regardless: if the stage is no longer at
        ``expected_version`` (because it was already decided), zero rows
        are affected and a ``ConcurrentUpdateError`` is raised rather than
        overwriting the existing decision.

        Args:
            stage_id: The stage's ``id``.
            expected_version: The version last observed by the caller.
            decided_by: The user recording the decision.
            decision_note: An optional note (API-ADD Section 19.5.1).

        Returns:
            The updated ``WorkflowStageRecord``, with
            ``status = StageStatus.APPROVED``.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version — including the case
                where the stage was already decided by another approver
                or by a duplicate submission (API-ADD Section 14).
        """
        values: dict[str, Any] = {
            "status": StageStatus.APPROVED.value,
            "decided_by": str(decided_by),
            "decided_at": datetime.now().astimezone().isoformat(),
            "decision_note": decision_note,
        }
        return self.update_with_optimistic_lock(
            stage_id,
            expected_version=expected_version,
            values=values,
            mapper=_map_workflow_stage_row,
        )

    def reject_stage(
        self,
        stage_id: UUID,
        *,
        expected_version: int,
        decided_by: UUID,
        decision_note: str,
    ) -> WorkflowStageRecord:
        """Record a rejection decision under optimistic-locking control.

        Identical in mechanism to ``approve_stage``, except that
        ``decision_note`` is required here (non-empty), per WEDD Section
        6.6's business rule that a rejection must always carry a stated
        reason. This method enforces that non-emptiness directly, since
        it is intrinsic to what a valid rejection *is*, not a
        state-dependent business rule that must wait for a database
        round trip to evaluate.

        Args:
            stage_id: The stage's ``id``.
            expected_version: The version last observed by the caller.
            decided_by: The user recording the decision.
            decision_note: The required reason for rejection.

        Returns:
            The updated ``WorkflowStageRecord``, with
            ``status = StageStatus.REJECTED``.

        Raises:
            InvalidQueryError: If ``decision_note`` is empty or
                whitespace-only.
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version.
        """
        if not decision_note or not decision_note.strip():
            raise InvalidQueryError("reject_stage requires a non-empty decision_note.")
        values: dict[str, Any] = {
            "status": StageStatus.REJECTED.value,
            "decided_by": str(decided_by),
            "decided_at": datetime.now().astimezone().isoformat(),
            "decision_note": decision_note,
        }
        return self.update_with_optimistic_lock(
            stage_id,
            expected_version=expected_version,
            values=values,
            mapper=_map_workflow_stage_row,
        )

    def escalate_stage(
        self,
        stage_id: UUID,
        *,
        expected_version: int,
        new_assigned_to: UUID | None,
        new_assigned_role: UserRole,
    ) -> WorkflowStageRecord:
        """Reassign an overdue, still-pending stage (WEDD Section 8.4).

        Invoked exclusively by the Scheduler's Escalation Check job
        (WEDD Section 8.5), using the same optimistic-locking predicate
        as a human decision, so that an escalation attempt racing against
        a just-arrived human decision is safely rejected rather than
        overwriting it (WEDD Section 12.5).

        This method does not change ``status`` — a stage remains
        ``pending`` after escalation, only its assignment changes.

        Args:
            stage_id: The stage's ``id``.
            expected_version: The version last observed by the Scheduler
                job at query time.
            new_assigned_to: The new specific assignee, if resolved, or
                ``None`` if escalating to a role-eligible pool.
            new_assigned_role: The new eligible role (typically
                ``UserRole.ADMIN``, per WEDD Section 7.5's fallback and
                Section 8.4's escalation routing).

        Returns:
            The updated ``WorkflowStageRecord``, with ``status`` unchanged
            and its assignment fields updated.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version — for example, because
                a human decided the stage between the Scheduler's query
                and this reassignment attempt (WEDD Section 18.3).
        """
        values: dict[str, Any] = {
            "assigned_to": str(new_assigned_to) if new_assigned_to else None,
            "assigned_role": new_assigned_role.value,
        }
        return self.update_with_optimistic_lock(
            stage_id,
            expected_version=expected_version,
            values=values,
            mapper=_map_workflow_stage_row,
        )

    def list_pending_for_approver(
        self,
        *,
        assigned_to: UUID | None = None,
        assigned_role: UserRole | None = None,
        page: Page = Page(),
    ) -> PagedResult[WorkflowStageRecord]:
        """List pending stages assigned to a specific user or role.

        Corresponds to ``GET /api/v1/approvals/pending`` (API-ADD Section
        19.5.3), backed by the composite index on ``(assigned_to,
        status)`` (DSD Section 10.2). When called against an anon-key
        client, Row-Level Security additionally restricts results to
        stages the authenticated caller may see (DSD Section 9.2); when
        called against a service-role client (for example, by the
        Scheduler), no such restriction applies and the caller must
        supply explicit filters.

        Args:
            assigned_to: Restrict to stages assigned to this specific
                user, if provided.
            assigned_role: Restrict to stages eligible for this role, if
                provided.
            page: The page to retrieve, ordered oldest-first so the
                stages closest to escalation surface first.

        Returns:
            A ``PagedResult`` of matching pending stages.

        Raises:
            InvalidQueryError: If neither ``assigned_to`` nor
                ``assigned_role`` is provided, which would otherwise
                return every pending stage in the system unfiltered.
        """
        if assigned_to is None and assigned_role is None:
            raise InvalidQueryError(
                "list_pending_for_approver requires at least one of "
                "assigned_to or assigned_role."
            )
        builder = self._query().eq("status", StageStatus.PENDING.value)
        if assigned_to is not None:
            builder = builder.eq("assigned_to", str(assigned_to))
        if assigned_role is not None:
            builder = builder.eq("assigned_role", assigned_role.value)
        builder = builder.order("created_at")
        return self.paginate(builder, page, mapper=_map_workflow_stage_row)

    def list_overdue_stages(
        self,
        *,
        created_before: datetime,
        page: Page = Page(size=100),
    ) -> PagedResult[WorkflowStageRecord]:
        """List pending stages created before a given threshold timestamp.

        Used by the Scheduler's Escalation Check and Reminder Dispatch
        jobs (WEDD Section 8.3), which compute the threshold externally
        (from a stage's ``created_at`` plus the workflow definition's
        configured ``escalation_hours``, per WEDD Section 8.2) and pass
        it in here as an absolute timestamp — this repository performs no
        duration arithmetic itself, keeping that computation in the
        Workflow Engine's ``EscalationPlanner`` where it belongs.

        Args:
            created_before: Only stages created at or before this
                timestamp are returned.
            page: The page to retrieve. Defaults to a page size of 100 to
                efficiently batch-process a Scheduler run.

        Returns:
            A ``PagedResult`` of pending stages older than the threshold,
            oldest first.
        """
        builder = (
            self._query()
            .eq("status", StageStatus.PENDING.value)
            .lte("created_at", created_before.isoformat())
            .order("created_at")
        )
        return self.paginate(builder, page, mapper=_map_workflow_stage_row)