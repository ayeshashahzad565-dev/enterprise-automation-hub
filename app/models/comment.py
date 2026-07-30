"""Domain models for the ``comments`` table.

Per DSD Section 3.5, ``comments`` is a threaded remark attached to a
request. A comment is immutable once created — there is no
``updated_at`` and no in-place edit path anywhere in this package; a
correction is modeled as a new comment referencing the original via
``parent_comment_id``, never an edit. Administrative removal is a soft
delete (``deleted_at``/``deleted_by``), per ``SoftDeletableModel``.
Corresponds to the persistence layer's
``app.database.repositories.comment_repository.CommentRepository``.
"""

from __future__ import annotations

from uuid import UUID

from app.models.base import (
    CommentBody,
    EAHBaseModel,
    IdentifiedModel,
    SoftDeletableModel,
    TimestampedModel,
)

__all__ = ["Comment", "CommentCreate"]


class Comment(IdentifiedModel, TimestampedModel, SoftDeletableModel):
    """A fully validated, persisted representation of a ``comments`` row.

    Mirrors DSD Section 3.5's column list exactly and corresponds
    directly to
    ``app.database.repositories.comment_repository.CommentRecord``.

    Attributes:
        request_id: The request this comment is attached to.
        author_id: The user who wrote the comment.
        parent_comment_id: The comment this one replies to, if any
            (self-referencing thread, DSD Section 3.5).
        body: The comment's content (1-5,000 characters).
    """

    request_id: UUID
    author_id: UUID
    parent_comment_id: UUID | None = None
    body: CommentBody


class CommentCreate(EAHBaseModel):
    """Input model for ``POST /api/v1/requests/{id}/comments`` (API-ADD
    Section 19.6.1).

    ``request_id`` (from the URL path) and ``author_id`` (from the
    authenticated caller) are deliberately not fields here — per API-ADD
    Section 19.6.1, the request body itself carries only ``body`` and an
    optional ``parent_comment_id``; the Application Layer supplies the
    other two.

    Attributes:
        body: The comment's content (1-5,000 characters after
            whitespace stripping).
        parent_comment_id: The comment being replied to, if any. Must
            reference an existing, non-deleted comment on the same
            request, verified by ``CommentService`` (not by this model),
            since that check requires a database read.
    """

    body: CommentBody
    parent_comment_id: UUID | None = None
