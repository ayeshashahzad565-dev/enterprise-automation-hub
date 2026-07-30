"""Repository for the ``attachments`` table.

Per DSD Section 3.6/7, an ``attachments`` row is a reference to a file
stored in Supabase Storage — this repository persists only that
reference and its metadata; it never touches Storage itself (see
``app.database.attachment_storage.AttachmentStorageGateway`` for that).
An attachment is never edited in place: "replacing" one is a new insert
(a new row, with ``version`` incremented and ``replaces_attachment_id``
set) plus a soft-delete of the row it replaces — the only mutation this
repository ever performs is that unconditional soft-delete, mirroring
``CommentRepository.soft_delete``'s identical reasoning (no concurrent
edits, no ``version``-column optimistic lock needed for the mutation
itself, since ``version`` here means "which upload in the replace chain
this is," not an optimistic-locking column).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.exceptions import InvalidQueryError
from app.database.repositories.base_repository import (
    BaseRepository,
    Page,
    PagedResult,
    escape_ilike_special_characters,
    parse_datetime,
    parse_uuid,
)
from app.models.enums import AttachmentScanStatus
from app.utils.datetime_utils import utc_now

__all__ = ["AttachmentRecord", "AttachmentRepository"]


@dataclass(frozen=True, slots=True)
class AttachmentRecord:
    """An immutable, persistence-level representation of one ``attachments`` row.

    Attributes:
        id: Primary key.
        request_id: The request this attachment belongs to.
        uploaded_by: The user who uploaded this file.
        file_name: The original filename as supplied by the uploader.
        content_type: The file's validated MIME type.
        size_bytes: The file's size in bytes.
        storage_path: The object's path within the attachments Storage
            bucket.
        checksum_sha256: The SHA-256 digest of the file's content.
        version: This attachment's position in its own replace chain.
        replaces_attachment_id: The attachment this one replaces, if any.
        scan_status: The file's virus-scan status.
        deleted_at: Soft-deletion timestamp, if removed.
        deleted_by: The user who removed this attachment, if soft-deleted.
        created_at: Upload timestamp.
    """

    id: UUID
    request_id: UUID
    uploaded_by: UUID
    file_name: str
    content_type: str
    size_bytes: int
    storage_path: str
    checksum_sha256: str
    version: int
    replaces_attachment_id: UUID | None
    scan_status: AttachmentScanStatus
    deleted_at: datetime | None
    deleted_by: UUID | None
    created_at: datetime


def _map_attachment_row(row: dict[str, Any]) -> AttachmentRecord:
    """Map a raw Supabase row dict into an ``AttachmentRecord``."""
    return AttachmentRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        request_id=parse_uuid(row["request_id"]),  # type: ignore[arg-type]
        uploaded_by=parse_uuid(row["uploaded_by"]),  # type: ignore[arg-type]
        file_name=row["file_name"],
        content_type=row["content_type"],
        size_bytes=int(row["size_bytes"]),
        storage_path=row["storage_path"],
        checksum_sha256=row["checksum_sha256"],
        version=int(row["version"]),
        replaces_attachment_id=parse_uuid(row.get("replaces_attachment_id")),
        scan_status=AttachmentScanStatus(row["scan_status"]),
        deleted_at=parse_datetime(row.get("deleted_at")),
        deleted_by=parse_uuid(row.get("deleted_by")),
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


class AttachmentRepository(BaseRepository[AttachmentRecord]):
    """Persistence operations for the ``attachments`` table."""

    table_name = "attachments"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def get_by_id(self, attachment_id: UUID) -> AttachmentRecord:  # type: ignore[override]
        """Fetch an attachment by its id.

        Args:
            attachment_id: The attachment's ``id``.

        Returns:
            The matching ``AttachmentRecord``.

        Raises:
            RecordNotFoundError: If no attachment with this id exists.
        """
        return super().get_by_id(attachment_id, mapper=_map_attachment_row)

    def find_by_id(self, attachment_id: UUID) -> AttachmentRecord | None:  # type: ignore[override]
        """Fetch an attachment by its id, tolerating absence.

        Args:
            attachment_id: The attachment's ``id``.

        Returns:
            The matching ``AttachmentRecord``, or ``None`` if not found.
        """
        return super().find_by_id(attachment_id, mapper=_map_attachment_row)

    def create_attachment(
        self,
        *,
        attachment_id: UUID,
        request_id: UUID,
        uploaded_by: UUID,
        file_name: str,
        content_type: str,
        size_bytes: int,
        storage_path: str,
        checksum_sha256: str,
        version: int = 1,
        replaces_attachment_id: UUID | None = None,
        scan_status: AttachmentScanStatus = AttachmentScanStatus.SKIPPED,
    ) -> AttachmentRecord:
        """Insert a new attachment row.

        Callers (``AttachmentService``) are responsible for having
        already written the corresponding object to Supabase Storage
        successfully before calling this method — per DSD Section 7.1,
        no ``attachments`` row is ever inserted for a file that does not
        exist in Storage. This is also why ``attachment_id`` is supplied
        by the caller rather than left to the table's own
        ``default gen_random_uuid()``: the id must be known *before* the
        Storage write, since it is embedded in ``storage_path`` (DSD
        Section 7.3's ``{attachment_id}_{file_name}`` convention) — the
        caller generates it, builds the Storage path from it, performs
        the Storage write, and only then calls this method with that
        same id.

        Args:
            attachment_id: The id this row will be created with (a
                client-generated UUID, not the table's default).
            request_id: The request this attachment is attached to.
            uploaded_by: The user uploading the file.
            file_name: The original, as-submitted filename.
            content_type: The file's already-validated MIME type.
            size_bytes: The file's already-validated size in bytes.
            storage_path: The path the file was written to in Storage.
            checksum_sha256: The file's SHA-256 checksum.
            version: This attachment's position in its own replace
                chain. Defaults to ``1`` (a fresh upload, not a replace).
            replaces_attachment_id: The attachment this one replaces, if
                any.
            scan_status: The file's virus-scan status at the time this
                row is created.

        Returns:
            The newly created ``AttachmentRecord``.

        Raises:
            ConstraintViolationError: If ``request_id``/``uploaded_by``/
                ``replaces_attachment_id`` does not resolve to an
                existing row, ``storage_path`` collides with an existing
                attachment, or ``size_bytes`` is not strictly positive.
        """
        values: dict[str, Any] = {
            "id": str(attachment_id),
            "request_id": str(request_id),
            "uploaded_by": str(uploaded_by),
            "file_name": file_name,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "storage_path": storage_path,
            "checksum_sha256": checksum_sha256,
            "version": version,
            "replaces_attachment_id": (
                str(replaces_attachment_id) if replaces_attachment_id else None
            ),
            "scan_status": scan_status.value,
        }
        return self.insert(values, mapper=_map_attachment_row)

    def list_for_request(
        self,
        request_id: UUID,
        *,
        include_deleted: bool = False,
        page: Page = Page(size=100),
    ) -> PagedResult[AttachmentRecord]:
        """List a request's attachments, newest first.

        Args:
            request_id: The request's ``id``.
            include_deleted: Whether to include soft-deleted attachments.
                Defaults to ``False`` — unlike a comment thread, a
                removed attachment's whole point is to no longer appear
                where the file list is shown; ``True`` is for an
                administrative/audit view that needs the complete
                history.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of the request's attachments, most
            recently uploaded first.
        """
        builder = self._select("*", count="exact").eq("request_id", str(request_id))
        if not include_deleted:
            builder = builder.is_("deleted_at", "null")
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_attachment_row)

    def search(
        self,
        query_text: str,
        *,
        request_ids: Sequence[UUID] | None = None,
        include_deleted: bool = False,
        page: Page = Page(),
    ) -> PagedResult[AttachmentRecord]:
        """Free-text search across attachment filenames.

        Mirrors ``CommentRepository.search``'s exact shape — attachments
        have no ``company_id`` column of their own (tenancy is inherited
        from the parent request), so ``request_ids`` is how the caller
        (``GlobalSearchService``) scopes this to requests it has already
        authorized the caller to see. Matched against ``file_name`` via
        the ``attachments_file_name_trgm_idx`` trigram index
        (``0018_search_indexes``).

        Args:
            query_text: The search term, matched case-insensitively
                against ``file_name``.
            request_ids: Restrict to attachments on exactly this set of
                requests, if provided.
            include_deleted: Whether to include soft-deleted attachments.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching attachments, newest first.

        Raises:
            InvalidQueryError: If ``query_text`` is empty or whitespace-only.
        """
        if not query_text or not query_text.strip():
            raise InvalidQueryError("search requires a non-empty query_text.")
        pattern = f"%{escape_ilike_special_characters(query_text.strip())}%"
        builder = self._select("*", count="exact").ilike("file_name", pattern)
        if request_ids is not None:
            builder = builder.in_("request_id", [str(i) for i in request_ids])
        if not include_deleted:
            builder = builder.is_("deleted_at", "null")
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_attachment_row)

    def soft_delete(self, attachment_id: UUID, *, deleted_by: UUID) -> AttachmentRecord:
        """Remove an attachment (soft delete).

        Per DSD Section 7.1, the metadata row is retained even after the
        underlying Storage object has been removed — callers
        (``AttachmentService``) are responsible for removing the Storage
        object first, then calling this method. Attachments have no
        ``version``-as-optimistic-lock column (that field means "replace
        chain position" here, per this module's own docstring), so this
        is a plain, unconditional update, mirroring
        ``CommentRepository.soft_delete``.

        Args:
            attachment_id: The attachment's ``id``.
            deleted_by: The user performing the removal.

        Returns:
            The updated ``AttachmentRecord``, with ``deleted_at``/
            ``deleted_by`` populated.

        Raises:
            RecordNotFoundError: If no attachment with this id exists.
        """
        response = self._execute(
            self._query()
            .update({"deleted_at": utc_now().isoformat(), "deleted_by": str(deleted_by)})
            .eq("id", str(attachment_id)),
            operation="soft_delete",
        )
        row = self._single_row(response, identifier=attachment_id)
        return _map_attachment_row(row)
