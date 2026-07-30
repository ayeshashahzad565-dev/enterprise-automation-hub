"""Supabase Storage gateway for attachment file content.

Per DSD Section 7's "files themselves never pass through the database;
only references do" principle, this module is the sole place in the
codebase that calls the Supabase Storage SDK (``storage3``, exposed via
``DatabaseClient.storage``). It is deliberately a separate class from
``app.database.repositories.attachment_repository.AttachmentRepository``
(which persists only the ``attachments`` table's metadata rows): Storage
and PostgreSQL are two distinct Supabase subsystems, reached through two
distinct SDK surfaces with two distinct failure modes, mirroring how
``NotificationService`` is injected with a separate ``EmailSender``
collaborator rather than folding SMTP concerns into
``NotificationRepository``.

``storage3`` raises its own ``StorageApiError`` — not a Postgrest/
PostgreSQL exception — so it cannot be translated by
``BaseRepository._translate_and_raise``. This module is where that raw,
third-party exception type is caught and translated into this
codebase's own ``app.database.exceptions.StorageError``, exactly the
role ``BaseRepository`` plays for every table-backed repository.
"""

from __future__ import annotations

import logging

from app.config.security import ATTACHMENTS_STORAGE_BUCKET
from app.database.client import DatabaseClient
from app.database.exceptions import StorageError

__all__ = ["AttachmentStorageGateway"]

logger = logging.getLogger(__name__)


class AttachmentStorageGateway:
    """Reads and writes attachment file content in Supabase Storage."""

    def __init__(self, client: DatabaseClient, *, bucket: str = ATTACHMENTS_STORAGE_BUCKET) -> None:
        """Initialize the gateway.

        Args:
            client: Any object satisfying the ``DatabaseClient`` protocol
                (only its ``.storage`` property is used here).
            bucket: The Storage bucket to operate against. Defaults to
                ``app.config.security.ATTACHMENTS_STORAGE_BUCKET``. This
                bucket must already exist (an operator-provisioned step,
                like a database migration — see ``docs/deployment.md``);
                this gateway never attempts to create it.
        """
        self._client = client
        self._bucket = bucket
        self._logger = logging.getLogger(f"{__name__}.AttachmentStorageGateway")

    def upload(self, *, path: str, content: bytes, content_type: str) -> None:
        """Write a file's content to Storage.

        Args:
            path: The object's path within the bucket (per DSD Section
                7.3's convention, already computed by the caller).
            content: The file's raw content.
            content_type: The file's already-validated MIME type.

        Raises:
            StorageError: If the underlying Storage write fails.
        """
        try:
            self._client.storage.from_(self._bucket).upload(
                path, content, file_options={"content-type": content_type}
            )
        except Exception as exc:  # noqa: BLE001 - translated below
            self._raise(exc, operation="upload", path=path)

    def download(self, *, path: str) -> bytes:
        """Read a file's content from Storage.

        Args:
            path: The object's path within the bucket.

        Returns:
            The file's raw content.

        Raises:
            StorageError: If the underlying Storage read fails (for
                example, no object exists at ``path``).
        """
        try:
            return self._client.storage.from_(self._bucket).download(path)
        except Exception as exc:  # noqa: BLE001 - translated below
            self._raise(exc, operation="download", path=path)
            raise  # pragma: no cover - _raise always raises

    def remove(self, *, path: str) -> None:
        """Remove a file from Storage.

        Args:
            path: The object's path within the bucket.

        Raises:
            StorageError: If the underlying Storage removal fails.
        """
        try:
            self._client.storage.from_(self._bucket).remove([path])
        except Exception as exc:  # noqa: BLE001 - translated below
            self._raise(exc, operation="remove", path=path)

    def create_signed_url(self, *, path: str, expires_in_seconds: int) -> str:
        """Create a short-lived, signed download URL for a file.

        Corresponds to ``GET /api/v1/attachments/{id}/download`` (API-ADD
        Section 19.7.2): "Retrieve a short-lived signed Storage URL."

        Args:
            path: The object's path within the bucket.
            expires_in_seconds: How long the URL remains valid.

        Returns:
            The signed URL.

        Raises:
            StorageError: If the underlying Storage call fails, or
                returns a response with no signed URL.
        """
        try:
            response = self._client.storage.from_(self._bucket).create_signed_url(
                path, expires_in_seconds
            )
        except Exception as exc:  # noqa: BLE001 - translated below
            self._raise(exc, operation="create_signed_url", path=path)
            raise  # pragma: no cover - _raise always raises

        url = response.get("signedURL") or response.get("signedUrl")
        if not url:
            raise StorageError(
                "Supabase Storage did not return a signed URL.", bucket=self._bucket, path=path
            )
        return str(url)

    def _raise(self, exc: Exception, *, operation: str, path: str) -> None:
        """Translate a raw Storage SDK failure into ``StorageError``.

        Args:
            exc: The exception raised by the underlying ``storage3`` SDK.
            operation: A short, human-readable operation name, used only
                for logging.
            path: The object path the operation was attempted against.

        Raises:
            StorageError: Always. This method never returns normally.
        """
        self._logger.warning(
            "Storage operation '%s' failed for bucket=%s path=%s: %s",
            operation,
            self._bucket,
            path,
            exc,
            exc_info=exc,
        )
        raise StorageError(
            f"Storage operation '{operation}' failed for '{path}'.",
            bucket=self._bucket,
            path=path,
        ) from exc
