"""Domain models for the ``attachments`` table.

Per DSD Section 3.6/7 and API-ADD Section 10.5, an attachment is a file
uploaded against a request: the file's bytes live only in Supabase
Storage (never in PostgreSQL); this table stores only a reference to
that Storage object plus metadata. An attachment is never edited in
place — "replacing" one is modeled as uploading a new file (a new row,
with ``version`` incremented and ``replaces_attachment_id`` pointing at
the row it supersedes) and soft-deleting the old one, exactly the same
append-only philosophy already applied to ``comments``. Corresponds to
the persistence layer's
``app.database.repositories.attachment_repository.AttachmentRepository``.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.models.base import IdentifiedModel, SoftDeletableModel, TimestampedModel
from app.models.enums import AttachmentScanStatus

__all__ = ["Attachment"]


class Attachment(IdentifiedModel, TimestampedModel, SoftDeletableModel):
    """A fully validated, persisted representation of an ``attachments`` row.

    Mirrors the column list in DSD Section 3.6 (extended with
    ``checksum_sha256``, per API-ADD Section 10.5/23, and ``version``/
    ``replaces_attachment_id``/``scan_status``, added by this feature —
    see the module housing the migration for the full rationale) and
    corresponds directly to
    ``app.database.repositories.attachment_repository.AttachmentRecord``.

    Attributes:
        request_id: The request this attachment belongs to.
        uploaded_by: The user who uploaded this file.
        file_name: The original filename as supplied by the uploader
            (not sanitized — the sanitized form only ever appears inside
            ``storage_path``; a human-facing display always uses this
            field).
        content_type: The file's MIME type, already validated against
            ``app.config.security.ALLOWED_ATTACHMENT_CONTENT_TYPES`` and
            cross-checked against the file's own sniffed magic bytes
            before this row was ever created.
        size_bytes: The file's size in bytes. Always ``> 0`` (DSD Section
            4.1's check constraint).
        storage_path: The object's path within the single Supabase
            Storage bucket (``app.config.security.ATTACHMENTS_STORAGE_BUCKET``),
            per the ``attachments/{request_id}/{attachment_id}_{name}``
            convention fixed in DSD Section 7.3. Unique across every
            attachment ever uploaded.
        checksum_sha256: The SHA-256 digest of the file's content,
            computed at upload time (API-ADD Section 23).
        version: This attachment's position in its own replace chain,
            starting at 1. A "replace" creates a new row with
            ``version = previous.version + 1``; the previous row is
            soft-deleted, never mutated.
        replaces_attachment_id: The attachment this one was uploaded to
            replace, if any. ``None`` for a version-1 attachment.
        scan_status: The file's virus-scan status. Always ``SKIPPED`` in
            this baseline, since no scanner is integrated — see
            ``AttachmentScanStatus``'s own docstring.
    """

    request_id: UUID
    uploaded_by: UUID
    file_name: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    size_bytes: int = Field(gt=0)
    storage_path: str = Field(min_length=1)
    checksum_sha256: str = Field(min_length=1)
    version: int = Field(ge=1)
    replaces_attachment_id: UUID | None = None
    scan_status: AttachmentScanStatus
