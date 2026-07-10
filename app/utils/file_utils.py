"""File-handling utilities for attachment processing.

Per API-ADD Section 23 and the Deployment Guide's file-upload hardening
section (DG Section 19.6), every uploaded attachment is subject to
filename sanitization, a content-type allow-list check, a size limit, and
a checksum computation before its metadata is persisted. This module
provides each of those checks as an independent, pure, reusable function,
plus the storage-path construction convention fixed in DSD Section 7.3.

This module performs no I/O of its own — it operates entirely on
in-memory ``bytes``/``str`` values passed in by the caller, which is
expected to be the component (outside this package's current scope) that
actually reads an uploaded file and writes it to Supabase Storage.
"""

from __future__ import annotations

import hashlib
import re
from uuid import UUID

from app.config.security import ALLOWED_ATTACHMENT_CONTENT_TYPES, MAX_ATTACHMENT_SIZE_BYTES
from app.utils.exceptions import FileValidationError

__all__ = [
    "sanitize_filename",
    "build_storage_path",
    "compute_sha256_checksum",
    "validate_content_type",
    "validate_file_size",
    "sniff_content_type",
    "get_file_extension",
]

#: Characters stripped from a filename during sanitization: path
#: separators (forward and back slash), null bytes, and other ASCII
#: control characters (0x00-0x1F and 0x7F), per DSD Section 7.3's
#: requirement that a sanitized filename never enables path traversal or
#: injects unexpected characters into a Storage path.
_UNSAFE_FILENAME_PATTERN = re.compile(r"[\\/\x00-\x1f\x7f]")

#: Magic-byte signatures for the subset of the attachment allow-list that
#: can be reliably identified from their leading bytes alone. Formats not
#: represented here (plain text, CSV) have no reliable universal
#: signature and are intentionally left unsniffable by this function —
#: per API-ADD Section 23, the declared content type is treated as "a
#: hint, not a trusted assertion" for those formats, and callers should
#: apply the content-type allow-list check as the primary safeguard for
#: them.
_MAGIC_BYTE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    # Modern Office Open XML formats (.docx, .xlsx) are ZIP containers;
    # this signature confirms "this is a ZIP-based Office document" but
    # cannot, from the leading bytes alone, distinguish .docx from
    # .xlsx — a caller sniffing one of those two declared types should
    # treat a match here as consistent with either, and rely on the
    # content-type allow-list check for the final decision.
    (b"PK\x03\x04", "application/zip"),
)


def sanitize_filename(filename: str) -> str:
    """Sanitize a user-supplied filename for safe inclusion in a Storage path.

    Strips path separators, null bytes, and other control characters, and
    collapses the result's surrounding whitespace, per DSD Section 7.3:
    "Path separators (/, \\), null bytes, and control characters are
    stripped."

    Args:
        filename: The original, as-submitted filename.

    Returns:
        The sanitized filename, safe to embed in a storage path.

    Raises:
        FileValidationError: If sanitization would leave an empty string
            (for example, a filename consisting entirely of path
            separators).
    """
    sanitized = _UNSAFE_FILENAME_PATTERN.sub("", filename).strip()
    if not sanitized:
        raise FileValidationError(
            f"Filename '{filename}' is empty after sanitization; a valid file name is required."
        )
    return sanitized


def build_storage_path(*, request_id: UUID, attachment_id: UUID, sanitized_file_name: str) -> str:
    """Construct an attachment's Supabase Storage path.

    Matches the exact convention fixed in DSD Section 7.3:
    ``attachments/{request_id}/{attachment_id}_{sanitized_file_name}``.

    Args:
        request_id: The id of the request this attachment belongs to.
        attachment_id: The id of the attachment row this file corresponds
            to.
        sanitized_file_name: A filename already sanitized via
            ``sanitize_filename``. This function does not re-sanitize its
            input; callers must sanitize first.

    Returns:
        The full storage path.
    """
    return f"attachments/{request_id}/{attachment_id}_{sanitized_file_name}"


def compute_sha256_checksum(content: bytes) -> str:
    """Compute the SHA-256 checksum of file content.

    Matches API-ADD Section 23's checksum-validation requirement: "A
    SHA-256 checksum is computed over the file content at upload time."

    Args:
        content: The raw file content.

    Returns:
        The lowercase hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(content).hexdigest()


def validate_content_type(
    content_type: str,
    *,
    allowed_content_types: frozenset[str] = ALLOWED_ATTACHMENT_CONTENT_TYPES,
) -> str:
    """Validate that a declared content type is on the attachment allow-list.

    Args:
        content_type: The declared MIME type.
        allowed_content_types: The set of acceptable MIME types. Defaults
            to ``app.config.security.ALLOWED_ATTACHMENT_CONTENT_TYPES``.

    Returns:
        ``content_type``, unchanged.

    Raises:
        FileValidationError: If ``content_type`` is not in
            ``allowed_content_types``.
    """
    if content_type not in allowed_content_types:
        raise FileValidationError(
            f"Content type '{content_type}' is not permitted for attachments."
        )
    return content_type


def validate_file_size(
    size_bytes: int, *, max_size_bytes: int = MAX_ATTACHMENT_SIZE_BYTES
) -> int:
    """Validate that a file's size is positive and within the configured limit.

    Matches DSD Section 4.1's ``size_bytes > 0`` check constraint and
    API-ADD Section 23's maximum-size rule.

    Args:
        size_bytes: The file's size in bytes.
        max_size_bytes: The maximum acceptable size. Defaults to
            ``app.config.security.MAX_ATTACHMENT_SIZE_BYTES``.

    Returns:
        ``size_bytes``, unchanged.

    Raises:
        FileValidationError: If ``size_bytes`` is not positive, or
            exceeds ``max_size_bytes``.
    """
    if size_bytes <= 0:
        raise FileValidationError(f"File size must be positive, got {size_bytes} bytes.")
    if size_bytes > max_size_bytes:
        raise FileValidationError(
            f"File size {size_bytes} bytes exceeds the maximum of {max_size_bytes} bytes."
        )
    return size_bytes


def sniff_content_type(content: bytes) -> str | None:
    """Attempt to identify a file's content type from its leading bytes.

    Realizes API-ADD Section 23's MIME-sniffing requirement: "the
    client-supplied Content-Type is treated as a hint, not a trusted
    assertion." This function inspects a bounded prefix of ``content``
    against a fixed table of known magic-byte signatures.

    Args:
        content: The file's raw content. Only the leading bytes are
            inspected; the full content need not be passed, though doing
            so is harmless.

    Returns:
        The sniffed MIME type if a known signature matched, or ``None``
        if the content's type could not be determined from its byte
        signature (which is expected, and not itself an error, for
        formats such as plain text or CSV that have no reliable
        universal signature).
    """
    for signature, mime_type in _MAGIC_BYTE_SIGNATURES:
        if content.startswith(signature):
            return mime_type
    return None


def get_file_extension(filename: str) -> str:
    """Extract a filename's extension, lowercased and without the leading dot.

    Args:
        filename: The filename to inspect.

    Returns:
        The lowercase extension (e.g. ``"pdf"``), or an empty string if
        ``filename`` has no extension.
    """
    if "." not in filename:
        return ""
    return filename.rsplit(".", maxsplit=1)[-1].lower()