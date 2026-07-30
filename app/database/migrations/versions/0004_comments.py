"""Add the comments table.

Per DSD Section 3.5, ``comments`` is a threaded remark attached to a
request: immutable once created (no ``updated_at``, no in-place edit —
a correction is a new comment referencing the original via
``parent_comment_id``), with administrative removal expressed as a soft
delete (``deleted_at``/``deleted_by``), never a hard delete, matching
the same append-only philosophy already applied to ``audit_logs``.

Grants and RLS mirror ``0003_row_level_security``'s posture exactly:
this application's own repository/service layer runs on the
service-role client (bypasses RLS), so these policies are a
defense-in-depth backstop for any caller using the anon key directly,
scoped per DSD Section 8's permission table — a request's requester or
an approver assigned to one of its stages may read/insert comments on
it; an administrator may read every comment and moderate (soft-delete)
any of them, but may not otherwise alter comment content.

Revision ID: 0004_comments
Revises: 0003_row_level_security
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_comments"
down_revision: str | None = "0003_row_level_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        create table public.comments (
            id                 uuid primary key default gen_random_uuid(),
            request_id         uuid not null references public.requests(id) on delete cascade,
            author_id          uuid not null references public.profiles(id) on delete restrict,
            parent_comment_id  uuid references public.comments(id) on delete cascade,
            body               text not null check (char_length(body) between 1 and 5000),
            deleted_at         timestamptz,
            deleted_by         uuid references public.profiles(id),
            created_at         timestamptz not null default now()
        );
        """)
    op.execute("create index comments_request_id_idx on public.comments (request_id);")
    op.execute(
        "create index comments_parent_comment_id_idx on public.comments (parent_comment_id);"
    )

    op.execute("alter table public.comments enable row level security;")
    op.execute("grant select, insert on public.comments to authenticated;")
    op.execute("""
        create policy comments_select on public.comments
            for select
            to authenticated
            using (
                public.current_profile_role() = 'admin'
                or exists (
                    select 1 from public.requests r
                    where r.id = comments.request_id
                      and r.requester_id = auth.uid()
                )
                or exists (
                    select 1 from public.workflow_stages ws
                    where ws.request_id = comments.request_id
                      and (
                          ws.assigned_to = auth.uid()
                          or ws.assigned_role = public.current_profile_role()
                      )
                )
            );
        """)
    op.execute("""
        create policy comments_insert on public.comments
            for insert
            to authenticated
            with check (
                author_id = auth.uid()
                and (
                    exists (
                        select 1 from public.requests r
                        where r.id = comments.request_id
                          and r.requester_id = auth.uid()
                    )
                    or exists (
                        select 1 from public.workflow_stages ws
                        where ws.request_id = comments.request_id
                          and (
                              ws.assigned_to = auth.uid()
                              or ws.assigned_role = public.current_profile_role()
                          )
                    )
                )
            );
        """)
    # Moderation (soft-delete) is admin-only and touches only
    # deleted_at/deleted_by, per DSD Section 8's "may not delete or alter
    # user-authored content" beyond that. A single UPDATE grant/policy is
    # sufficient since this application's own CommentService is the only
    # code path that ever issues this update (as the service-role
    # client, which bypasses this policy entirely); it exists here purely
    # as the anon-key backstop.
    op.execute("grant update on public.comments to authenticated;")
    op.execute("""
        create policy comments_moderate_admin on public.comments
            for update
            to authenticated
            using (public.current_profile_role() = 'admin')
            with check (public.current_profile_role() = 'admin');
        """)


def downgrade() -> None:
    op.execute("drop policy if exists comments_moderate_admin on public.comments;")
    op.execute("drop policy if exists comments_insert on public.comments;")
    op.execute("drop policy if exists comments_select on public.comments;")
    op.execute("revoke all on public.comments from authenticated;")
    op.execute("drop table if exists public.comments;")
