"""Shared job infrastructure: the base job class and common discovery helpers.

Per this package's design brief, every concrete job (``EscalationJob``,
``ReminderJob``, ``HealthCheckJob``) shares the same execution-timing,
error-handling, and result-construction discipline. Rather than
duplicate that discipline three times, it is implemented exactly once
here, in ``BaseJob``, which every concrete job extends and only
implements its own ``_execute`` method against.

This module also centralizes two small, cross-job discovery helpers used
by both ``EscalationJob`` and ``ReminderJob`` — iterating every currently
pending workflow stage, and resolving a specific stage's own workflow
definition and configured ``escalation_hours`` — so that neither job
duplicates the other's data-loading logic.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator
from uuid import uuid4

from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.base_repository import Page
from app.database.repositories.request_repository import RequestRecord, RequestRepository
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
    WorkflowStageRecord,
)
from app.models import StageDefinition
from app.services.workflow_definition_service import map_workflow_definition_record_to_domain
from app.utils.datetime_utils import utc_now
from app.workflow.exceptions import StageNotFoundInDefinitionError

from app.scheduler.interfaces import ExecutionContext, ExecutionResult

__all__ = ["BaseJob", "StageContext", "ItemBatchResult", "iter_pending_stages", "load_stage_context"]

logger = logging.getLogger(__name__)

#: The default page size used when paging through candidate stages.
_DEFAULT_PAGE_SIZE = 100

#: The default maximum number of pages a single job execution will
#: consume, bounding worst-case work per tick so a very large pending
#: backlog cannot make one job execution run indefinitely.
_DEFAULT_MAX_PAGES = 50


class BaseJob(ABC):
    """Abstract base class providing the shared execution discipline every
    concrete job in this package uses.

    Concrete subclasses implement only ``_execute``, which performs the
    job's own discovery-and-processing logic and returns an
    ``(items_processed, items_failed)`` pair. ``run`` wraps that call
    with timing, structured logging, and translation of any escaping
    exception into a failed ``ExecutionResult`` — a concrete job's
    ``_execute`` is never required to catch a job-level (as opposed to
    per-item) failure itself.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """A short, stable, unique identifier for this job."""
        raise NotImplementedError

    @property
    @abstractmethod
    def interval_seconds(self) -> int:
        """The interval, in seconds, this job should be executed at."""
        raise NotImplementedError

    @abstractmethod
    def _execute(self, context: ExecutionContext) -> tuple[int, int]:
        """Perform this job's own discovery-and-processing logic.

        Args:
            context: The execution context for this run.

        Returns:
            A tuple of ``(items_processed, items_failed)``, where
            ``items_failed`` counts individual work items that failed
            without aborting the remainder of the batch — a job-level
            failure (the discovery query itself failing, for example)
            should be raised as an exception here, which ``run`` will
            catch and translate into a failed ``ExecutionResult``.
        """
        raise NotImplementedError

    def run(self, context: ExecutionContext) -> ExecutionResult:
        """Execute this job once, with timing and error translation.

        Args:
            context: The execution context for this run.

        Returns:
            The outcome of this execution. This method never raises: a
            job-level exception from ``_execute`` is caught and reported
            as a failed ``ExecutionResult`` instead.
        """
        logger_ = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")
        started_at = utc_now()
        logger_.info(
            "Starting job '%s' (run_id=%s)",
            self.name,
            context.run_id,
            extra={"job_name": self.name, "run_id": context.run_id},
        )

        try:
            items_processed, items_failed = self._execute(context)
        except Exception as exc:  # noqa: BLE001 - translated into a failed ExecutionResult
            finished_at = utc_now()
            logger_.error(
                "Job '%s' failed (run_id=%s): %s",
                self.name,
                context.run_id,
                exc,
                exc_info=exc,
                extra={"job_name": self.name, "run_id": context.run_id},
            )
            return ExecutionResult(
                job_name=self.name,
                started_at=started_at,
                finished_at=finished_at,
                success=False,
                error_message=str(exc),
            )

        finished_at = utc_now()
        logger_.info(
            "Completed job '%s' (run_id=%s): processed=%d, failed=%d, duration=%.3fs",
            self.name,
            context.run_id,
            items_processed,
            items_failed,
            (finished_at - started_at).total_seconds(),
            extra={
                "job_name": self.name,
                "run_id": context.run_id,
                "items_processed": items_processed,
                "items_failed": items_failed,
            },
        )
        return ExecutionResult(
            job_name=self.name,
            started_at=started_at,
            finished_at=finished_at,
            success=True,
            items_processed=items_processed,
            items_failed=items_failed,
        )


