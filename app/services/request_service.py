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
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError

from app.auth.authentication import AuthenticatedIdentity
from app.auth.authorization import (
    authorize_request_edit,
    authorize_request_view,
    authorize_request_withdrawal,
)
from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.request_repository import RequestRecord, RequestRepository
from app.database.repositories.user_repository import ProfileRecord, ProfileRepository
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
    WorkflowStageRepository,
)
from app.models import Profile, Request, RequestCreate, RequestUpdate
from app.models.enums import AuditAction, RequestStatus, UserRole
from app.models.exceptions import DomainError
from app.services.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
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
from app.utils.datetime_utils import utc_now
from app.utils.decorators import log_calls
from app.workflow.constants import ASSIGNMENT_FALLBACK_METADATA_KEY
from app.workflow.engine import StagePlan, WorkflowEngine
from app.workflow.exceptions import WorkflowError as EngineWorkflowError

__all__ = ["map_profile_record_to_domain", "map_request_record_to_domain", "RequestService"]

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
        """
        self._request_repo = request_repo
        self._workflow_definition_repo = workflow_definition_repo
        self._workflow_stage_repo = workflow_stage_repo
        self._profile_repo = profile_repo
        self._audit_repo = audit_repo
        self._notification_service = notification_service
        self._workflow_engine = workflow_engine
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
                request_type=request_type, title=title, description=description, department=department
            )
        except (PydanticValidationError, DomainError) as exc:
            raise translate_model_construction_error(exc, model_name="RequestCreate") from exc

        try:
            candidates = self._workflow_definition_repo.list_definitions(
                request_type=payload.request_type, is_active=True, page=Page(size=10)
            ).items
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        try:
            definition_domain = self._workflow_engine.resolve_definition(
                payload.request_type, candidates
            )
        except EngineWorkflowError as exc:
            raise translate_workflow_error(exc) from exc

        try:
            requester_record = self._profile_repo.get_by_id(identity.user_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        requester_domain = map_profile_record_to_domain(requester_record)

        department_approvers = self._fetch_department_approvers_if_needed(
            definition_domain, requester_domain
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
                    description=payload.description,
                    department=payload.department,
                )
            except DatabaseError as exc:
                raise translate_database_error(exc) from exc

            tx.register_compensation(
                lambda: self._request_repo.soft_delete(
                    created_request.id,  # type: ignore[union-attr]
                    expected_version=created_request.version,  # type: ignore[union-attr]
                    deleted_by=identity.user_id,
                )
            )

            try:
                created_stage = self._workflow_stage_repo.create_stage(
                    request_id=created_request.id,
                    stage_order=plan.stage_order,
                    stage_name=plan.stage_name,
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

        is_requester = record.requester_id == identity.user_id
        is_assigned_approver = self._is_assigned_to_any_stage(record.id, identity.user_id, identity.role)

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
        if identity.role is UserRole.EMPLOYEE:
            requester_filter = identity.user_id

        try:
            result = self._request_repo.list_requests(
                status=status,
                request_type=request_type,
                department=department,
                requester_id=requester_filter,
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
        try:
            result = self._request_repo.search_requests(query_text, page=page)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        items = result.items
        if identity.role is UserRole.EMPLOYEE:
            items = [r for r in items if r.requester_id == identity.user_id]

        return PagedResult(
            items=[map_request_record_to_domain(r) for r in items],
            page=result.page,
            page_size=result.page_size,
            total_records=result.total_records,
        )

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
        self, definition, requester: Profile
    ) -> Sequence[Profile]:
        """Fetch the department-approver candidate pool only when the
        definition's first stage actually needs it.

        Args:
            definition: The resolved workflow definition.
            requester: The requester's profile.

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
                UserRole.APPROVER, department=requester.department, page=Page(size=100)
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
        return any(
            stage.assigned_to == user_id or stage.assigned_role == role for stage in stages
        )