"""The Escalation Check job.

Per WEDD Section 8.3, this job discovers overdue, still-pending workflow
stages and invokes ``ApprovalService.escalate_stage`` for each one that
is genuinely eligible, continuing past any individual stage's failure.
Per this package's design brief, no workflow decision logic lives here —
eligibility is determined entirely by ``app.workflow.WorkflowEngine``'s
own pure ``is_stage_escalation_eligible`` function, and the actual
reassignment transaction is entirely ``ApprovalService.escalate_stage``'s
responsibility.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.request_repository import RequestRepository
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
    WorkflowStageRecord,
)
from app.models.enums import StageStatus
from app.services.approval_service import ApprovalService
from app.workflow.engine import WorkflowEngine
from app.workflow.exceptions import StageNotFoundInDefinitionError

from app.scheduler.interfaces import ExecutionContext
from app.scheduler.jobs import BaseJob, iter_pending_stages, load_stage_context, run_over_items

__all__ = ["EscalationJob"]


class EscalationJob(BaseJob):
    """Escalates overdue, still-pending workflow stages.

    This job performs no persistence directly beyond the read queries
    needed for discovery (``ApprovalRepository``, ``RequestRepository``,
    ``WorkflowDefinitionRepository``) — the actual escalation write is
    delegated entirely to ``ApprovalService.escalate_stage``.
    """

    def __init__(
        self,
        *,
        approval_service: ApprovalService,
        approval_repo: ApprovalRepository,
        request_repo: RequestRepository,
        workflow_definition_repo: WorkflowDefinitionRepository,
        workflow_engine: WorkflowEngine,
        interval_seconds: int = 3600,
    ) -> None:
        """Initialize the job with its injected collaborators.

        Args:
            approval_service: Used to perform the actual escalation
                reassignment (WEDD Section 8.5).
            approval_repo: Used for the broad pending-stage discovery
                query.
            request_repo: Used to resolve a stage's parent request.
            workflow_definition_repo: Used to resolve a stage's own
                pinned workflow definition.
            workflow_engine: The composed Workflow Engine facade, used
                for the pure escalation-eligibility check (WEDD Section
                8.2).
            interval_seconds: The default interval this job runs at.
                Defaults to one hour, matching WEDD Section 8.3's
                documented interval.
        """
        self._approval_service = approval_service
        self._approval_repo = approval_repo
        self._request_repo = request_repo
        self._workflow_definition_repo = workflow_definition_repo
        self._workflow_engine = workflow_engine
        self._interval_seconds = interval_seconds
        self._logger = logging.getLogger(f"{__name__}.EscalationJob")

    @property
    def name(self) -> str:
        """This job's stable identifier, ``"escalation_check"``."""
        return "escalation_check"

    @property
    def interval_seconds(self) -> int:
        """The configured interval, in seconds, this job runs at."""
        return self._interval_seconds

    def _execute(self, context: ExecutionContext) -> tuple[int, int]:
        """Discover and escalate every currently eligible pending stage.

        Args:
            context: The execution context for this run.

        Returns:
            A tuple of ``(items_processed, items_failed)`` across every
            pending stage considered — "processed" here means
            "successfully evaluated," which includes stages correctly
            determined *not* to be eligible yet, not only stages that
            were actually escalated.
        """
        candidates = list(iter_pending_stages(self._approval_repo))
        self._logger.info(
            "Escalation check considering %d pending stage(s)",
            len(candidates),
            extra={"candidate_count": len(candidates)},
        )

        result = run_over_items(
            candidates, self._evaluate_and_escalate_if_eligible, job_logger=self._logger
        )
        return result.processed_count, result.failed_count

    def _evaluate_and_escalate_if_eligible(self, stage: WorkflowStageRecord) -> None:
        """Evaluate a single stage's escalation eligibility and act on it.

        Args:
            stage: The candidate stage.

        Raises:
            RecordNotFoundError: If the stage's request or workflow
                definition can no longer be resolved.
            StageNotFoundInDefinitionError: If the stage's own order does
                not appear in its pinned definition.
            DatabaseError: If the escalation write itself fails for a
                reason other than a concurrent human decision (which
                ``ApprovalService.escalate_stage`` is expected to raise
                as a ``ConcurrencyError``, not swallow — see note below).
        """
        stage_context = load_stage_context(
            stage,
            request_repo=self._request_repo,
            workflow_definition_repo=self._workflow_definition_repo,
        )

        eligible = self._workflow_engine.is_stage_escalation_eligible(
            stage.created_at, stage_context.stage_definition.escalation_hours
        )
        if not eligible:
            self._logger.debug(
                "Stage %s not yet eligible for escalation (escalation_hours=%.2f)",
                stage.id,
                stage_context.stage_definition.escalation_hours,
                extra={"stage_id": str(stage.id)},
            )
            return

        try:
            self._approval_service.escalate_stage(stage.id)
        except Exception as exc:  # noqa: BLE001 - re-raised; caught by run_over_items per-item
            # A concurrency conflict here means a human decided the
            # stage between this job's query and the escalation attempt
            # — per WEDD Section 18.3, this is expected, desired behavior
            # under normal operation, not an operator-facing error. It is
            # still logged as a per-item outcome by run_over_items (at
            # WARNING level), which is an acceptable, low-noise signal
            # for this expected race, rather than requiring a separate,
            # silent-success code path here.
            self._logger.debug(
                "Escalation attempt for stage %s did not apply (likely a concurrent "
                "human decision): %s",
                stage.id,
                exc,
                extra={"stage_id": str(stage.id)},
            )
            raise