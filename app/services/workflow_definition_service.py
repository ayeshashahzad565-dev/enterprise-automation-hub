"""Application service orchestrating workflow definition lifecycle operations.

Per the Workflow Engine Design Document (WEDD Section 9) and the API
Design Document (API-ADD Section 19.9), this service coordinates
``WorkflowDefinitionRepository``, ``ProfileRepository``,
``AuditRepository``, and ``app.workflow.WorkflowEngine`` to implement
creation, draft editing, activation, and read access for workflow
definitions. Every business rule enforced here — version numbering,
edit-while-inactive-only, at-most-one-active-per-type — is delegated to
``WorkflowEngine``; this service's own responsibility is limited to
input validation, authorization, data assembly, and transaction
orchestration.

This module also defines ``TransactionContext``, the compensation-based
orchestration boundary shared by every service in this package that
performs a multi-step operation spanning more than one repository call.
See ``TransactionContext``'s own docstring for exactly what guarantee it
does and does not provide.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError

from app.auth.authentication import AuthenticatedIdentity
from app.auth.authorization import authorize_workflow_definition_management
from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.user_repository import ProfileRepository
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRecord,
    WorkflowDefinitionRepository,
)
from app.models import WorkflowDefinition, WorkflowDefinitionDocument
from app.models.enums import AuditAction
from app.models.exceptions import DomainError
from app.services.exceptions import (
    NotFoundError,
    translate_auth_error,
    translate_database_error,
    translate_model_construction_error,
    translate_workflow_error,
)
from app.utils.decorators import log_calls
from app.workflow.engine import WorkflowEngine
from app.workflow.exceptions import WorkflowError as EngineWorkflowError

__all__ = [
    "TransactionContext",
    "map_workflow_definition_record_to_domain",
    "WorkflowDefinitionService",
]

logger = logging.getLogger(__name__)


class TransactionContext:
    """A compensation-based orchestration boundary for multi-step operations.

    **What this class does not provide:** the finalized Repository Layer
    (``app.database.repositories``) executes each call as its own
    independent request against Supabase's PostgREST API; the Supabase
    client this project uses exposes no cross-statement ``BEGIN``/
    ``COMMIT`` primitive to Python code. This class therefore does not
    provide true, database-level ACID atomicity across multiple
    repository calls.

    **What this class does provide:** a disciplined compensation
    boundary. Each step of a multi-step operation registers an optional
    compensating action via ``register_compensation``. If a later step
    raises, every previously registered compensation is executed, in
    reverse order, before the triggering exception propagates — so a
    partial multi-step operation (for example, a ``requests`` row created
    successfully but its first ``workflow_stages`` row failing to insert)
    does not silently leave orphaned data behind uncorrected. A
    compensation failure is logged, not raised, so that one failed
    compensation does not prevent the remaining ones from running.

    This is the closest approximation of the Database Schema Design
    Document's transaction list (DSD Section 11) available given the
    finalized database client's actual capabilities, and it is documented
    here candidly rather than presented as equivalent to a real
    transaction.
    """

    def __init__(self, *, operation_name: str) -> None:
        """Initialize a transaction context for a named operation.

        Args:
            operation_name: A short, human-readable name for the
                operation this context spans, used only for logging.
        """
        self._operation_name = operation_name
        self._compensations: list[Callable[[], None]] = []
        self._logger = logging.getLogger(f"{__name__}.TransactionContext")

    def register_compensation(self, action: Callable[[], None]) -> None:
        """Register a compensating action to run if a later step fails.

        Args:
            action: A zero-argument callable that undoes the effect of
                the step just completed.
        """
        self._compensations.append(action)

    def __enter__(self) -> TransactionContext:
        self._logger.debug(
            "Beginning orchestrated operation '%s'",
            self._operation_name,
            extra={"operation": self._operation_name},
        )
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: object
    ) -> Literal[False]:
        if exc_type is None:
            self._logger.debug(
                "Completed orchestrated operation '%s'",
                self._operation_name,
                extra={"operation": self._operation_name},
            )
            return False

        self._logger.warning(
            "Orchestrated operation '%s' failed; running %d compensating action(s): %s",
            self._operation_name,
            len(self._compensations),
            exc,
            extra={"operation": self._operation_name},
        )
        for compensation in reversed(self._compensations):
            try:
                compensation()
            except (
                Exception
            ):  # noqa: BLE001 - a failed compensation must not mask the original error
                self._logger.error(
                    "Compensating action failed during rollback of '%s'",
                    self._operation_name,
                    exc_info=True,
                    extra={"operation": self._operation_name},
                )
        return False  # never suppress the triggering exception


def map_workflow_definition_record_to_domain(
    record: WorkflowDefinitionRecord,
) -> WorkflowDefinition:
    """Map a persistence-level ``WorkflowDefinitionRecord`` into its Domain
    Layer ``WorkflowDefinition`` representation.

    Args:
        record: The record returned by ``WorkflowDefinitionRepository``.

    Returns:
        The corresponding ``WorkflowDefinition`` domain model, with its
        ``definition`` field validated into a ``WorkflowDefinitionDocument``.

    Raises:
        ValidationError: If ``record.definition`` fails
            ``WorkflowDefinitionDocument`` validation — this should never
            occur for a definition that was itself validated before being
            persisted (WEDD Section 13.1), and indicates either a
            defect upstream or a manually inserted, invalid row.
    """
    try:
        document = WorkflowDefinitionDocument.model_validate(record.definition)
    except (PydanticValidationError, DomainError) as exc:
        raise translate_model_construction_error(
            exc, model_name="WorkflowDefinitionDocument"
        ) from exc
    return WorkflowDefinition(
        id=record.id,
        request_type=record.request_type,
        version=record.version,
        definition=document,
        is_active=record.is_active,
        created_by=record.created_by,
        row_version=record.row_version,
        created_at=record.created_at,
    )


class WorkflowDefinitionService:
    """Orchestrates workflow definition creation, editing, activation, and reads.

    Every method requires an ``AuthenticatedIdentity`` and enforces,
    before any persistence, that the caller is an administrator
    (API-ADD Section 19.9's "admin only" rule for every mutating
    endpoint), except ``list_versions`` and ``get_active_version``, which
    are readable by any authenticated user for active definitions
    (API-ADD Section 19.9.4).
    """

    def __init__(
        self,
        *,
        workflow_definition_repo: WorkflowDefinitionRepository,
        profile_repo: ProfileRepository,
        audit_repo: AuditRepository,
        workflow_engine: WorkflowEngine,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            workflow_definition_repo: Persistence for
                ``workflow_definitions``.
            profile_repo: Persistence for ``profiles``, used to validate
                ``specific_user`` assignees referenced by a candidate
                definition.
            audit_repo: Persistence for ``audit_logs``, used to record
                ``WORKFLOW_DEFINITION_ACTIVATED`` events per WEDD Section
                14.1.
            workflow_engine: The composed Workflow Engine facade.
        """
        self._workflow_definition_repo = workflow_definition_repo
        self._profile_repo = profile_repo
        self._audit_repo = audit_repo
        self._workflow_engine = workflow_engine
        self._logger = logging.getLogger(f"{__name__}.WorkflowDefinitionService")

    @log_calls()
    def create_definition(
        self,
        identity: AuthenticatedIdentity,
        *,
        request_type: str,
        definition: dict,
    ) -> WorkflowDefinition:
        """Create a new, inactive workflow definition version.

        Args:
            identity: The authenticated administrator creating this
                version.
            request_type: The request type this definition will govern.
            definition: The raw JSON document (``{"stages": [...]}``, per
                DSD Section 5.2), to be validated by
                ``WorkflowDefinitionDocument`` before any assignee lookup
                or persistence is attempted.

        Returns:
            The newly created ``WorkflowDefinition``, with
            ``is_active = False`` (WEDD Section 9.1).

        Raises:
            PermissionDeniedError: If ``identity`` is not an
                administrator.
            ValidationError: If ``definition`` fails structural
                validation (WEDD Section 13.1).
            AssignmentError: If any ``specific_user`` stage references a
                profile id that does not exist (WEDD Section 13.3).
        """
        try:
            authorize_workflow_definition_management(identity)
        except Exception as exc:  # noqa: BLE001 - translated below
            raise translate_auth_error(exc) from exc

        document = self._validate_document(definition)
        self._validate_assignees(document)

        try:
            existing_versions = [
                d.version
                for d in self._workflow_definition_repo.list_definitions(
                    request_type=request_type, company_id=identity.company_id, page=Page(size=100)
                ).items
            ]
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        next_version = self._workflow_engine.next_definition_version(existing_versions)

        try:
            created = self._workflow_definition_repo.create_definition(
                request_type=request_type,
                version=next_version,
                definition=document.model_dump(mode="json"),
                created_by=identity.user_id,
                company_id=identity.company_id,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._logger.info(
            "Created workflow definition %s (version %d) for request_type=%s",
            created.id,
            created.version,
            request_type,
            extra={"definition_id": str(created.id), "request_type": request_type},
        )
        return map_workflow_definition_record_to_domain(created)

    @log_calls()
    def update_draft(
        self,
        identity: AuthenticatedIdentity,
        definition_id: UUID,
        *,
        definition: dict,
    ) -> WorkflowDefinition:
        """Edit a workflow definition that has not yet been activated.

        Args:
            identity: The authenticated administrator making the edit.
            definition_id: The id of the definition to edit.
            definition: The replacement JSON document.

        Returns:
            The updated ``WorkflowDefinition``.

        Raises:
            PermissionDeniedError: If ``identity`` is not an
                administrator.
            NotFoundError: If no definition with ``definition_id`` exists.
            WorkflowError: If the target definition is already active
                (API-ADD Section 19.9.2).
            ValidationError: If ``definition`` fails structural
                validation.
            AssignmentError: If any ``specific_user`` stage references an
                unknown profile.
        """
        try:
            authorize_workflow_definition_management(identity)
        except Exception as exc:  # noqa: BLE001
            raise translate_auth_error(exc) from exc

        try:
            # get_by_id_for_company reports a different company's
            # definition exactly as not-found, never a permission
            # failure, matching this codebase's established convention
            # for cross-tenant/cross-owner access elsewhere (e.g.
            # authorize_request_view) — enforced structurally by the
            # repository itself, not by a manual check here.
            existing = self._workflow_definition_repo.get_by_id_for_company(
                definition_id, company_id=identity.company_id
            )
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc

        existing_domain = map_workflow_definition_record_to_domain(existing)
        try:
            self._workflow_engine.validate_definition_edit(existing_domain)
        except EngineWorkflowError as exc:
            raise translate_workflow_error(exc) from exc

        document = self._validate_document(definition)
        self._validate_assignees(document)

        try:
            updated = self._workflow_definition_repo.update_inactive_definition(
                definition_id,
                expected_row_version=existing.row_version,
                definition=document.model_dump(mode="json"),
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._logger.info(
            "Updated draft workflow definition %s",
            definition_id,
            extra={"definition_id": str(definition_id)},
        )
        return map_workflow_definition_record_to_domain(updated)

    @log_calls()
    def delete_draft(self, identity: AuthenticatedIdentity, definition_id: UUID) -> None:
        """Delete a workflow definition that has not yet been activated.

        Args:
            identity: The authenticated administrator deleting this
                version.
            definition_id: The id of the definition to delete.

        Raises:
            PermissionDeniedError: If ``identity`` is not an
                administrator.
            NotFoundError: If no definition with ``definition_id`` exists.
            WorkflowError: If the target definition is already active —
                reuses the same rule ``update_draft`` enforces, since
                deleting an active definition would be exactly as
                destructive as silently editing one in place.
        """
        try:
            authorize_workflow_definition_management(identity)
        except Exception as exc:  # noqa: BLE001
            raise translate_auth_error(exc) from exc

        try:
            existing = self._workflow_definition_repo.get_by_id_for_company(
                definition_id, company_id=identity.company_id
            )
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc

        existing_domain = map_workflow_definition_record_to_domain(existing)
        try:
            self._workflow_engine.validate_definition_edit(existing_domain)
        except EngineWorkflowError as exc:
            raise translate_workflow_error(exc) from exc

        try:
            self._workflow_definition_repo.delete_inactive_definition(
                definition_id, company_id=identity.company_id
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._logger.info(
            "Deleted draft workflow definition %s",
            definition_id,
            extra={"definition_id": str(definition_id)},
        )

    @log_calls()
    def activate_version(
        self, identity: AuthenticatedIdentity, definition_id: UUID
    ) -> WorkflowDefinition:
        """Activate a workflow definition version.

        Per WEDD Section 9.2 and DSD Section 11, this atomically
        deactivates whichever version is currently active for the same
        ``request_type`` (if any) and activates the target. The
        underlying transaction itself is implemented by
        ``WorkflowDefinitionRepository.activate_definition``; this
        method's own responsibility is validating that the attempt is
        legal (via ``WorkflowEngine.validate_definition_activation``) and
        recording the resulting ``WORKFLOW_DEFINITION_ACTIVATED`` audit
        entry (WEDD Section 14.1).

        Args:
            identity: The authenticated administrator performing the
                activation.
            definition_id: The id of the definition to activate.

        Returns:
            The newly activated ``WorkflowDefinition``.

        Raises:
            PermissionDeniedError: If ``identity`` is not an
                administrator.
            NotFoundError: If no definition with ``definition_id`` exists.
            ConcurrencyError: If the definition is already active, or a
                competing activation was processed first (API-ADD's
                ``409 DUPLICATE_ACTIVATION``, WEDD Section 9.2).
        """
        try:
            authorize_workflow_definition_management(identity)
        except Exception as exc:  # noqa: BLE001
            raise translate_auth_error(exc) from exc

        try:
            candidate = self._workflow_definition_repo.get_by_id_for_company(
                definition_id, company_id=identity.company_id
            )
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc

        currently_active_record = self._workflow_definition_repo.find_active_for_request_type(
            candidate.request_type, company_id=identity.company_id
        )
        candidate_domain = map_workflow_definition_record_to_domain(candidate)
        currently_active_domain = (
            map_workflow_definition_record_to_domain(currently_active_record)
            if currently_active_record is not None
            else None
        )

        try:
            self._workflow_engine.validate_definition_activation(
                candidate_domain, currently_active=currently_active_domain
            )
        except EngineWorkflowError as exc:
            raise translate_workflow_error(exc) from exc

        with TransactionContext(operation_name="activate_workflow_definition") as tx:
            try:
                activated = self._workflow_definition_repo.activate_definition(
                    definition_id,
                    request_type=candidate.request_type,
                    expected_row_version=candidate.row_version,
                    company_id=identity.company_id,
                )
            except DatabaseError as exc:
                raise translate_database_error(exc) from exc

            tx.register_compensation(
                lambda: self._logger.error(
                    "Activation of workflow definition %s partially applied and could not "
                    "be automatically reversed (e.g. the audit entry failed to write after "
                    "the definition itself was activated); manual review required.",
                    definition_id,
                    extra={"definition_id": str(definition_id)},
                )
            )

            try:
                self._audit_repo.record_event(
                    action=AuditAction.WORKFLOW_DEFINITION_ACTIVATED,
                    actor_id=identity.user_id,
                    request_id=None,
                    metadata={
                        "definition_id": str(activated.id),
                        "request_type": activated.request_type,
                        "version": activated.version,
                        "previously_active_definition_id": (
                            str(currently_active_record.id)
                            if currently_active_record is not None
                            else None
                        ),
                    },
                )
            except DatabaseError as exc:
                raise translate_database_error(exc) from exc

        self._logger.info(
            "Activated workflow definition %s (version %d) for request_type=%s",
            activated.id,
            activated.version,
            activated.request_type,
            extra={"definition_id": str(activated.id), "request_type": activated.request_type},
        )
        return map_workflow_definition_record_to_domain(activated)

    @log_calls()
    def list_versions(
        self,
        identity: AuthenticatedIdentity,
        request_type: str,
        *,
        page: Page = Page(),
    ) -> PagedResult[WorkflowDefinition]:
        """List workflow definition versions for a request type.

        Args:
            identity: The authenticated caller. Non-administrators are
                restricted to active definitions only, per API-ADD
                Section 19.9.4.
            request_type: The request type to list versions for.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching ``WorkflowDefinition`` instances.
        """
        from app.models.enums import UserRole  # local import avoids a module-level cycle risk

        is_active_filter: bool | None = None
        if identity.role is not UserRole.ADMIN:
            is_active_filter = True

        try:
            result = self._workflow_definition_repo.list_definitions(
                request_type=request_type,
                company_id=identity.company_id,
                is_active=is_active_filter,
                page=page,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return PagedResult(
            items=[map_workflow_definition_record_to_domain(r) for r in result.items],
            page=result.page,
            page_size=result.page_size,
            total_records=result.total_records,
        )

    @log_calls()
    def search_definitions(
        self,
        identity: AuthenticatedIdentity,
        query_text: str,
        *,
        page: Page = Page(),
    ) -> PagedResult[WorkflowDefinition]:
        """Free-text search across request types, unlike ``list_versions``
        (which requires an exact, already-known request type).

        Used by ``GlobalSearchService``. Applies the identical
        active-only restriction ``list_versions`` already applies to a
        non-administrator (API-ADD Section 19.9.4).

        Args:
            identity: The authenticated caller.
            query_text: The search term.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching ``WorkflowDefinition`` instances.

        Raises:
            ValidationError: If ``query_text`` is empty.
        """
        from app.models.enums import UserRole  # local import avoids a module-level cycle risk

        is_active_filter: bool | None = None
        if identity.role is not UserRole.ADMIN:
            is_active_filter = True

        try:
            result = self._workflow_definition_repo.search_definitions(
                query_text, company_id=identity.company_id, is_active=is_active_filter, page=page
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return PagedResult(
            items=[map_workflow_definition_record_to_domain(r) for r in result.items],
            page=result.page,
            page_size=result.page_size,
            total_records=result.total_records,
        )

    @log_calls()
    def get_active_version(self, request_type: str, *, company_id: UUID) -> WorkflowDefinition:
        """Fetch the currently active workflow definition for a request type.

        Args:
            request_type: The request type to resolve.
            company_id: The company (tenant) to resolve within.

        Returns:
            The active ``WorkflowDefinition``.

        Raises:
            NotFoundError: If no active definition exists for
                ``request_type`` within this company.
        """
        record = self._workflow_definition_repo.find_active_for_request_type(
            request_type, company_id=company_id
        )
        if record is None:
            raise NotFoundError("workflow_definition (active)", request_type)
        return map_workflow_definition_record_to_domain(record)

    def _validate_document(self, definition: dict) -> WorkflowDefinitionDocument:
        """Validate a raw definition dict into a ``WorkflowDefinitionDocument``.

        Args:
            definition: The raw JSON document.

        Returns:
            The validated document.

        Raises:
            ValidationError: If validation fails.
        """
        try:
            return WorkflowDefinitionDocument.model_validate(definition)
        except (PydanticValidationError, DomainError) as exc:
            raise translate_model_construction_error(
                exc, model_name="WorkflowDefinitionDocument"
            ) from exc

    def _validate_assignees(self, document: WorkflowDefinitionDocument) -> None:
        """Validate every ``specific_user`` stage's assignee against known profiles.

        Args:
            document: The document to validate.

        Raises:
            AssignmentError: If any referenced profile id does not exist.
        """
        from app.models.enums import AssignmentStrategy  # local import, narrow use

        referenced_ids = {
            stage.assigned_user_id
            for stage in document.stages
            if stage.assignment_strategy is AssignmentStrategy.SPECIFIC_USER
            and stage.assigned_user_id is not None
        }
        if not referenced_ids:
            self._workflow_engine.validate_definition_assignees(document, frozenset())
            return

        found_ids = {profile.id for profile in self._profile_repo.find_by_ids(list(referenced_ids))}

        try:
            self._workflow_engine.validate_definition_assignees(document, frozenset(found_ids))
        except EngineWorkflowError as exc:
            raise translate_workflow_error(exc) from exc
