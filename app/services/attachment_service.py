"""Application service orchestrating attachment upload, replace, removal,
and read access.

Per DSD Section 7 and API-ADD Section 19.7, this service coordinates
``AttachmentRepository`` (metadata rows), ``AttachmentStorageGateway``
(Supabase Storage file content), ``RequestRepository``/
``WorkflowStageRepository`` (visibility), and ``AuditRepository`` to
implement the full attachment lifecycle. Files themselves never pass
through this service's caller in either direction except as the raw
``bytes`` a Streamlit upload widget already holds in memory — no
attachment content is ever written to, or read from, PostgreSQL.

An attachment's visibility and who may upload one match
``RequestService``'s own request-visibility rule exactly (API-ADD
Section 19.7.1: "Requester, assigned approver, or admin") — this service
therefore reuses ``app.auth.authorization.authorize_request_view``
rather than inventing a second, parallel ownership predicate for the
same population, exactly as ``CommentService`` already does. Removal
uses the already-implemented ``app.auth.authorization.authorize_attachment_removal``
(API-ADD Section 19.7.4: "the original uploader, while the request is
still pending, or admin") — built in an earlier pass of this codebase's
own development, never previously called by any service.

**Upload order matches DSD Section 7.1/11 and API-ADD Section 21.6
exactly**: validate → write to Storage → (virus-scan integration point)
→ insert the ``attachments`` row → insert the audit entry. No
``attachments`` row is ever committed for a file that does not already
exist in Storage; if the row insert fails after a successful Storage
write, this service makes a best-effort attempt to remove the
now-orphaned Storage object rather than leave it unreferenced (a
best-effort cleanup, not a transactional guarantee — see
``_cleanup_orphaned_storage_object``'s own docstring for the honest
limits of what that provides).

**"Replacing" an attachment never mutates a row in place** — it uploads
an entirely new file as a new row (``version`` incremented,
``replaces_attachment_id`` pointing at the row it supersedes) and
soft-deletes the row it replaces, mirroring the same append-only
philosophy already applied to ``comments``. The replaced row's own
Storage object is deliberately *not* deleted (unlike an explicit
removal, which does delete it) — its row still references it, so it
remains available for a future "view previous versions" feature without
any extra bookkeeping now.

**Virus scanning is a real, wired integration point, not a TODO.**
``VirusScanner`` (below) is called once per upload, between the Storage
write and the metadata insert, exactly where API-ADD Section 23 says a
scan step could be inserted. ``NullVirusScanner`` is the only
implementation in this codebase and always reports
``AttachmentScanStatus.SKIPPED`` — never a fabricated "clean" result —
since no scanner is actually integrated in this baseline. A download of
an attachment whose ``scan_status`` is ``INFECTED`` is refused (a real
consequence of this integration point, not merely a recorded value with
no effect), even though ``NullVirusScanner`` itself can never produce
that status.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from app.auth.authentication import AuthenticatedIdentity
from app.auth.authorization import authorize_attachment_removal, authorize_request_view
from app.database.attachment_storage import AttachmentStorageGateway
from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.exceptions import StorageError as _DbStorageError
from app.database.repositories.attachment_repository import AttachmentRecord, AttachmentRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.request_repository import RequestRecord, RequestRepository
from app.database.repositories.workflow_repository import WorkflowStageRepository
from app.models import Attachment
from app.models.enums import AttachmentScanStatus, AuditAction, RequestStatus, UserRole
from app.services.exceptions import (
    NotFoundError,
    ValidationError,
    translate_auth_error,
    translate_database_error,
    translate_file_validation_error,
    translate_storage_error,
)
from app.utils.decorators import log_calls
from app.utils.exceptions import FileValidationError
from app.utils.file_utils import (
    build_storage_path,
    compute_sha256_checksum,
    sanitize_filename,
    validate_content_type,
    validate_content_type_consistency,
    validate_file_size,
)

__all__ = [
    "VirusScanner",
    "ScanResult",
    "NullVirusScanner",
    "map_attachment_record_to_domain",
    "AttachmentService",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScanResult:
    """The outcome of scanning a file's content for malware.

    Attributes:
        status: The resulting scan status.
        detail: A short, human-readable explanation, if relevant (for
            example, the signature name a real scanner matched). ``None``
            for ``NullVirusScanner``, which never has one.
    """

    status: AttachmentScanStatus
    detail: str | None = None


@runtime_checkable
class VirusScanner(Protocol):
    """Structural interface for scanning an attachment's content.

    This is the virus-scan integration point API-ADD Section 23
    describes ("the upload sequence is positioned so a scan step could
    later be inserted"): a real implementation (calling ClamAV,
    VirusTotal, or an equivalent service) can be substituted for
    ``NullVirusScanner`` by dependency injection alone, with no change
    to ``AttachmentService`` itself.
    """

    def scan(self, content: bytes) -> ScanResult:
        """Scan a file's content and report the result.

        Args:
            content: The file's raw content.

        Returns:
            The ``ScanResult``. Implementations are expected never to
            raise for a routine "this file is infected" finding (that is
            a normal, expected result, reported via
            ``ScanResult.status``, not an exception) — an exception
            should be reserved for the scanner itself being unreachable
            or misconfigured.
        """
        ...


class NullVirusScanner:
    """The only ``VirusScanner`` implementation in this codebase.

    Per API-ADD Section 23: "No virus/malware scanning is performed in
    this baseline." This implementation is honest about that — it always
    reports ``AttachmentScanStatus.SKIPPED``, never a fabricated "clean"
    result, so nothing downstream can mistake "not actually scanned" for
    "scanned and found safe."
    """

    def scan(self, content: bytes) -> ScanResult:
        """Report that no scan was performed.

        Args:
            content: The file's raw content (unused).

        Returns:
            A ``ScanResult`` with ``status=AttachmentScanStatus.SKIPPED``.
        """
        del content  # Unused: this implementation inspects nothing.
        return ScanResult(status=AttachmentScanStatus.SKIPPED)


def map_attachment_record_to_domain(record: AttachmentRecord) -> Attachment:
    """Map a persistence-level ``AttachmentRecord`` into its Domain Layer
    ``Attachment`` representation.

    Args:
        record: The record returned by ``AttachmentRepository``.

    Returns:
        The corresponding ``Attachment`` domain model.
    """
    return Attachment(
        id=record.id,
        request_id=record.request_id,
        uploaded_by=record.uploaded_by,
        file_name=record.file_name,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        storage_path=record.storage_path,
        checksum_sha256=record.checksum_sha256,
        version=record.version,
        replaces_attachment_id=record.replaces_attachment_id,
        scan_status=record.scan_status,
        deleted_at=record.deleted_at,
        deleted_by=record.deleted_by,
        created_at=record.created_at,
    )


class AttachmentService:
    """Orchestrates attachment upload, replace, removal, and read access."""

    #: How long a generated download URL remains valid, per API-ADD
    #: Section 19.7.2's "short-lived signed Storage URL."
    _SIGNED_URL_TTL_SECONDS = 300

    def __init__(
        self,
        *,
        attachment_repo: AttachmentRepository,
        storage_gateway: AttachmentStorageGateway,
        request_repo: RequestRepository,
        workflow_stage_repo: WorkflowStageRepository,
        audit_repo: AuditRepository,
        virus_scanner: VirusScanner,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            attachment_repo: Persistence for ``attachments`` metadata rows.
            storage_gateway: Read/write access to attachment file content
                in Supabase Storage.
            request_repo: Persistence for ``requests``, used to resolve
                the parent request for visibility/removal checks.
            workflow_stage_repo: Persistence for ``workflow_stages``, used
                to determine whether the caller is assigned to any stage
                on the parent request.
            audit_repo: Persistence for ``audit_logs``.
            virus_scanner: The virus-scan integration point. Production
                wiring supplies ``NullVirusScanner()`` (see module
                docstring); tests may supply a fake reporting any status.
        """
        self._attachment_repo = attachment_repo
        self._storage_gateway = storage_gateway
        self._request_repo = request_repo
        self._workflow_stage_repo = workflow_stage_repo
        self._audit_repo = audit_repo
        self._virus_scanner = virus_scanner
        self._logger = logging.getLogger(f"{__name__}.AttachmentService")

    @log_calls()
    def upload_attachment(
        self,
        identity: AuthenticatedIdentity,
        request_id: UUID,
        *,
        file_name: str,
        content_type: str,
        content: bytes,
    ) -> Attachment:
        """Upload a new attachment against a request.

        Args:
            identity: The authenticated caller.
            request_id: The request to attach this file to.
            file_name: The original, as-submitted filename.
            content_type: The file's declared MIME type.
            content: The file's raw content.

        Returns:
            The newly created ``Attachment``.

        Raises:
            NotFoundError: If no request with this id exists, or it is
                outside the caller's visibility.
            ValidationError: If the filename cannot be sanitized, the
                content type is not allow-listed, the file is empty or
                too large, or the declared content type contradicts the
                file's sniffed content.
            StorageOperationError: If the Storage write fails.
        """
        self._authorize_view(identity, request_id)
        return self._store_new_attachment(
            identity,
            request_id,
            file_name=file_name,
            content_type=content_type,
            content=content,
            version=1,
            replaces_attachment_id=None,
        )

    @log_calls()
    def replace_attachment(
        self,
        identity: AuthenticatedIdentity,
        attachment_id: UUID,
        *,
        file_name: str,
        content_type: str,
        content: bytes,
    ) -> Attachment:
        """Replace an attachment with a new version of the file.

        Uploads ``content`` as an entirely new attachment (a new row, a
        new Storage object, ``version = existing.version + 1``,
        ``replaces_attachment_id = existing.id``) and soft-deletes the
        attachment it replaces. Authorization matches removal exactly
        (API-ADD Section 19.7.4): the same rule governs "may this caller
        make the existing file no longer the current one" whether the
        end state is "gone" (remove) or "superseded" (replace).

        Args:
            identity: The authenticated caller.
            attachment_id: The attachment to replace.
            file_name: The new file's original filename.
            content_type: The new file's declared MIME type.
            content: The new file's raw content.

        Returns:
            The newly created ``Attachment`` (the new, current version).

        Raises:
            NotFoundError: If no attachment with this id exists.
            PermissionDeniedError: If the caller is neither the original
                uploader (while the request is pending) nor an admin.
            ValidationError: If the new file fails validation.
            StorageOperationError: If the Storage write fails.
        """
        existing = self._get_existing(attachment_id)
        request = self._get_parent_request(identity, existing.request_id)
        self._authorize_removal(identity, existing, request)

        created = self._store_new_attachment(
            identity,
            existing.request_id,
            file_name=file_name,
            content_type=content_type,
            content=content,
            version=existing.version + 1,
            replaces_attachment_id=existing.id,
        )

        try:
            self._attachment_repo.soft_delete(existing.id, deleted_by=identity.user_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._logger.info(
            "Attachment %s replaced by %s (new attachment %s)",
            existing.id,
            identity.user_id,
            created.id,
            extra={"attachment_id": str(existing.id), "new_attachment_id": str(created.id)},
        )
        return created

    @log_calls()
    def remove_attachment(self, identity: AuthenticatedIdentity, attachment_id: UUID) -> Attachment:
        """Remove an attachment: delete its Storage object and soft-delete its row.

        Per DSD Section 7.1, the metadata row is retained (with
        ``deleted_at``/``deleted_by`` populated) even after the
        underlying Storage object has been removed.

        Args:
            identity: The authenticated caller.
            attachment_id: The attachment to remove.

        Returns:
            The updated ``Attachment``, with ``deleted_at``/``deleted_by``
            populated.

        Raises:
            NotFoundError: If no attachment with this id exists.
            PermissionDeniedError: If the caller is neither the original
                uploader (while the request is pending) nor an admin.
            StorageOperationError: If the Storage removal fails.
        """
        existing = self._get_existing(attachment_id)
        request = self._get_parent_request(identity, existing.request_id)
        self._authorize_removal(identity, existing, request)

        try:
            self._storage_gateway.remove(path=existing.storage_path)
        except _DbStorageError as exc:
            raise translate_storage_error(exc) from exc

        try:
            removed = self._attachment_repo.soft_delete(attachment_id, deleted_by=identity.user_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        try:
            self._audit_repo.record_event(
                action=AuditAction.ATTACHMENT_REMOVED,
                actor_id=identity.user_id,
                request_id=existing.request_id,
                metadata={"attachment_id": str(attachment_id), "file_name": existing.file_name},
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._logger.info(
            "Attachment %s removed by %s",
            attachment_id,
            identity.user_id,
            extra={"attachment_id": str(attachment_id)},
        )
        return map_attachment_record_to_domain(removed)

    @log_calls()
    def list_attachments(
        self, identity: AuthenticatedIdentity, request_id: UUID, *, page: Page = Page(size=100)
    ) -> PagedResult[Attachment]:
        """List a request's current (non-removed) attachments, newest first.

        Args:
            identity: The authenticated caller.
            request_id: The request's id.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of the request's attachments.

        Raises:
            NotFoundError: If no request with this id exists, or it is
                outside the caller's visibility.
        """
        self._authorize_view(identity, request_id)

        try:
            result = self._attachment_repo.list_for_request(request_id, page=page)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return PagedResult(
            items=[map_attachment_record_to_domain(r) for r in result.items],
            page=result.page,
            page_size=result.page_size,
            total_records=result.total_records,
        )

    @log_calls()
    def get_download_url(
        self,
        identity: AuthenticatedIdentity,
        attachment_id: UUID,
        *,
        expires_in_seconds: int | None = None,
    ) -> str:
        """Generate a short-lived, signed download URL for an attachment.

        Args:
            identity: The authenticated caller.
            attachment_id: The attachment to download.
            expires_in_seconds: How long the URL remains valid. Defaults
                to ``_SIGNED_URL_TTL_SECONDS``.

        Returns:
            The signed URL.

        Raises:
            NotFoundError: If no attachment with this id exists, or it is
                outside the caller's visibility.
            ValidationError: If the attachment's ``scan_status`` is
                ``INFECTED`` — a real consequence of the virus-scan
                integration point, even though ``NullVirusScanner`` can
                never produce that status itself.
            StorageOperationError: If the Storage call fails.
        """
        existing = self._get_existing(attachment_id)
        self._authorize_view(identity, existing.request_id)
        self._reject_if_infected(existing)

        try:
            return self._storage_gateway.create_signed_url(
                path=existing.storage_path,
                expires_in_seconds=expires_in_seconds or self._SIGNED_URL_TTL_SECONDS,
            )
        except _DbStorageError as exc:
            raise translate_storage_error(exc) from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _store_new_attachment(
        self,
        identity: AuthenticatedIdentity,
        request_id: UUID,
        *,
        file_name: str,
        content_type: str,
        content: bytes,
        version: int,
        replaces_attachment_id: UUID | None,
    ) -> Attachment:
        """Validate, write to Storage, scan, and persist one new attachment row.

        Shared by ``upload_attachment`` (``version=1``) and
        ``replace_attachment`` (``version=existing.version + 1``) — both
        follow the identical validate-then-store sequence; only the
        version bookkeeping differs, which the caller supplies.
        """
        try:
            sanitized_name = sanitize_filename(file_name)
            validate_content_type(content_type)
            validate_file_size(len(content))
            validate_content_type_consistency(content_type, content)
        except FileValidationError as exc:
            raise translate_file_validation_error(exc) from exc

        checksum = compute_sha256_checksum(content)
        attachment_id = uuid4()
        storage_path = build_storage_path(
            request_id=request_id, attachment_id=attachment_id, sanitized_file_name=sanitized_name
        )

        try:
            self._storage_gateway.upload(
                path=storage_path, content=content, content_type=content_type
            )
        except _DbStorageError as exc:
            raise translate_storage_error(exc) from exc

        scan_result = self._virus_scanner.scan(content)
        if scan_result.status is AttachmentScanStatus.INFECTED:
            self._logger.warning(
                "Uploaded file flagged as infected: attachment_id=%s request_id=%s detail=%s",
                attachment_id,
                request_id,
                scan_result.detail,
                extra={"attachment_id": str(attachment_id), "request_id": str(request_id)},
            )

        try:
            created = self._attachment_repo.create_attachment(
                attachment_id=attachment_id,
                request_id=request_id,
                uploaded_by=identity.user_id,
                file_name=file_name,
                content_type=content_type,
                size_bytes=len(content),
                storage_path=storage_path,
                checksum_sha256=checksum,
                version=version,
                replaces_attachment_id=replaces_attachment_id,
                scan_status=scan_result.status,
            )
        except DatabaseError as exc:
            self._cleanup_orphaned_storage_object(storage_path)
            raise translate_database_error(exc) from exc

        try:
            self._audit_repo.record_event(
                action=AuditAction.ATTACHMENT_UPLOADED,
                actor_id=identity.user_id,
                request_id=request_id,
                metadata={"attachment_id": str(created.id), "file_name": file_name},
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._logger.info(
            "Attachment %s uploaded to request %s by %s",
            created.id,
            request_id,
            identity.user_id,
            extra={"attachment_id": str(created.id), "request_id": str(request_id)},
        )
        return map_attachment_record_to_domain(created)

    def _cleanup_orphaned_storage_object(self, storage_path: str) -> None:
        """Best-effort removal of a Storage object whose metadata row
        insert failed.

        This is a best-effort cleanup, not a transactional guarantee:
        the Supabase client this project uses exposes no cross-statement
        rollback spanning Storage and PostgreSQL (the same honest
        limitation documented by
        ``app.services.workflow_definition_service.TransactionContext``).
        If this cleanup call itself fails, the object is left in place as
        a genuinely orphaned Storage object — safely so, since
        ``build_storage_path`` embeds a freshly generated attachment id
        that is never reused, so no future upload can ever collide with
        it; it is left for the periodic orphan-cleanup job API-ADD
        Section 23 describes (not yet implemented anywhere in this
        codebase) to reclaim.
        """
        try:
            self._storage_gateway.remove(path=storage_path)
        except _DbStorageError:
            self._logger.warning(
                "Failed to clean up orphaned Storage object at '%s' after a failed "
                "attachment row insert; it will remain until a future orphan-cleanup pass.",
                storage_path,
                exc_info=True,
            )

    def _reject_if_infected(self, record: AttachmentRecord) -> None:
        """Refuse to serve a download for a file flagged as infected.

        Args:
            record: The attachment to check.

        Raises:
            ValidationError: If ``record.scan_status`` is ``INFECTED``.
        """
        if record.scan_status is AttachmentScanStatus.INFECTED:
            raise ValidationError(
                "This file was flagged as infected during its virus scan and cannot be downloaded."
            )

    def _get_existing(self, attachment_id: UUID) -> AttachmentRecord:
        """Fetch an attachment record, translating a miss into ``NotFoundError``."""
        try:
            return self._attachment_repo.get_by_id(attachment_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc

    def _get_parent_request(
        self, identity: AuthenticatedIdentity, request_id: UUID
    ) -> RequestRecord:
        """Fetch an attachment's parent request record, enforcing the same
        cross-tenant boundary ``RequestService.get_request`` and
        ``_authorize_view`` enforce — this is the removal/replace path's
        only company check (``_authorize_removal`` itself checks
        ownership/role, never company), so it must not be skipped here.

        Args:
            identity: The authenticated caller.
            request_id: The request's id.

        Raises:
            NotFoundError: If no request with this id exists, or it
                belongs to a different company.
        """
        try:
            request = self._request_repo.get_by_id(request_id)
        except RecordNotFoundError as exc:
            raise translate_database_error(exc) from exc
        if request.company_id != identity.company_id:
            raise NotFoundError("request", request_id)
        return request

    def _authorize_removal(
        self, identity: AuthenticatedIdentity, existing: AttachmentRecord, request: RequestRecord
    ) -> None:
        """Enforce that the caller may remove/replace this attachment.

        Args:
            identity: The authenticated caller.
            existing: The attachment being removed or replaced.
            request: The attachment's parent request record.

        Raises:
            PermissionDeniedError: If the caller is neither the original
                uploader (while the request is pending) nor an admin.
        """
        try:
            authorize_attachment_removal(
                identity,
                is_uploader=existing.uploaded_by == identity.user_id,
                request_is_pending=request.status is RequestStatus.PENDING,
            )
        except Exception as exc:  # noqa: BLE001 - translated below
            raise translate_auth_error(exc) from exc

    def _authorize_view(self, identity: AuthenticatedIdentity, request_id: UUID) -> None:
        """Enforce that the caller may view (and therefore upload/list/
        download attachments on) a request, matching
        ``RequestService.get_request``'s identical visibility rule and
        not-found-on-denial behavior.

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
            # unauthorized caller — matching RequestService.get_request
            # and CommentService._authorize_view.
            raise NotFoundError("request", request_id) from exc

    def _is_assigned_to_any_stage(self, request_id: UUID, user_id: UUID, role: UserRole) -> bool:
        """Determine whether a caller is assigned to any stage on a request.

        Duplicates ``RequestService``'s/``CommentService``'s identical
        private helper: each service in this package recomputes this
        small, pure check locally rather than sharing it, consistent
        with this package's existing pattern of not introducing
        cross-service dependencies for a two-line predicate.
        """
        if role not in (UserRole.APPROVER, UserRole.ADMIN):
            return False
        stages = self._workflow_stage_repo.list_for_request(request_id, page=Page(size=100)).items
        return any(stage.assigned_to == user_id or stage.assigned_role == role for stage in stages)
