"""Application service orchestrating comment creation, reads, and moderation.

Per the API Design Document (Section 19.6) and DSD Section 3.5, this
service coordinates ``CommentRepository``, ``RequestRepository``,
``WorkflowStageRepository``, and ``AuditRepository`` to implement adding
a comment (optionally as a threaded reply), listing a request's comment
thread, and administrative moderation (soft-delete).

A comment's visibility and who may add one match ``RequestService``'s
own request-visibility rule exactly (API-ADD Section 6.2: an employee
may comment on their own requests; an approver may comment on requests
they are assigned to review; an admin may comment on, and moderate, any
request/comment) — this service therefore reuses
``app.auth.authorization.authorize_request_view`` rather than inventing
a second, parallel ownership predicate for the same population.
"""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError

from app.auth.authentication import AuthenticatedIdentity
from app.auth.authorization import authorize_comment_moderation, authorize_request_view
from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.comment_repository import CommentRecord, CommentRepository
from app.database.repositories.request_repository import RequestRepository
from app.database.repositories.workflow_repository import WorkflowStageRepository
from app.models import Comment, CommentCreate
from app.models.enums import AuditAction, UserRole
from app.models.exceptions import DomainError
from app.services.exceptions import (
    NotFoundError,
    ValidationError,
    translate_auth_error,
    translate_database_error,
    translate_model_construction_error,
)
from app.utils.decorators import log_calls

__all__ = ["map_comment_record_to_domain", "CommentService"]

logger = logging.getLogger(__name__)


def map_comment_record_to_domain(record: CommentRecord) -> Comment:
    """Map a persistence-level ``CommentRecord`` into its Domain Layer
    ``Comment`` representation.

    Args:
        record: The record returned by ``CommentRepository``.

    Returns:
        The corresponding ``Comment`` domain model.
    """
    return Comment(
        id=record.id,
        request_id=record.request_id,
        author_id=record.author_id,
        parent_comment_id=record.parent_comment_id,
        body=record.body,
        deleted_at=record.deleted_at,
        deleted_by=record.deleted_by,
        created_at=record.created_at,
    )


