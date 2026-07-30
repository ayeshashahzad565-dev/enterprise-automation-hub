"""The Escalation Check job.

Per WEDD Section 8.3, this job discovers overdue, still-pending workflow
stages and enqueues an ``escalate_stage`` job (via ``JobDispatcher``) for
each one that is genuinely eligible, continuing past any individual
stage's enqueue failure. Per this package's design brief, no workflow
decision logic lives here — eligibility is determined entirely by
``app.workflow.WorkflowEngine``'s own pure ``is_stage_escalation_eligible``
function, and the actual reassignment transaction is entirely
``app.jobs.handlers.handle_escalate_stage``'s (via ``ApprovalService.
escalate_stage``) responsibility, now executed by a worker process (or,
when Redis is not configured, synchronously by ``JobDispatcher``'s
in-process fallback — see ``app.jobs.job_service.SynchronousJobDispatcher``)
rather than inline in this job.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.request_repository import RequestRepository
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
    WorkflowStageRecord,
)
from app.jobs.job_service import JobDispatcher
from app.jobs.task_types import TASK_ESCALATE_STAGE
from app.models import WorkflowDefinition
from app.models.enums import JobPriority
from app.scheduler.interfaces import ExecutionContext
from app.scheduler.jobs import BaseJob, iter_pending_stages, load_stage_context, run_over_items
from app.workflow.engine import WorkflowEngine

__all__ = ["EscalationJob"]

#: A stale escalation attempt has diminishing value the further it drifts
#: from this job's own discovery query — a smaller budget than the
#: system-wide default (``JOB_DEFAULT_MAX_ATTEMPTS``) is deliberate.
_ESCALATE_STAGE_MAX_ATTEMPTS = 3


class EscalationJob(BaseJob):
    """Discovers, and enqueues the escalation of, overdue pending workflow stages.

    This job performs no persistence directly beyond the read queries
    needed for discovery (``ApprovalRepository``, ``RequestRepository``,
    ``WorkflowDefinitionRepository``) — the actual escalation write is
    delegated entirely to a job dispatched through ``JobDispatcher``.
    """

    def __init__(
        self,
        *,
        job_dispatcher: JobDispatcher,
        approval_repo: ApprovalRepository,
        request_repo: RequestRepository,
        workflow_definition_repo: WorkflowDefinitionRepository,
        workflow_engine: WorkflowEngine,
        interval_seconds: int = 3600,
    ) -> None:
        """Initialize the job with its injected collaborators.

        Args:
            job_dispatcher: Used to enqueue the actual escalation
                reassignment (WEDD Section 8.5) — either durably, for a
                separate worker to execute, or synchronously in-process
                when Redis is not configured (see ``JobDispatcher``'s
                docstring).
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
        self._job_dispatcher = job_dispatcher
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

        # One definition cache per run, shared across every candidate
        # stage below — most stages in a single run share a small number
        # of distinct pinned workflow definitions (one per request
        # type/version in active use), so this avoids re-fetching a
        # definition already resolved for an earlier stage in this batch.
        definition_cache: dict[UUID, WorkflowDefinition] = {}
        result = run_over_items(
            candidates,
            lambda stage: self._evaluate_and_escalate_if_eligible(
                stage, definition_cache=definition_cache
            ),
            job_logger=self._logger,
        )
        return result.processed_count, result.failed_count

    def _evaluate_and_escalate_if_eligible(
        self, stage: WorkflowStageRecord, *, definition_cache: dict[UUID, WorkflowDefinition]
    ) -> None:
        """Evaluate a single stage's escalation eligibility and act on it.

        Args:
            stage: The candidate stage.
            definition_cache: This run's shared workflow-definition cache
                — see ``load_stage_context``'s own docstring.

        Raises:
            RecordNotFoundError: If the stage's request or workflow
                definition can no longer be resolved.
            StageNotFoundInDefinitionError: If the stage's own order does
                not appear in its pinned definition.
            Exception: If enqueuing the ``escalate_stage`` job itself
                fails (a durable-record write failure, not an eventual
                execution failure — a concurrent human decision, for
                example, is a possible *execution*-time outcome, handled
                entirely by ``app.jobs.handlers.handle_escalate_stage``
                once the job actually runs, not by this discovery step).
        """
        stage_context = load_stage_context(
            stage,
            request_repo=self._request_repo,
            workflow_definition_repo=self._workflow_definition_repo,
            definition_cache=definition_cache,
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

        self._job_dispatcher.enqueue(
            task_type=TASK_ESCALATE_STAGE,
            queue_name="escalation",
            payload={"stage_id": str(stage.id)},
            priority=JobPriority.HIGH,
            max_attempts=_ESCALATE_STAGE_MAX_ATTEMPTS,
            request_id=stage.request_id,
        )
