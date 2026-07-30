"""Repository for the ``comments`` table.

Per DSD Section 3.5, ``comments`` is a threaded remark attached to a
request. This module defines the ``CommentRepository`` class. A comment
is immutable once created (no ``updated_at``, no in-place edit path);
the only mutation this repository ever performs is the administrative
soft-delete moderation path, via a plain unconditional update — a
comment is never concurrently edited by multiple parties the way a
``requests``/``workflow_stages`` row can be, so there is no ``version``
column and no optimistic-locking predicate here, mirroring
``NotificationRepository.mark_read``'s identical reasoning.
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
    quote_postgrest_filter_value,
)
from app.utils.datetime_utils import utc_now

__all__ = ["CommentRecord", "CommentRepository"]


@dataclass(frozen=True, slots=True)
class CommentRecord:
    """An immutable, persistence-level representation of one ``comments``
    row (DSD Section 3.5).

    Attributes:
        id: Primary key.
        request_id: The request this comment is attached to.
        author_id: The user who wrote the comment.
        parent_comment_id: The comment this one replies to, if any.
        body: The comment's content.
        deleted_at: The soft-deletion (moderation) timestamp, if removed.
        deleted_by: The administrator who removed the comment, if
            soft-deleted.
        created_at: Comment creation timestamp.
    """

    id: UUID
    request_id: UUID
    author_id: UUID
    parent_comment_id: UUID | None
    body: str
    deleted_at: datetime | None
    deleted_by: UUID | None
    created_at: datetime


def _map_comment_row(row: dict[str, Any]) -> CommentRecord:
    """Map a raw Supabase row dict into a ``CommentRecord``."""
    return CommentRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        request_id=parse_uuid(row["request_id"]),  # type: ignore[arg-type]
        author_id=parse_uuid(row["author_id"]),  # type: ignore[arg-type]
        parent_comment_id=parse_uuid(row.get("parent_comment_id")),
        body=row["body"],
        deleted_at=parse_datetime(row.get("deleted_at")),
        deleted_by=parse_uuid(row.get("deleted_by")),
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


class CommentRepository(BaseRepository[CommentRecord]):
    """Persistence operations for the ``comments`` table.

    Corresponds to ``CommentService``'s persistence needs (API-ADD
    Section 19.6).
    """

    table_name = "comments"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def get_by_id(self, comment_id: UUID) -> CommentRecord:  # type: ignore[override]
        """Fetch a comment by its id.

        Args:
            comment_id: The comment's ``id``.

        Returns:
            The matching ``CommentRecord``.

        Raises:
            RecordNotFoundError: If no comment with this id exists or is
                visible under the current client's RLS context.
        """
        return super().get_by_id(comment_id, mapper=_map_comment_row)

    def find_by_id(self, comment_id: UUID) -> CommentRecord | None:  # type: ignore[override]
        """Fetch a comment by its id, tolerating absence.

        Used to validate a candidate ``parent_comment_id`` (API-ADD
        Section 19.6.1's ``PARENT_COMMENT_NOT_FOUND`` rule) without
        raising for the common "no such comment" case.

        Args:
            comment_id: The comment's ``id``.

        Returns:
            The matching ``CommentRecord``, or ``None`` if not found.
        """
        return super().find_by_id(comment_id, mapper=_map_comment_row)

    def create_comment(
        self,
        *,
        request_id: UUID,
        author_id: UUID,
        body: str,
        parent_comment_id: UUID | None = None,
    ) -> CommentRecord:
        """Insert a new comment row.

        Args:
            request_id: The request this comment is attached to.
            author_id: The user writing the comment.
            body: The comment's content (1-5,000 characters, validated
                by the Domain Layer, not here).
            parent_comment_id: The comment being replied to, if any.
                Existence and same-request validation is the
                Application Layer's responsibility (API-ADD Section
                19.6.1), not this method's.

        Returns:
            The newly created ``CommentRecord``.

        Raises:
            ConstraintViolationError: If ``request_id``, ``author_id``,
                or ``parent_comment_id`` does not resolve to an existing
                row.
        """
        values: dict[str, Any] = {
            "request_id": str(request_id),
            "author_id": str(author_id),
            "body": body,
            "parent_comment_id": str(parent_comment_id) if parent_comment_id else None,
        }
        return self.insert(values, mapper=_map_comment_row)

    def list_for_request(
        self, request_id: UUID, *, page: Page = Page(size=100)
    ) -> PagedResult[CommentRecord]:
        """List a request's comment thread in creation order.

        Corresponds to ``GET /api/v1/requests/{id}/comments`` (API-ADD
        Section 19.6.2).

        Args:
            request_id: The request's ``id``.
            page: The page to retrieve. Defaults to a page size of 100,
                since a request's comment thread is expected to be
                small enough to typically fit in a single page.

        Returns:
            A ``PagedResult`` of the request's comments, oldest first.
        """
        builder = (
            self._select("*", count="exact").eq("request_id", str(request_id)).order("created_at")
        )
        return self.paginate(builder, page, mapper=_map_comment_row)

    def search(
        self,
        query_text: str,
        *,
        request_ids: Sequence[UUID] | None = None,
        include_deleted: bool = False,
        page: Page = Page(),
    ) -> PagedResult[CommentRecord]:
        """Free-text search across comment bodies.

        Matches either a literal substring (``ILIKE``, backed by the
        ``comments_body_trgm_idx`` trigram index from ``0018_search_indexes``)
        or a stemmed word via the generated ``search_vector`` column
        (backed by ``comments_search_vector_idx``), mirroring
        ``RequestRepository.search_requests``'s identical two-mode
        matching and the same escaping/quoting rationale.

        Args:
            query_text: The search term. Matched case-insensitively
                against ``body``.
            request_ids: Restrict to comments on exactly this set of
                requests, if provided. The caller (``GlobalSearchService``)
                is responsible for computing an already-authorized set —
                this repository performs no visibility scoping of its own,
                per this package's usual layering.
            include_deleted: Whether to include administratively removed
                (soft-deleted) comments.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching comments, newest first.

        Raises:
            InvalidQueryError: If ``query_text`` is empty or whitespace-only.
        """
        if not query_text or not query_text.strip():
            raise InvalidQueryError("search requires a non-empty query_text.")
        pattern = f"%{escape_ilike_special_characters(query_text.strip())}%"
        quoted_pattern = quote_postgrest_filter_value(pattern)
        quoted_query = quote_postgrest_filter_value(query_text.strip())
        builder = self._select("*", count="exact").or_(
            f"body.ilike.{quoted_pattern},search_vector.wfts(english).{quoted_query}"
        )
        if request_ids is not None:
            builder = builder.in_("request_id", [str(i) for i in request_ids])
        if not include_deleted:
            builder = builder.is_("deleted_at", "null")
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_comment_row)

    def soft_delete(self, comment_id: UUID, *, deleted_by: UUID) -> CommentRecord:
        """Administratively remove a comment (soft delete).

        Corresponds to ``DELETE /api/v1/comments/{id}`` (API-ADD Section
        19.6.3). Per DSD Section 3.5, a comment has no ``version``
        column and is never concurrently edited, so this is a plain,
        unconditional update rather than an optimistic-locking one,
        mirroring ``NotificationRepository.mark_read``.

        Args:
            comment_id: The comment's ``id``.
            deleted_by: The administrator performing the removal.

        Returns:
            The updated ``CommentRecord``, with ``deleted_at``/
            ``deleted_by`` populated.

        Raises:
            RecordNotFoundError: If no comment with this id exists.
        """
        response = self._execute(
            self._query()
            .update(
                {
                    "deleted_at": utc_now().isoformat(),
                    "deleted_by": str(deleted_by),
                }
            )
            .eq("id", str(comment_id)),
            operation="soft_delete",
        )
        row = self._single_row(response, identifier=comment_id)
        return _map_comment_row(row)
