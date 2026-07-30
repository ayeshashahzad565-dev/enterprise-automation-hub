"""Application service orchestrating the request submission and lifecycle use cases.

Per the Workflow Engine Design Document (WEDD Section 5) and the API
Design Document (API-ADD Sections 19.3), this service coordinates
``RequestRepository``, ``WorkflowDefinitionRepository``,
``WorkflowStageRepository``, ``ProfileRepository``, ``AuditRepository``,
``NotificationService``, and ``app.workflow.WorkflowEngine`` to implement
request creation, editing, withdrawal, and read access.

Every business rule enforced here — which workflow definition governs a
request, how the first stage is assigned, which state transitions are
legal — is delegated entirely to ``app.workflow.WorkflowEngine``. This
service's own responsibility, per this package's design brief, is
strictly limited to: validating input shape, resolving the data the
Workflow Engine's pure functions need, invoking those functions,
persisting their results through the Repository Layer, writing the audit
trail, and triggering notifications after commit — never deciding a
workflow outcome itself.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError

from app.auth.authentication import AuthenticatedIdentity
from app.auth.authorization import (
    authorize_audit_trail_view,
    authorize_request_edit,
    authorize_request_view,
    authorize_request_withdrawal,
)
from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import MAX_PAGE_SIZE, Page, PagedResult
from app.database.repositories.request_repository import RequestRecord, RequestRepository
from app.database.repositories.user_repository import ProfileRecord, ProfileRepository
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
    WorkflowStageRepository,
)
from app.models import Profile, Request, RequestCreate, RequestUpdate
from app.models.enums import AuditAction, RequestStatus, StageStatus, UserRole
from app.models.exceptions import DomainError
from app.services.exceptions import (
    NotFoundError,
    translate_auth_error,
    translate_database_error,
    translate_model_construction_error,
    translate_workflow_error,
)
from app.services.notification_service import NotificationService
from app.services.workflow_definition_service import (
    TransactionContext,
    map_workflow_definition_record_to_domain,
)
from app.utils.decorators import log_calls
from app.workflow.constants import ASSIGNMENT_FALLBACK_METADATA_KEY
from app.workflow.engine import WorkflowEngine
from app.workflow.exceptions import WorkflowError as EngineWorkflowError

__all__ = [
    "map_profile_record_to_domain",
    "map_request_record_to_domain",
    "RequestService",
    "WorkflowStageDetail",
    "UpcomingStage",
    "WorkflowProgress",
    "AuditEntryDetail",
]

logger = logging.getLogger(__name__)


def map_profile_record_to_domain(record: ProfileRecord) -> Profile:
    """Map a persistence-level ``ProfileRecord`` into its Domain Layer
    ``Profile`` representation.

    Args:
        record: The record returned by ``ProfileRepository``.

    Returns:
        The corresponding ``Profile`` domain model.
    """
    return Profile(
        id=record.id,
        full_name=record.full_name,
        role=record.role,
        department=record.department,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        company_id=record.company_id,
        is_platform_admin=record.is_platform_admin,
    )


def map_request_record_to_domain(record: RequestRecord) -> Request:
    """Map a persistence-level ``RequestRecord`` into its Domain Layer
    ``Request`` representation.

    Args:
        record: The record returned by ``RequestRepository``.

    Returns:
        The corresponding ``Request`` domain model.
    """
    return Request(
        id=record.id,
        requester_id=record.requester_id,
        workflow_definition_id=record.workflow_definition_id,
        request_type=record.request_type,
        title=record.title,
        description=record.description,
        department=record.department,
        status=record.status,
        current_stage_id=record.current_stage_id,
        version=record.version,
        deleted_at=record.deleted_at,
        deleted_by=record.deleted_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


@dataclass(frozen=True, slots=True)
class WorkflowStageDetail:
    """A single workflow stage, enriched for read-only presentation.

    Unlike ``app.models.workflow.WorkflowStage`` (the persisted-row
    representation, which carries only raw ids), every user-facing field
    here is already resolved to something a page can display directly —
    no page needs to separately look up a profile id to show a name.

    Attributes:
        stage_id: The stage's id.
        stage_order: The stage's 1-indexed position in the approval chain.
        stage_name: The stage's human-readable label.
        assigned_to_name: The specific assignee's display name, or
            ``None`` if the stage is assigned to a role-eligible pool
            instead of a specific person.
        assigned_role: The role eligible to act on this stage, if not
            assigned to a specific person.
        status: The stage's current decision status.
        created_at: When this stage was materialized.
        decided_at: When this stage was decided, if it has been.
        decided_by_name: The display name of whoever actually decided
            this stage, if it has been decided.
        decision_note: The note recorded with the decision, if any.
        is_escalated: Whether this stage has ever been escalated (per a
            ``STAGE_ESCALATED`` audit entry referencing it) — independent
            of ``status``, since escalation reassigns a stage without
            changing its status away from ``pending``.
    """

    stage_id: UUID
    stage_order: int
    stage_name: str
    assigned_to_name: str | None
    assigned_role: UserRole | None
    status: StageStatus
    created_at: datetime
    decided_at: datetime | None
    decided_by_name: str | None
    decision_note: str | None
    is_escalated: bool


@dataclass(frozen=True, slots=True)
class UpcomingStage:
    """A stage the workflow definition defines but has not yet reached.

    Attributes:
        stage_order: The stage's 1-indexed position in the approval chain.
        stage_name: The stage's human-readable label.
    """

    stage_order: int
    stage_name: str


@dataclass(frozen=True, slots=True)
class WorkflowProgress:
    """A request's complete workflow stage history plus its position
    within the governing workflow definition's total stage count.

    Attributes:
        stages: Every stage materialized for the request so far, ordered
            by ``stage_order`` ascending.
        upcoming_stages: The stages the workflow definition defines but
            has not yet materialized, in order — genuinely known in
            advance (stages are authored up front as part of the
            definition; only their materialization as a
            ``workflow_stages`` row happens incrementally), never a guess.
        current_stage_order: The order of the stage currently awaiting a
            decision, or — once the request has reached a terminal
            status — the order of the last stage that was ever
            materialized (never a stage number the request never
            actually reached).
        total_stages: The total number of stages defined by the
            workflow definition governing this request, regardless of
            how many have been materialized so far.
    """

    stages: list[WorkflowStageDetail]
    upcoming_stages: list[UpcomingStage]
    current_stage_order: int
    total_stages: int


@dataclass(frozen=True, slots=True)
class AuditEntryDetail:
    """A single audit log entry, enriched for read-only presentation.

    Attributes:
        action: The recorded action code.
        actor_name: The acting user's display name, or ``None`` for a
            system-initiated action (e.g. a Scheduler escalation).
        created_at: When the action occurred.
        metadata: The structured snapshot recorded with the entry, if any.
    """

    action: AuditAction
    actor_name: str | None
    created_at: datetime
    metadata: dict[str, object] | None


class RequestService:
    """Orchestrates request creation, editing, withdrawal, and read access."""

    def __init__(
        self,
        *,
        request_repo: RequestRepository,
        workflow_definition_repo: WorkflowDefinitionRepository,
        workflow_stage_repo: WorkflowStageRepository,
        profile_repo: ProfileRepository,
        audit_repo: AuditRepository,
        notification_service: NotificationService,
        workflow_engine: WorkflowEngine,
        approval_repo: ApprovalRepository,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            request_repo: Persistence for ``requests``.
            workflow_definition_repo: Persistence for
                ``workflow_definitions``, used to resolve the active
                definition at creation time.
            workflow_stage_repo: Persistence for ``workflow_stages``,
                used to create the first stage.
            profile_repo: Persistence for ``profiles``, used to fetch the
                requester's own profile and, where needed, a candidate
                approver pool for assignment resolution.
            audit_repo: Persistence for ``audit_logs``.
            notification_service: The service used to dispatch the
                first-stage assignment notification after commit.
            workflow_engine: The composed Workflow Engine facade.
            approval_repo: Persistence for ``workflow_stages``' decision
                fields, used by ``list_requests``/``search_requests`` to
                scope an approver's results to requests with a pending
                stage resolved or role-eligible to them (API-ADD's
                Approver permission: "may not view unrelated requests").
        """
        self._request_repo = request_repo
        self._workflow_definition_repo = workflow_definition_repo
        self._workflow_stage_repo = workflow_stage_repo
        self._profile_repo = profile_repo
        self._audit_repo = audit_repo
        self._notification_service = notification_service
        self._workflow_engine = workflow_engine
        self._approval_repo = approval_repo
        self._logger = logging.getLogger(f"{__name__}.RequestService")

    @log_calls()
    def create_request(
        self,
        identity: AuthenticatedIdentity,
        *,
        request_type: str,
        title: str,
        description: str | None = None,
        department: str | None = None,
    ) -> Request:
        """Submit a new request, generating its first workflow stage.

        Implements the full sequence specified in WEDD Section 5.4:
        validate the payload, resolve the active workflow definition,
        resolve the first stage's assignment, persist the request and
        its first stage together (via ``TransactionContext``), write the
        audit entry, and — only after that sequence completes — trigger
        the assignment notification (WEDD Section 5.7's rule that
        notification dispatch happens after, not inside, the orchestrated
        write).

        Args:
            identity: The authenticated submitter.
            request_type: The request type identifier. Must match an
                active ``WorkflowDefinition``.
            title: Short human-readable summary (1-200 characters).
            description: Full request details, if provided.
            department: Department the request is being raised under, if
                provided.

        Returns:
            The newly created ``Request``, with its ``current_stage_id``
            already pointing at the generated first stage.

        Raises:
            ValidationError: If the payload fails shape validation, or no
                active workflow definition exists for ``request_type``.
            NotFoundError: If the requester's own profile cannot be found.
            AssignmentError: If assignment resolution fails in a way the
                Workflow Engine does not itself recover from via its
                documented fallback (WEDD Section 7.5 covers the
                fallback path itself, which does not raise).
        """
        try:
            payload = RequestCreate(
                request_type=request_type,
                title=title,
                description=description,
                department=department,
            )
        except (PydanticValidationError, DomainError) as exc:
            raise translate_model_construction_error(exc, model_name="RequestCreate") from exc

        try:
            candidates = self._workflow_definition_repo.list_definitions(
                request_type=payload.request_type,
                company_id=identity.company_id,
                is_active=True,
                page=Page(size=10),
            ).items
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        candidate_domains = [map_workflow_definition_record_to_domain(c) for c in candidates]

        try:
            definition_domain = self._workflow_engine.resolve_definition(
                payload.request_type, candidate_domains
            )
        except EngineWorkflowError as exc:
            raise translate_workflow_error(exc) from exc

        try:
            requester_record = self._profile_repo.get_by_id(identity.user_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        requester_domain = map_profile_record_to_domain(requester_record)

        department_approvers = self._fetch_department_approvers_if_needed(
            definition_domain, requester_domain, company_id=identity.company_id
        )

        plan = self._workflow_engine.plan_first_stage(
            definition_domain, requester=requester_domain, department_approvers=department_approvers
        )

        created_request: RequestRecord | None = None
        with TransactionContext(operation_name="create_request") as tx:
            try:
                created_request = self._request_repo.create_request(
                    requester_id=identity.user_id,
                    workflow_definition_id=definition_domain.id,
                    request_type=payload.request_type,
                    title=payload.title,
                    company_id=identity.company_id,
                    description=payload.description,
                    department=payload.department,
                )
            except DatabaseError as exc:
                raise translate_database_error(exc) from exc

            def _compensate_create_request() -> None:
                self._request_repo.soft_delete(
                    created_request.id,  # type: ignore[union-attr]
                    expected_version=created_request.version,  # type: ignore[union-attr]
                    deleted_by=identity.user_id,
                )

            tx.register_compensation(_compensate_create_request)

            try:
                created_stage = self._workflow_stage_repo.create_stage(
                    request_id=created_request.id,
                    stage_order=plan.stage_order,
                    stage_name=plan.stage_name,
                    company_id=identity.company_id,
                    assigned_role=plan.assigned_role,
                    assigned_to=plan.assigned_to,
                )
            except DatabaseError as exc:
                raise translate_database_error(exc) from exc

            try:
                updated_request = self._request_repo.set_current_stage(
                    created_request.id,
                    expected_version=created_request.version,
                    current_stage_id=created_stage.id,
                    status=RequestStatus.PENDING,
                )
            except DatabaseError as exc:
                raise translate_database_error(exc) from exc

            audit_metadata: dict[str, object] = {"stage_id": str(created_stage.id)}
            if plan.used_fallback:
                audit_metadata[ASSIGNMENT_FALLBACK_METADATA_KEY] = plan.fallback_reason

            try:
                self._audit_repo.record_event(
                    action=AuditAction.REQUEST_CREATED,
                    actor_id=identity.user_id,
                    request_id=created_request.id,
                    metadata=audit_metadata,
                )
            except DatabaseError as exc:
                raise translate_database_error(exc) from exc

        self._logger.info(
            "Created request %s (type=%s) with first stage %s",
            updated_request.id,
            payload.request_type,
            plan.stage_name,
            extra={"request_id": str(updated_request.id), "request_type": payload.request_type},
        )

        recipient = plan.assigned_to
        if recipient is not None:
            self._notification_service.notify_assignment(
                recipient_id=recipient,
                request_id=updated_request.id,
                message=f"You have been assigned to review '{payload.title}'.",
            )

        return map_request_record_to_domain(updated_request)

    @log_calls()
    def get_request(self, identity: AuthenticatedIdentity, request_id: UUID) -> Request:
        """Retrieve a single request, enforcing view authorization.

        Args:
            identity: The authenticated caller.
            request_id: The request's id.

        Returns:
            The matching ``Request``.

        Raises:
            NotFoundError: If no request with this id exists.
            PermissionDeniedError: If the caller may not view this request.
        """
        try:
            record = self._request_repo.get_by_id(request_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        if record.company_id != identity.company_id:
            raise NotFoundError("request", request_id)

        is_requester = record.requester_id == identity.user_id
        is_assigned_approver = self._is_assigned_to_any_stage(
            record.id, identity.user_id, identity.role
        )

        try:
            authorize_request_view(
                identity, is_requester=is_requester, is_assigned_approver=is_assigned_approver
            )
        except Exception as exc:  # noqa: BLE001
            # Per API-ADD Section 11.2, an out-of-scope resource is reported
            # as not-found, never as a permission failure, to avoid
            # confirming the resource's existence to an unauthorized caller.
            raise NotFoundError("request", request_id) from exc

        return map_request_record_to_domain(record)

    @log_calls()
    def get_workflow_progress(
        self, identity: AuthenticatedIdentity, request_id: UUID
    ) -> WorkflowProgress:
        """Retrieve a request's complete workflow stage history and progress.

        Read-only: this method performs no workflow decision-making of
        its own and never mutates a stage — it only assembles data
        already produced by ``ApprovalService``/the Workflow Engine
        (stage records, the request's pinned workflow definition, and
        escalation audit entries) into a single, presentation-ready view.

        Visibility matches ``get_request``'s own rule exactly: the
        requester, an approver assigned to any of the request's stages,
        or an administrator.

        Args:
            identity: The authenticated caller.
            request_id: The request's id.

        Returns:
            A ``WorkflowProgress`` describing every stage materialized so
            far, enriched with resolved assignee/decider display names
            and escalation status, plus the request's position within
            its workflow definition's total stage count.

        Raises:
            NotFoundError: If no request with this id exists, or it is
                outside the caller's visibility.
        """
        try:
            record = self._request_repo.get_by_id(request_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        if record.company_id != identity.company_id:
            raise NotFoundError("request", request_id)

        is_requester = record.requester_id == identity.user_id
        is_assigned_approver = self._is_assigned_to_any_stage(
            record.id, identity.user_id, identity.role
        )
        try:
            authorize_request_view(
                identity, is_requester=is_requester, is_assigned_approver=is_assigned_approver
            )
        except Exception as exc:  # noqa: BLE001
            raise NotFoundError("request", request_id) from exc

        try:
            stage_records = self._workflow_stage_repo.list_for_request(
                request_id, page=Page(size=100)
            ).items
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        try:
            audit_entries = self._audit_repo.list_for_request(request_id, page=Page(size=100)).items
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        escalated_stage_ids = {
            entry.metadata.get("stage_id")
            for entry in audit_entries
            if entry.action == AuditAction.STAGE_ESCALATED.value and entry.metadata
        }

        resolve_name = self._build_profile_name_resolver()
        stages = [
            WorkflowStageDetail(
                stage_id=stage.id,
                stage_order=stage.stage_order,
                stage_name=stage.stage_name,
                assigned_to_name=resolve_name(stage.assigned_to),
                assigned_role=stage.assigned_role,
                status=stage.status,
                created_at=stage.created_at,
                decided_at=stage.decided_at,
                decided_by_name=resolve_name(stage.decided_by),
                decision_note=stage.decision_note,
                is_escalated=str(stage.id) in escalated_stage_ids,
            )
            for stage in stage_records
        ]

        try:
            definition_record = self._workflow_definition_repo.get_by_id(
                record.workflow_definition_id
            )
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        stage_defs = definition_record.definition.get("stages", [])
        total_stages = len(stage_defs)
        materialized_orders = {stage.stage_order for stage in stages}
        upcoming_stages = [
            UpcomingStage(stage_order=stage_def["order"], stage_name=stage_def["name"])
            for stage_def in sorted(stage_defs, key=lambda stage_def: stage_def["order"])
            if stage_def["order"] not in materialized_orders
        ]

        pending_stage = next((s for s in stages if s.status is StageStatus.PENDING), None)
        if pending_stage is not None:
            current_stage_order = pending_stage.stage_order
        elif stages:
            current_stage_order = stages[-1].stage_order
        else:
            current_stage_order = 0

        return WorkflowProgress(
            stages=stages,
            upcoming_stages=upcoming_stages,
            current_stage_order=current_stage_order,
            total_stages=total_stages,
        )

    @log_calls()
    def get_audit_trail(
        self, identity: AuthenticatedIdentity, request_id: UUID
    ) -> list[AuditEntryDetail]:
        """Retrieve a request's complete audit trail, chronologically.

        Visibility follows API-ADD Section 19.10.1: the same population
        permitted to view the request itself.

        Args:
            identity: The authenticated caller.
            request_id: The request's id.

        Returns:
            The request's audit entries, oldest first, with each entry's
            actor resolved to a display name.

        Raises:
            NotFoundError: If no request with this id exists, or it is
                outside the caller's visibility.
        """
        try:
            record = self._request_repo.get_by_id(request_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        if record.company_id != identity.company_id:
            raise NotFoundError("request", request_id)

        is_requester = record.requester_id == identity.user_id
        is_assigned_approver = self._is_assigned_to_any_stage(
            record.id, identity.user_id, identity.role
        )
        try:
            authorize_audit_trail_view(
                identity, is_requester=is_requester, is_assigned_approver=is_assigned_approver
            )
        except Exception as exc:  # noqa: BLE001
            raise NotFoundError("request", request_id) from exc

        try:
            entries = self._audit_repo.list_for_request(request_id, page=Page(size=100)).items
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        resolve_name = self._build_profile_name_resolver()
        return [
            AuditEntryDetail(
                action=AuditAction(entry.action),
                actor_name=resolve_name(entry.actor_id),
                created_at=entry.created_at,
                metadata=entry.metadata,
            )
            for entry in entries
        ]

    @log_calls()
    def list_requests(
        self,
        identity: AuthenticatedIdentity,
        *,
        status: RequestStatus | None = None,
        request_type: str | None = None,
        department: str | None = None,
        page: Page = Page(),
    ) -> PagedResult[Request]:
        """List requests visible to the caller.

        Per DSD Section 9's Row-Level Security policies, the underlying
        database connection is expected to already scope which rows are
        returned to the authenticated caller. This method additionally
        enforces, defensively, that an ``employee`` may only ever list
        their own requests, even if the underlying connection's RLS
        policy were somehow bypassed — the same defense-in-depth
        discipline applied throughout the architecture.

        Args:
            identity: The authenticated caller.
            status: Restrict to this lifecycle status, if provided.
            request_type: Restrict to this request type, if provided.
            department: Restrict to this department, if provided.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching ``Request`` instances.
        """
        requester_filter: UUID | None = None
        request_ids_filter: list[UUID] | None = None
        if identity.role is UserRole.EMPLOYEE:
            requester_filter = identity.user_id
        elif identity.role is UserRole.APPROVER:
            request_ids_filter = self._visible_request_ids_for_approver(identity)
            if not request_ids_filter:
                return PagedResult(items=[], page=page.number, page_size=page.size, total_records=0)

        try:
            result = self._request_repo.list_requests(
                company_id=identity.company_id,
                status=status,
                request_type=request_type,
                department=department,
                requester_id=requester_filter,
                request_ids=request_ids_filter,
                page=page,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return PagedResult(
            items=[map_request_record_to_domain(r) for r in result.items],
            page=result.page,
            page_size=result.page_size,
            total_records=result.total_records,
        )

    @log_calls()
    def search_requests(
        self, identity: AuthenticatedIdentity, query_text: str, *, page: Page = Page()
    ) -> PagedResult[Request]:
        """Free-text search across the caller's visible requests.

        Args:
            identity: The authenticated caller.
            query_text: The search term.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching ``Request`` instances.

        Raises:
            ValidationError: If ``query_text`` is empty.
        """
        requester_filter: UUID | None = None
        request_ids_filter: list[UUID] | None = None
        if identity.role is UserRole.EMPLOYEE:
            requester_filter = identity.user_id
        elif identity.role is UserRole.APPROVER:
            request_ids_filter = self._visible_request_ids_for_approver(identity)
            if not request_ids_filter:
                return PagedResult(items=[], page=page.number, page_size=page.size, total_records=0)

        try:
            result = self._request_repo.search_requests(
                query_text,
                company_id=identity.company_id,
                requester_id=requester_filter,
                request_ids=request_ids_filter,
                page=page,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return PagedResult(
            items=[map_request_record_to_domain(r) for r in result.items],
            page=result.page,
            page_size=result.page_size,
            total_records=result.total_records,
        )

    def _visible_request_ids_for_approver(self, identity: AuthenticatedIdentity) -> list[UUID]:
        """Return the request ids an approver may browse or search.

        Matches the Approver permission documented in API-ADD Section 6.2:
        "may view requests where they are the resolved or role-eligible
        assignee on a pending stage... may not view unrelated requests."
        Bounded to the first ``MAX_PAGE_SIZE`` matching stages, the same
        bound this service's own ``_is_assigned_to_any_stage`` already
        applies per-request, reasonable at this application's documented
        scale (SRS Section 12.1: up to 50 concurrent users).

        Args:
            identity: The authenticated approver.

        Returns:
            The distinct request ids with at least one pending stage
            assigned to this user or eligible for their role. Empty if
            none.
        """
        stages = self._approval_repo.list_pending_for_approver(
            company_id=identity.company_id,
            assigned_to=identity.user_id,
            assigned_role=identity.role,
            page=Page(size=MAX_PAGE_SIZE),
        ).items
        return list({stage.request_id for stage in stages})

    @log_calls()
    def update_request(
        self,
        identity: AuthenticatedIdentity,
        request_id: UUID,
        *,
        title: str | None = None,
        description: str | None = None,
        department: str | None = None,
        expected_version: int,
    ) -> Request:
        """Update a request's editable fields while it is still pending.

        Note: no audit action code exists (WEDD Section 14.1) for this
        operation, so no ``audit_logs`` entry is written here — the
        Workflow Engine Design Document does not enumerate a request
        edit as an audited event, unlike creation, decisions, and
        activation.

        Args:
            identity: The authenticated caller.
            request_id: The request's id.
            title: The new title, if changing.
            description: The new description, if changing.
            department: The new department, if changing.
            expected_version: The version last observed by the caller.

        Returns:
            The updated ``Request``.

        Raises:
            NotFoundError: If no request with this id exists.
            PermissionDeniedError: If the caller is not the requester, or
                the request is no longer pending.
            ValidationError: If no field to update was provided.
            ConcurrencyError: If ``expected_version`` no longer matches.
        """
        try:
            record = self._request_repo.get_by_id(request_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        if record.company_id != identity.company_id:
            raise NotFoundError("request", request_id)

        try:
            authorize_request_edit(
                identity,
                is_requester=record.requester_id == identity.user_id,
                request_is_pending=record.status is RequestStatus.PENDING,
            )
        except Exception as exc:  # noqa: BLE001
            raise translate_auth_error(exc) from exc

        try:
            RequestUpdate(title=title, description=description, department=department)
        except (PydanticValidationError, DomainError) as exc:
            raise translate_model_construction_error(exc, model_name="RequestUpdate") from exc

        try:
            updated = self._request_repo.update_editable_fields(
                request_id,
                expected_version=expected_version,
                title=title,
                description=description,
                department=department,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return map_request_record_to_domain(updated)

    @log_calls()
    def withdraw_request(
        self, identity: AuthenticatedIdentity, request_id: UUID, *, expected_version: int
    ) -> Request:
        """Withdraw (soft-delete) a request.

        Args:
            identity: The authenticated caller.
            request_id: The request's id.
            expected_version: The version last observed by the caller.

        Returns:
            The updated ``Request``, with ``deleted_at`` populated.

        Raises:
            NotFoundError: If no request with this id exists.
            PermissionDeniedError: If the caller is not the requester
                (while pending) and not an administrator.
            ConcurrencyError: If ``expected_version`` no longer matches.
        """
        try:
            record = self._request_repo.get_by_id(request_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        if record.company_id != identity.company_id:
            raise NotFoundError("request", request_id)

        try:
            authorize_request_withdrawal(
                identity,
                is_requester=record.requester_id == identity.user_id,
                request_is_pending=record.status is RequestStatus.PENDING,
            )
        except Exception as exc:  # noqa: BLE001
            raise translate_auth_error(exc) from exc

        try:
            updated = self._request_repo.soft_delete(
                request_id, expected_version=expected_version, deleted_by=identity.user_id
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        try:
            self._audit_repo.record_event(
                action=AuditAction.REQUEST_WITHDRAWN,
                actor_id=identity.user_id,
                request_id=request_id,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return map_request_record_to_domain(updated)

    def _fetch_department_approvers_if_needed(
        self, definition, requester: Profile, *, company_id: UUID
    ) -> Sequence[Profile]:
        """Fetch the department-approver candidate pool only when the
        definition's first stage actually needs it.

        Args:
            definition: The resolved workflow definition.
            requester: The requester's profile.
            company_id: The company (tenant) to restrict the candidate
                pool to — always the caller's own ``identity.company_id``.

        Returns:
            A list of candidate ``Profile`` instances, or an empty list if
            the first stage's assignment strategy does not require them.
        """
        from app.models.enums import AssignmentStrategy  # local import, narrow use

        first_stage = definition.definition.ordered_stages()[0]
        if first_stage.assignment_strategy is not AssignmentStrategy.REQUESTER_MANAGER:
            return []

        try:
            records = self._profile_repo.list_by_role(
                UserRole.APPROVER,
                company_id=company_id,
                department=requester.department,
                page=Page(size=100),
            ).items
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        return [map_profile_record_to_domain(r) for r in records]

    def _is_assigned_to_any_stage(self, request_id: UUID, user_id: UUID, role: UserRole) -> bool:
        """Determine whether a caller is assigned to any stage on a request.

        Args:
            request_id: The request's id.
            user_id: The caller's id.
            role: The caller's role.

        Returns:
            ``True`` if the caller is a specific assignee, or an eligible
            role-based assignee, on any stage belonging to this request.
        """
        if role not in (UserRole.APPROVER, UserRole.ADMIN):
            return False
        stages = self._workflow_stage_repo.list_for_request(request_id, page=Page(size=100)).items
        return any(stage.assigned_to == user_id or stage.assigned_role == role for stage in stages)

    def _build_profile_name_resolver(self) -> Callable[[UUID | None], str | None]:
        """Return a callable resolving a profile id to its display name.

        The returned callable caches each id it resolves for the
        lifetime of the single call site that requested it (never across
        separate ``get_workflow_progress``/``get_audit_trail`` calls), so
        a request's stages/audit entries referencing the same user
        repeatedly are only looked up once, without risking a stale name
        surviving across unrelated calls.

        Returns:
            A callable ``(profile_id) -> display_name``, tolerating a
            ``None`` input (returns ``None``) and a profile id that no
            longer resolves to any row (returns ``"Unknown user"`` rather
            than raising, since a missing profile must never break an
            otherwise-valid history view).
        """
        cache: dict[UUID, str] = {}

        def resolve(profile_id: UUID | None) -> str | None:
            if profile_id is None:
                return None
            if profile_id not in cache:
                profile = self._profile_repo.find_by_id(profile_id)
                cache[profile_id] = profile.full_name if profile is not None else "Unknown user"
            return cache[profile_id]

        return resolve
