"""Application service orchestrating approval and rejection decisions.

Per the Workflow Engine Design Document (WEDD Section 6) and the API
Design Document (API-ADD Section 19.5), this service coordinates
``ApprovalRepository``, ``WorkflowStageRepository``, ``RequestRepository``,
``WorkflowDefinitionRepository``, ``ProfileRepository``,
``AuditRepository``, ``NotificationService``, and
``app.workflow.WorkflowEngine`` to implement stage approval, rejection,
and the read access approvers need for their working queue.

This service never decides whether a decision is legal on its own terms
— every check (is this caller the resolved assignee or role-eligible, is
the stage still pending, what does completion vs. advancement mean for
the request) is delegated to ``app.auth.authorization`` and
``app.workflow.WorkflowEngine`` respectively. This service's own
responsibility is strictly orchestration: fetch what those two layers
need, invoke them, persist the outcome through the Repository Layer under
optimistic-locking control, write the audit trail, and dispatch
notifications after commit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from app.auth.authentication import AuthenticatedIdentity
from app.auth.authorization import authorize_stage_decision
from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.request_repository import RequestRepository
from app.database.repositories.user_repository import ProfileRepository
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
    WorkflowStageRecord,
    WorkflowStageRepository,
)
from app.models import ApprovalOutcome, WorkflowStage
from app.models.enums import AuditAction, NotificationType, RequestStatus, StageStatus, UserRole
from app.services.exceptions import (
    PermissionDeniedError,
    ValidationError,
    translate_auth_error,
    translate_database_error,
    translate_workflow_error,
)
from app.services.notification_service import NotificationService
from app.services.request_service import map_profile_record_to_domain
from app.services.workflow_definition_service import (
    TransactionContext,
    map_workflow_definition_record_to_domain,
)
from app.utils.datetime_utils import utc_now
from app.utils.decorators import log_calls
from app.workflow.engine import WorkflowEngine
from app.workflow.exceptions import WorkflowError as EngineWorkflowError

__all__ = ["map_workflow_stage_record_to_domain", "ApprovalService"]

logger = logging.getLogger(__name__)


def map_workflow_stage_record_to_domain(record: WorkflowStageRecord) -> WorkflowStage:
    """Map a persistence-level ``WorkflowStageRecord`` into its Domain
    Layer ``WorkflowStage`` representation.

    Args:
        record: The record returned by ``WorkflowStageRepository`` or
            ``ApprovalRepository``.

    Returns:
        The corresponding ``WorkflowStage`` domain model.
    """
    return WorkflowStage(
        id=record.id,
        request_id=record.request_id,
        stage_order=record.stage_order,
        stage_name=record.stage_name,
        assigned_role=record.assigned_role,
        assigned_to=record.assigned_to,
        status=record.status,
        decided_by=record.decided_by,
        decided_at=record.decided_at,
        decision_note=record.decision_note,
        version=record.version,
        created_at=record.created_at,
    )


@dataclass(frozen=True, slots=True)
class _DecisionAdvancement:
    """The request-level consequence of a single stage decision.

    Kept as its own dataclass, rather than a plain tuple, specifically so
    that "a new stage was created" (``new_stage_id``) and "a notification
    recipient was resolved for that new stage" (``notify_recipient_id``)
    are two independently nullable fields, not conflated into one. A
    stage's assignment can legitimately resolve to a role-eligible pool
    with no specific user (``department_queue``, WEDD Section 7.3) — in
    that case a new stage still exists and ``current_stage_id`` must
    still point at it, even though there is no single recipient to
    notify.

    Attributes:
        request_status: The request's status immediately after this
            decision.
        new_stage_id: The id of the newly generated next stage, or
            ``None`` if the decision resulted in a terminal request
            status (``COMPLETED`` or ``REJECTED``) with no further stage.
        notify_recipient_id: The specific user to send an ``assignment``
            notification to for the new stage, or ``None`` if either no
            new stage was created, or the new stage's assignment
            resolved to a role-eligible pool rather than a specific user.
        audit_action: The audit action code to record for this decision.
    """

    request_status: RequestStatus
    new_stage_id: UUID | None
    notify_recipient_id: UUID | None
    audit_action: AuditAction


class ApprovalService:
    """Orchestrates approval, rejection, escalation, and pending-queue reads."""

    def __init__(
        self,
        *,
        approval_repo: ApprovalRepository,
        workflow_stage_repo: WorkflowStageRepository,
        request_repo: RequestRepository,
        workflow_definition_repo: WorkflowDefinitionRepository,
        profile_repo: ProfileRepository,
        audit_repo: AuditRepository,
        notification_service: NotificationService,
        workflow_engine: WorkflowEngine,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            approval_repo: Decision-specific mutations on
                ``workflow_stages``.
            workflow_stage_repo: Structural reads/creation on
                ``workflow_stages`` (fetching the current stage, creating
                the next one, and determining the highest existing
                order).
            request_repo: Persistence for ``requests``.
            workflow_definition_repo: Persistence for
                ``workflow_definitions``, used to fetch the specific
                version pinned to the request being advanced (never a
                freshly re-resolved active definition, per WEDD Section
                9.6).
            profile_repo: Persistence for ``profiles``.
            audit_repo: Persistence for ``audit_logs``.
            notification_service: The service used to dispatch
                post-commit notifications.
            workflow_engine: The composed Workflow Engine facade.
        """
        self._approval_repo = approval_repo
        self._workflow_stage_repo = workflow_stage_repo
        self._request_repo = request_repo
        self._workflow_definition_repo = workflow_definition_repo
        self._profile_repo = profile_repo
        self._audit_repo = audit_repo
        self._notification_service = notification_service
        self._workflow_engine = workflow_engine
        self._logger = logging.getLogger(f"{__name__}.ApprovalService")

    @log_calls()
    def approve_stage(
        self,
        identity: AuthenticatedIdentity,
        stage_id: UUID,
        *,
        expected_version: int | None = None,
        decision_note: str | None = None,
    ) -> ApprovalOutcome:
        """Approve a workflow stage, advancing or completing its request.

        Implements the full sequence specified in WEDD Section 6.2:
        authorize, decide the stage under optimistic-locking control,
        determine the next stage (or completion) via the Workflow Engine,
        persist the outcome, write the audit entry, and dispatch the
        appropriate post-commit notification.

        Args:
            identity: The authenticated approver.
            stage_id: The stage's id.
            expected_version: The version last observed by the caller. If
                omitted, the version fetched during this call's own
                pre-check read is used instead.
            decision_note: An optional note.

        Returns:
            An ``ApprovalOutcome`` describing the decided stage and the
            resulting request-level state, including ``current_stage_id``
            whenever a further stage was genuinely generated — regardless
            of whether that stage resolved to a specific assignee or a
            role-eligible pool.

        Raises:
            NotFoundError: If no stage with this id exists.
            PermissionDeniedError: If the caller is not the resolved
                assignee or role-eligible, or the stage is not pending.
            ConcurrencyError: If the stage was already decided by another
                action.
        """
        return self._decide_stage(
            identity,
            stage_id,
            target_stage_status=StageStatus.APPROVED,
            expected_version=expected_version,
            decision_note=decision_note,
        )

    @log_calls()
    def reject_stage(
        self,
        identity: AuthenticatedIdentity,
        stage_id: UUID,
        *,
        expected_version: int | None = None,
        decision_note: str,
    ) -> ApprovalOutcome:
        """Reject a workflow stage, terminating its request's workflow.

        Per WEDD Section 6.6, ``decision_note`` is required (non-empty)
        for a rejection, unlike an approval.

        Args:
            identity: The authenticated approver.
            stage_id: The stage's id.
            expected_version: The version last observed by the caller.
            decision_note: The required reason for rejection.

        Returns:
            An ``ApprovalOutcome`` describing the decided stage and the
            resulting request-level state (always ``REJECTED``).

        Raises:
            NotFoundError: If no stage with this id exists.
            PermissionDeniedError: If the caller is not the resolved
                assignee or role-eligible, or the stage is not pending.
            ValidationError: If ``decision_note`` is empty.
            ConcurrencyError: If the stage was already decided by another
                action.
        """
        if not decision_note or not decision_note.strip():
            raise ValidationError("A decision_note is required when rejecting a stage.")
        return self._decide_stage(
            identity,
            stage_id,
            target_stage_status=StageStatus.REJECTED,
            expected_version=expected_version,
            decision_note=decision_note,
        )

    @log_calls()
    def escalate_stage(self, stage_id: UUID) -> WorkflowStage:
        """Reassign an overdue, still-pending stage.

        Per WEDD Section 8.5, this method is invoked exclusively by the
        Scheduler's Escalation Check job — never by a human-facing
        endpoint — and uses the same optimistic-locking predicate as a
        human decision, so a human decision arriving concurrently always
        wins over a stale escalation attempt (WEDD Section 12.5).

        Args:
            stage_id: The stage's id.

        Returns:
            The reassigned ``WorkflowStage``.

        Raises:
            NotFoundError: If no stage with this id exists.
            ConcurrencyError: If a human decision was recorded between
                the Scheduler's query and this reassignment attempt.
        """
        try:
            stage = self._workflow_stage_repo.get_by_id(stage_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc

        plan = self._workflow_engine.plan_stage_escalation(
            current_assigned_to=stage.assigned_to, current_assigned_role=stage.assigned_role
        )

        try:
            reassigned = self._approval_repo.escalate_stage(
                stage_id,
                expected_version=stage.version,
                new_assigned_to=plan.new_assigned_to,
                new_assigned_role=plan.new_assigned_role,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        try:
            self._audit_repo.record_event(
                action=AuditAction.STAGE_ESCALATED,
                request_id=stage.request_id,
                metadata={
                    "stage_id": str(stage_id),
                    "previous_assigned_to": str(plan.previous_assigned_to)
                    if plan.previous_assigned_to
                    else None,
                    "previous_assigned_role": plan.previous_assigned_role.value
                    if plan.previous_assigned_role
                    else None,
                },
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        if reassigned.assigned_to is not None:
            self._notification_service.notify_escalation(
                recipient_id=reassigned.assigned_to,
                request_id=stage.request_id,
                message=f"Stage '{stage.stage_name}' has been escalated to you.",
            )

        return map_workflow_stage_record_to_domain(reassigned)

    @log_calls()
    def list_pending_approvals(
        self, identity: AuthenticatedIdentity, *, page: Page = Page()
    ) -> PagedResult[WorkflowStage]:
        """List stages currently awaiting the caller's decision.

        Args:
            identity: The authenticated approver or administrator.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching ``WorkflowStage`` instances.

        Raises:
            PermissionDeniedError: If the caller is an employee.
        """
        if identity.role not in (UserRole.APPROVER, UserRole.ADMIN):
            raise PermissionDeniedError(
                f"Role '{identity.role.value}' may not view the pending approvals queue."
            )

        try:
            result = self._approval_repo.list_pending_for_approver(
                assigned_to=identity.user_id, assigned_role=identity.role, page=page
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return PagedResult(
            items=[map_workflow_stage_record_to_domain(r) for r in result.items],
            page=result.page,
            page_size=result.page_size,
            total_records=result.total_records,
        )

    def _decide_stage(
        self,
        identity: AuthenticatedIdentity,
        stage_id: UUID,
        *,
        target_stage_status: StageStatus,
        expected_version: int | None,
        decision_note: str | None,
    ) -> ApprovalOutcome:
        """Shared implementation for ``approve_stage`` and ``reject_stage``.

        Args:
            identity: The authenticated approver.
            stage_id: The stage's id.
            target_stage_status: The status the stage is being decided
                to (``APPROVED`` or ``REJECTED``).
            expected_version: The version last observed by the caller.
            decision_note: The decision note, if any.

        Returns:
            The resulting ``ApprovalOutcome``.
        """
        try:
            stage = self._workflow_stage_repo.get_by_id(stage_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc

        try:
            authorize_stage_decision(
                identity,
                is_resolved_assignee=stage.assigned_to == identity.user_id,
                is_role_eligible=stage.assigned_role == identity.role,
                stage_is_pending=stage.status is StageStatus.PENDING,
            )
        except Exception as exc:  # noqa: BLE001
            raise translate_auth_error(exc) from exc

        try:
            self._workflow_engine.validate_stage_status_transition(
                stage.status, target_stage_status
            )
        except EngineWorkflowError as exc:
            raise translate_workflow_error(exc) from exc

        version_to_use = expected_version if expected_version is not None else stage.version

        with TransactionContext(operation_name=f"decide_stage_{target_stage_status.value}"):
            if target_stage_status is StageStatus.APPROVED:
                try:
                    decided_stage = self._approval_repo.approve_stage(
                        stage_id,
                        expected_version=version_to_use,
                        decided_by=identity.user_id,
                        decision_note=decision_note,
                    )
                except DatabaseError as exc:
                    raise translate_database_error(exc) from exc
                advancement = self._advance_after_approval(stage, decided_stage)
            else:
                try:
                    decided_stage = self._approval_repo.reject_stage(
                        stage_id,
                        expected_version=version_to_use,
                        decided_by=identity.user_id,
                        decision_note=decision_note or "",
                    )
                except DatabaseError as exc:
                    raise translate_database_error(exc) from exc
                advancement = self._finalize_rejection(stage)

            try:
                self._audit_repo.record_event(
                    action=advancement.audit_action,
                    actor_id=identity.user_id,
                    request_id=stage.request_id,
                    metadata={"stage_id": str(stage_id), "decision_note": decision_note},
                )
            except DatabaseError as exc:
                raise translate_database_error(exc) from exc

        self._dispatch_post_decision_notifications(
            stage=stage,
            request_status=advancement.request_status,
            notify_recipient_id=advancement.notify_recipient_id,
        )

        return ApprovalOutcome(
            stage=map_workflow_stage_record_to_domain(decided_stage),
            request_status=advancement.request_status,
            current_stage_id=advancement.new_stage_id,
        )

    def _advance_after_approval(
        self,
        stage: WorkflowStageRecord,
        decided_stage: WorkflowStageRecord,
    ) -> _DecisionAdvancement:
        """Determine and persist the request-level consequence of an approval.

        Args:
            stage: The stage record as it was before this decision.
            decided_stage: The stage record as it now stands, post-decision.

        Returns:
            A ``_DecisionAdvancement`` describing the request's new
            status, the id of any newly generated stage (independent of
            whether a specific notification recipient was resolved for
            it), a notification recipient if one was resolved, and the
            audit action to record.
        """
        try:
            request = self._request_repo.get_by_id(stage.request_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc

        try:
            definition_record = self._workflow_definition_repo.get_by_id(
                request.workflow_definition_id
            )
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        definition_domain = map_workflow_definition_record_to_domain(definition_record)

        highest_existing_order = self._workflow_stage_repo.get_highest_stage_order(request.id)

        try:
            requester_record = self._profile_repo.get_by_id(request.requester_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        requester_domain = map_profile_record_to_domain(requester_record)

        department_approvers = []
        from app.models.enums import AssignmentStrategy  # local import, narrow use

        remaining_stage_defs = [
            s
            for s in definition_domain.definition.ordered_stages()
            if s.order == stage.stage_order + 1
        ]
        if remaining_stage_defs and remaining_stage_defs[0].assignment_strategy is AssignmentStrategy.REQUESTER_MANAGER:
            records = self._profile_repo.list_by_role(
                UserRole.APPROVER, department=requester_domain.department, page=Page(size=100)
            ).items
            department_approvers = [map_profile_record_to_domain(r) for r in records]

        plan = self._workflow_engine.plan_next_stage(
            definition_domain,
            current_order=stage.stage_order,
            highest_existing_order=highest_existing_order,
            requester=requester_domain,
            department_approvers=department_approvers,
        )

        if plan is None:
            try:
                self._workflow_engine.validate_request_status_transition(
                    request.status, RequestStatus.COMPLETED
                )
            except EngineWorkflowError as exc:
                raise translate_workflow_error(exc) from exc
            try:
                self._request_repo.set_current_stage(
                    request.id,
                    expected_version=request.version,
                    current_stage_id=None,
                    status=RequestStatus.COMPLETED,
                    completed_at=utc_now(),
                )
            except DatabaseError as exc:
                raise translate_database_error(exc) from exc
            return _DecisionAdvancement(
                request_status=RequestStatus.COMPLETED,
                new_stage_id=None,
                notify_recipient_id=None,
                audit_action=AuditAction.STAGE_APPROVED,
            )

        try:
            new_stage = self._workflow_stage_repo.create_stage(
                request_id=request.id,
                stage_order=plan.stage_order,
                stage_name=plan.stage_name,
                assigned_role=plan.assigned_role,
                assigned_to=plan.assigned_to,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        try:
            self._workflow_engine.validate_request_status_transition(
                request.status, RequestStatus.IN_REVIEW
            )
        except EngineWorkflowError as exc:
            raise translate_workflow_error(exc) from exc

        try:
            self._request_repo.set_current_stage(
                request.id,
                expected_version=request.version,
                current_stage_id=new_stage.id,
                status=RequestStatus.IN_REVIEW,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        # new_stage.id is always populated here: a next stage genuinely
        # was created, regardless of whether plan.assigned_to resolved to
        # a specific user or the stage was left assigned to a role-
        # eligible pool (WEDD Section 7.3's department_queue "queue"
        # semantic). notify_recipient_id is intentionally allowed to be
        # None in the latter case; there is simply no single user to
        # notify by name, not an indication that no stage was created.
        return _DecisionAdvancement(
            request_status=RequestStatus.IN_REVIEW,
            new_stage_id=new_stage.id,
            notify_recipient_id=plan.assigned_to,
            audit_action=AuditAction.STAGE_APPROVED,
        )

    def _finalize_rejection(self, stage: WorkflowStageRecord) -> _DecisionAdvancement:
        """Terminate a request's workflow following a stage rejection.

        Args:
            stage: The stage record as it was before this decision.

        Returns:
            A ``_DecisionAdvancement`` with ``request_status =
            RequestStatus.REJECTED``, ``new_stage_id = None``, and
            ``notify_recipient_id = None`` (the requester is notified
            directly by ``_dispatch_post_decision_notifications`` based
            on ``request_status`` alone, not via this field).
        """
        try:
            request = self._request_repo.get_by_id(stage.request_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc

        try:
            self._workflow_engine.validate_request_status_transition(
                request.status, RequestStatus.REJECTED
            )
        except EngineWorkflowError as exc:
            raise translate_workflow_error(exc) from exc

        try:
            self._request_repo.set_current_stage(
                request.id,
                expected_version=request.version,
                current_stage_id=None,
                status=RequestStatus.REJECTED,
                completed_at=utc_now(),
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return _DecisionAdvancement(
            request_status=RequestStatus.REJECTED,
            new_stage_id=None,
            notify_recipient_id=None,
            audit_action=AuditAction.STAGE_REJECTED,
        )

    def _dispatch_post_decision_notifications(
        self,
        *,
        stage: WorkflowStageRecord,
        request_status: RequestStatus,
        notify_recipient_id: UUID | None,
    ) -> None:
        """Dispatch the post-commit notification appropriate to a decision's outcome.

        Per WEDD Section 15.1: an approval that advances to a further
        stage triggers only an ``assignment`` notification to the next
        assignee (when one was resolved to a specific user); an approval
        that completes the request triggers only a ``completion``
        notification to the requester; a rejection triggers a
        ``decision`` notification to the requester.

        Args:
            stage: The stage record as it was before this decision.
            request_status: The resulting request-level status.
            notify_recipient_id: The specific user to notify of a new
                assignment, if one was resolved; ``None`` if the new
                stage (if any) resolved to a role-eligible pool instead,
                or if no new stage was created.
        """
        try:
            request = self._request_repo.get_by_id(stage.request_id)
        except RecordNotFoundError:
            self._logger.error(
                "Could not load request %s to dispatch post-decision notification",
                stage.request_id,
            )
            return

        if request_status is RequestStatus.REJECTED:
            self._notification_service.notify_decision(
                recipient_id=request.requester_id,
                request_id=request.id,
                message=f"Your request '{request.title}' was rejected.",
            )
            return

        if request_status is RequestStatus.COMPLETED:
            self._notification_service.notify_completion(
                recipient_id=request.requester_id,
                request_id=request.id,
                message=f"Your request '{request.title}' has been completed.",
            )
            return

        if notify_recipient_id is not None:
            self._notification_service.notify_assignment(
                recipient_id=notify_recipient_id,
                request_id=request.id,
                message=f"You have been assigned to review '{request.title}'.",
            )