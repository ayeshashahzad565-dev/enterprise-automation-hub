"""Enterprise-wide search: trigram + full-text indexes.

``app.services.search_service.GlobalSearchService`` (originally built for
the since-removed Streamlit UI) has always deliberately stopped short of
provisioning a trigram/full-text index, per its own docstring: "a real
infrastructure decision this feature does not make unilaterally." This
migration makes that decision, combining two complementary techniques:

1. ``pg_trgm`` GIN indexes on every free-text column the repository layer
   already filters with ``.ilike('%term%')`` (``search_requests``,
   ``search_definitions``, ``search_by_name``, ``list_for_recipient``'s
   ``search`` param, ``AuditRepository.search``, and the two new search
   methods added for notifications/attachments alongside this feature) —
   Postgres can use a trigram GIN index for a leading-wildcard ``ILIKE``,
   unlike a plain btree index, so this requires no query-code changes at
   all for those columns.
2. Generated ``tsvector`` columns + GIN indexes on the two entities with
   real prose bodies (``requests``, ``comments``), enabling genuine
   stemmed, multi-word full-text search (``@@ websearch_to_tsquery``) —
   something substring ``ILIKE`` can never provide (e.g. "run" matching
   "running"). Generated columns recompute automatically on write; no
   trigger is needed, unlike this migration's own-table siblings that use
   ``set_updated_at``.

Every other searchable column (``workflow_definitions.request_type``,
``profiles.full_name``, ``notifications.message``, ``attachments.file_name``,
``audit_logs.action``) is a short, single-field label rather than prose,
where trigram substring matching is the right tool — no ``tsvector`` is
added for these, avoiding redundant indexing.

Revision ID: 0018_search_indexes
Revises: 0017_platform_admin
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_search_indexes"
down_revision: str | None = "0017_platform_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("create extension if not exists pg_trgm;")

    op.execute(
        "create index requests_title_trgm_idx "
        "on public.requests using gin (title gin_trgm_ops);"
    )
    op.execute(
        "create index requests_description_trgm_idx "
        "on public.requests using gin (description gin_trgm_ops);"
    )
    op.execute(
        "create index comments_body_trgm_idx "
        "on public.comments using gin (body gin_trgm_ops);"
    )
    op.execute(
        "create index workflow_definitions_request_type_trgm_idx "
        "on public.workflow_definitions using gin (request_type gin_trgm_ops);"
    )
    op.execute(
        "create index profiles_full_name_trgm_idx "
        "on public.profiles using gin (full_name gin_trgm_ops);"
    )
    op.execute(
        "create index notifications_message_trgm_idx "
        "on public.notifications using gin (message gin_trgm_ops);"
    )
    op.execute(
        "create index attachments_file_name_trgm_idx "
        "on public.attachments using gin (file_name gin_trgm_ops);"
    )
    op.execute(
        "create index audit_logs_action_trgm_idx "
        "on public.audit_logs using gin (action gin_trgm_ops);"
    )

    op.execute("""
        alter table public.requests add column search_vector tsvector
            generated always as (
                setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(description, '')), 'B')
            ) stored;
        """)
    op.execute(
        "create index requests_search_vector_idx "
        "on public.requests using gin (search_vector);"
    )

    op.execute("""
        alter table public.comments add column search_vector tsvector
            generated always as (to_tsvector('english', coalesce(body, ''))) stored;
        """)
    op.execute(
        "create index comments_search_vector_idx "
        "on public.comments using gin (search_vector);"
    )


def downgrade() -> None:
    op.execute("drop index if exists comments_search_vector_idx;")
    op.execute("alter table public.comments drop column if exists search_vector;")
    op.execute("drop index if exists requests_search_vector_idx;")
    op.execute("alter table public.requests drop column if exists search_vector;")

    op.execute("drop index if exists audit_logs_action_trgm_idx;")
    op.execute("drop index if exists attachments_file_name_trgm_idx;")
    op.execute("drop index if exists notifications_message_trgm_idx;")
    op.execute("drop index if exists profiles_full_name_trgm_idx;")
    op.execute("drop index if exists workflow_definitions_request_type_trgm_idx;")
    op.execute("drop index if exists comments_body_trgm_idx;")
    op.execute("drop index if exists requests_description_trgm_idx;")
    op.execute("drop index if exists requests_title_trgm_idx;")