class CommentService:
    """Orchestrates comment creation, thread reads, and moderation."""

    def __init__(
        self,
        *,
        comment_repo: CommentRepository,
        request_repo: RequestRepository,
        workflow_stage_repo: WorkflowStageRepository,
        audit_repo: AuditRepository,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            comment_repo: Persistence for ``comments``.
            request_repo: Persistence for ``requests``, used to resolve
                the parent request for visibility checks.
            workflow_stage_repo: Persistence for ``workflow_stages``,
                used to determine whether the caller is assigned to any
                stage on the parent request.
            audit_repo: Persistence for ``audit_logs``.
        """
        self._comment_repo = comment_repo
        self._request_repo = request_repo
        self._workflow_stage_repo = workflow_stage_repo
        self._audit_repo = audit_repo
        self._logger = logging.getLogger(f"{__name__}.CommentService")

    @log_calls()
    def list_comments(
        self, identity: AuthenticatedIdentity, request_id: UUID, *, page: Page = Page(size=100)
    ) -> PagedResult[Comment]:
        """List a request's comment thread in creation order.

        Args:
            identity: The authenticated caller.
            request_id: The request's id.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of the request's comments, oldest first.
            Soft-deleted comments are included (not filtered out), so a
            reply thread remains contextually intact; the Presentation
            Layer is responsible for rendering a removed comment's
            tombstoned state rather than its ``body``.

        Raises:
            NotFoundError: If no request with this id exists, or it
                exists but is outside the caller's visibility (API-ADD
                Section 11.2 — reported as not-found, never as a
                permission failure, to avoid confirming the resource's
                existence to an unauthorized caller).
        """
        self._authorize_view(identity, request_id)

        try:
            result = self._comment_repo.list_for_request(request_id, page=page)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return PagedResult(
            items=[map_comment_record_to_domain(r) for r in result.items],
            page=result.page,
            page_size=result.page_size,
            total_records=result.total_records,
        )

    @log_calls()
    def add_comment(
        self,
        identity: AuthenticatedIdentity,
        request_id: UUID,
        *,
        body: str,
        parent_comment_id: UUID | None = None,
    ) -> Comment:
        """Add a comment, or reply to one, on a request.

        Per DSD Section 11 ("Comment creation"), the comment insert and
        its corresponding ``audit_logs`` entry are treated as a single
        logical unit — this method never returns having written one but
        not the other, per this codebase's established
        ``TransactionContext``-adjacent discipline for such pairs (see
        ``app.services.workflow_definition_service.TransactionContext``'s
        own docstring for the honest limits of what that guarantees
        against the finalized Supabase client).

        Args:
            identity: The authenticated caller.
            request_id: The request to comment on.
            body: The comment's content (1-5,000 characters).
            parent_comment_id: The comment being replied to, if any.

        Returns:
            The newly created ``Comment``.

        Raises:
            ValidationError: If ``body`` fails shape validation, or
                ``parent_comment_id`` does not reference an existing,
                non-deleted comment on the same request (API-ADD
                Section 19.6.1's ``PARENT_COMMENT_NOT_FOUND`` rule).
            NotFoundError: If no request with this id exists, or it is
                outside the caller's visibility.
        """
        try:
            payload = CommentCreate(body=body, parent_comment_id=parent_comment_id)
        except (PydanticValidationError, DomainError) as exc:
            raise translate_model_construction_error(exc, model_name="CommentCreate") from exc

        self._authorize_view(identity, request_id)

        if payload.parent_comment_id is not None:
            parent = self._comment_repo.find_by_id(payload.parent_comment_id)
            if parent is None or parent.deleted_at is not None or parent.request_id != request_id:
                raise ValidationError(
                    "parent_comment_id does not reference an existing, non-deleted "
                    "comment on this request."
                )

        try:
            created = self._comment_repo.create_comment(
                request_id=request_id,
                author_id=identity.user_id,
                body=payload.body,
                parent_comment_id=payload.parent_comment_id,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        try:
            self._audit_repo.record_event(
                action=AuditAction.COMMENT_CREATED,
                actor_id=identity.user_id,
                request_id=request_id,
                metadata={"comment_id": str(created.id)},
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._logger.info(
            "Comment %s added to request %s by %s",
            created.id,
            request_id,
            identity.user_id,
            extra={"comment_id": str(created.id), "request_id": str(request_id)},
        )
        return map_comment_record_to_domain(created)

    @log_calls()
    def remove_comment(self, identity: AuthenticatedIdentity, comment_id: UUID) -> Comment:
        """Administratively remove (soft-delete) a comment.

        Args:
            identity: The authenticated administrator performing the
                removal.
            comment_id: The comment's id.

        Returns:
            The updated ``Comment``, with ``deleted_at``/``deleted_by``
            populated.

        Raises:
            NotFoundError: If no comment with this id exists, or its
                parent request belongs to a different company.
            PermissionDeniedError: If the caller is not an administrator
                (API-ADD Section 19.6.3).
        """
        try:
            existing = self._comment_repo.get_by_id(comment_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc

        # authorize_comment_moderation only checks role (admin), with no
        # company comparison of its own — CommentRecord has no company_id
        # of its own either, so this must be checked against the parent
        # request explicitly, exactly like _authorize_view does, or an
        # admin from any company could moderate any other company's
        # comments by id alone.
        try:
            parent_request = self._request_repo.get_by_id(existing.request_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        if parent_request.company_id != identity.company_id:
            raise NotFoundError("comment", comment_id)

        try:
            authorize_comment_moderation(identity)
        except Exception as exc:  # noqa: BLE001 - translated below
            raise translate_auth_error(exc) from exc

        try:
            removed = self._comment_repo.soft_delete(comment_id, deleted_by=identity.user_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        try:
            self._audit_repo.record_event(
                action=AuditAction.COMMENT_REMOVED,
                actor_id=identity.user_id,
                request_id=existing.request_id,
                metadata={"comment_id": str(comment_id)},
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._logger.info(
            "Comment %s removed by administrator %s",
            comment_id,
            identity.user_id,
            extra={"comment_id": str(comment_id)},
        )
        return map_comment_record_to_domain(removed)

    def _authorize_view(self, identity: AuthenticatedIdentity, request_id: UUID) -> None:
        """Enforce that the caller may view (and therefore comment on)
        a request, matching ``RequestService.get_request``'s identical
        visibility rule and not-found-on-denial behavior.

        Args:
            identity: The authenticated caller.
            request_id: The request's id.

        Raises:
            NotFoundError: If no request with this id exists, or it
                belongs to a different company, or is outside the
                caller's visibility.
        """
        try:
            request = self._request_repo.get_by_id(request_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        # Cross-tenant check first, exactly matching RequestService
        # .get_request's ordering: a request from another company must
        # be indistinguishable from one that doesn't exist at all, before
        # any same-company visibility rule (requester/approver/admin) is
        # even considered.
        if request.company_id != identity.company_id:
            raise NotFoundError("request", request_id)

        is_requester = request.requester_id == identity.user_id
        is_assigned_approver = self._is_assigned_to_any_stage(
            request_id, identity.user_id, identity.role
        )

        try:
            authorize_request_view(
                identity, is_requester=is_requester, is_assigned_approver=is_assigned_approver
            )
        except Exception as exc:  # noqa: BLE001
            # Per API-ADD Section 11.2, an out-of-scope resource is
            # reported as not-found, never as a permission failure, to
            # avoid confirming the resource's existence to an
            # unauthorized caller — matching RequestService.get_request.
            raise NotFoundError("request", request_id) from exc

    def _is_assigned_to_any_stage(self, request_id: UUID, user_id: UUID, role: UserRole) -> bool:
        """Determine whether a caller is assigned to any stage on a request.

        Duplicates ``RequestService``'s identical private helper: each
        service in this package recomputes this small, pure check
        locally rather than sharing it, consistent with this package's
        existing pattern of not introducing cross-service dependencies
        for a two-line predicate.

        Args:
            request_id: The request's id.
            user_id: The caller's id.
            role: The caller's role.

        Returns:
            ``True`` if the caller is a specific assignee, or an
            eligible role-based assignee, on any stage belonging to this
            request.
        """
        if role not in (UserRole.APPROVER, UserRole.ADMIN):
            return False
        stages = self._workflow_stage_repo.list_for_request(request_id, page=Page(size=100)).items
        return any(stage.assigned_to == user_id or stage.assigned_role == role for stage in stages)