@dataclass(frozen=True, slots=True)
class ItemBatchResult:
    """The outcome of processing a batch of individual work items.

    Attributes:
        processed_count: The number of items successfully processed.
        failed_count: The number of items that raised during processing.
    """

    processed_count: int
    failed_count: int


def run_over_items(items, action, *, job_logger: logging.Logger) -> ItemBatchResult:
    """Process a sequence of items, continuing past any individual failure.

    Shared by ``EscalationJob`` and ``ReminderJob`` to realize the
    "continues processing remaining items if one fails" requirement
    identically in both, rather than each job re-implementing the same
    try/except-per-item loop.

    Args:
        items: The items to process, in order.
        action: A callable invoked once per item. May raise; a raised
            exception is caught, logged, and counted as a failure for
            that item only.
        job_logger: The logger to record per-item failures against.

    Returns:
        An ``ItemBatchResult`` summarizing how many items succeeded and
        how many failed.
    """
    processed = 0
    failed = 0
    for item in items:
        try:
            action(item)
        except Exception as exc:  # noqa: BLE001 - intentional: one item's failure must not abort the batch
            failed += 1
            job_logger.warning(
                "Failed to process item %r: %s", item, exc, exc_info=exc
            )
        else:
            processed += 1
    return ItemBatchResult(processed_count=processed, failed_count=failed)


def iter_pending_stages(
    approval_repo: ApprovalRepository,
    *,
    page_size: int = _DEFAULT_PAGE_SIZE,
    max_pages: int = _DEFAULT_MAX_PAGES,
) -> Iterator[WorkflowStageRecord]:
    """Iterate every currently pending workflow stage, in bounded pages.

    Uses ``ApprovalRepository.list_overdue_stages`` with a cutoff of "now"
    as a broad candidate query — since every already-persisted stage's
    ``created_at`` is necessarily at or before the current instant, this
    returns every currently pending stage rather than a narrower
    "overdue" subset. Callers (``EscalationJob``, ``ReminderJob``) apply
    their own precise, per-stage threshold logic against each yielded
    stage via the Workflow Engine, per WEDD Section 8.2's "compute the
    threshold on demand" design. No repository method exists to query
    "stages nearing or past an arbitrary, per-stage threshold" directly,
    since a stage's threshold depends on its own workflow definition's
    configuration, not a single system-wide value this query could filter
    on server-side.

    Args:
        approval_repo: The repository to query.
        page_size: The number of stages to fetch per page.
        max_pages: The maximum number of pages to fetch in a single call,
            bounding worst-case work against a very large pending
            backlog.

    Yields:
        Every currently pending ``WorkflowStageRecord``, up to
        ``page_size * max_pages`` stages.
    """
    cutoff = utc_now()
    page_number = 1
    while page_number <= max_pages:
        result = approval_repo.list_overdue_stages(
            created_before=cutoff, page=Page(number=page_number, size=page_size)
        )
        if not result.items:
            return
        yield from result.items
        if page_number >= result.total_pages:
            return
        page_number += 1


@dataclass(frozen=True, slots=True)
class StageContext:
    """The resolved request and stage-definition context for a single
    workflow stage, used to determine its escalation threshold and to
    build human-readable notification content.

    Attributes:
        request: The stage's parent request record.
        stage_definition: The corresponding entry in the request's
            pinned workflow definition (WEDD Section 9.6 — always
            resolved via ``request.workflow_definition_id``, never a
            freshly re-resolved active definition).
    """

    request: RequestRecord
    stage_definition: StageDefinition


def load_stage_context(
    stage: WorkflowStageRecord,
    *,
    request_repo: RequestRepository,
    workflow_definition_repo: WorkflowDefinitionRepository,
) -> StageContext:
    """Resolve a stage's parent request and its own workflow definition entry.

    Args:
        stage: The stage to resolve context for.
        request_repo: Persistence for ``requests``.
        workflow_definition_repo: Persistence for ``workflow_definitions``.

    Returns:
        The resolved ``StageContext``.

    Raises:
        RecordNotFoundError: If the stage's request or its pinned
            workflow definition no longer exists.
        StageNotFoundInDefinitionError: If the stage's own
            ``stage_order`` does not correspond to any entry in its
            pinned workflow definition — a defensive check against data
            inconsistency, since this should never occur in correctly
            operating production code.
    """
    request = request_repo.get_by_id(stage.request_id)
    definition_record = workflow_definition_repo.get_by_id(request.workflow_definition_id)
    definition_domain = map_workflow_definition_record_to_domain(definition_record)

    matching = [
        stage_def
        for stage_def in definition_domain.definition.stages
        if stage_def.order == stage.stage_order
    ]
    if not matching:
        raise StageNotFoundInDefinitionError(stage.stage_order)

    return StageContext(request=request, stage_definition=matching[0])