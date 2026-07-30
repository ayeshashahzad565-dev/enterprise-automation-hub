"""Add the attachments table.

Per DSD Section 3.6/7 and API-ADD Section 10.5/19.7/23, ``attachments``
stores only a reference to a file's content (which lives in Supabase
Storage, never in PostgreSQL) plus its metadata. An attachment is never
edited in place: "replacing" one is a new row (``version`` incremented,
``replaces_attachment_id`` pointing at the row it supersedes) plus a
soft-delete of the row it replaces — the same append-only philosophy
already applied to ``comments`` in ``0004_comments``. ``checksum_sha256``,
``version``, ``replaces_attachment_id``, and ``scan_status`` extend the
column list beyond the original DSD Section 3.6 table (which predates
this feature's build-out) per API-ADD Section 23's checksum requirement
and this feature's version-metadata/virus-scan-integration-point goals.

Grants and RLS mirror ``0004_comments``'s posture: this application's own
repository/service layer runs on the service-role client (bypasses RLS),
so these policies are a defense-in-depth backstop for any caller using
the anon key directly. Two differences from the ``comments`` policy
shape, both intentional:

- **Attachment INSERT is granted to the same population as SELECT**
  (requester or assigned approver), matching API-ADD Section 19.7.1's
  "Requester, assigned approver, or admin" upload rule — broader than
  DSD Section 9.2's RLS table alone suggests (which lists attachment
  INSERT for the submitter only), resolved in favor of the more specific,
  later API-ADD rule, consistent with how ``comments_insert`` already
  covers both populations for the analogous comment-creation action.
- **The uploader may soft-delete their own attachment directly** (not
  only an admin), matching API-ADD Section 19.7.4: "the original
  uploader, while the request is still pending, or admin" — a genuinely
  new RLS shape ``comments`` has no equivalent of (comment moderation is
  admin-only; attachment removal is not).

Revision ID: 0005_attachments
Revises: 0004_comments
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_attachments"
down_revision: str | None = "0004_comments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        create table public.attachments (
            id                       uuid primary key default gen_random_uuid(),
            request_id               uuid not null references public.requests(id) on delete cascade,
            uploaded_by              uuid not null references public.profiles(id) on delete restrict,
            file_name                text not null,
            content_type             text not null,
            size_bytes               bigint not null check (size_bytes > 0),
            storage_path             text not null unique,
            checksum_sha256          text not null,
            version                  integer not null default 1 check (version > 0),
            replaces_attachment_id   uuid references public.attachments(id) on delete set null,
            scan_status              text not null default 'skipped'
                                         check (scan_status in ('skipped', 'clean', 'infected', 'scan_error')),
            deleted_at               timestamptz,
            deleted_by               uuid references public.profiles(id),
            created_at               timestamptz not null default now()
        );
        """)
    op.execute("create index attachments_request_id_idx on public.attachments (request_id);")
    op.execute(
        "create index attachments_replaces_attachment_id_idx "
        "on public.attachments (replaces_attachment_id);"
    )

    op.execute("alter table public.attachments enable row level security;")
    op.execute("grant select, insert on public.attachments to authenticated;")
    op.execute("""
        create policy attachments_select on public.attachments
            for select
            to authenticated
            using (
                public.current_profile_role() = 'admin'
                or exists (
                    select 1 from public.requests r
                    where r.id = attachments.request_id
                      and r.requester_id = auth.uid()
                )
                or exists (
                    select 1 from public.workflow_stages ws
                    where ws.request_id = attachments.request_id
                      and (
                          ws.assigned_to = auth.uid()
                          or ws.assigned_role = public.current_profile_role()
                      )
                )
            );
        """)
    op.execute("""
        create policy attachments_insert on public.attachments
            for insert
            to authenticated
            with check (
                uploaded_by = auth.uid()
                and (
                    exists (
                        select 1 from public.requests r
                        where r.id = attachments.request_id
                          and r.requester_id = auth.uid()
                    )
                    or exists (
                        select 1 from public.workflow_stages ws
                        where ws.request_id = attachments.request_id
                          and (
                              ws.assigned_to = auth.uid()
                              or ws.assigned_role = public.current_profile_role()
                          )
                    )
                )
            );
        """)
    # Removal (soft-delete) touches only deleted_at/deleted_by, per the
    # same "may not delete or alter user-authored content" discipline
    # comments_moderate_admin already applies. Two separate UPDATE
    # policies express the two distinct populations API-ADD Section
    # 19.7.4 grants this to (an admin, for any attachment; the uploader,
    # only for their own and only while the request is still pending) —
    # a single combined policy expression would obscure which rule
    # actually applies to which caller.
    op.execute("grant update on public.attachments to authenticated;")
    op.execute("""
        create policy attachments_moderate_admin on public.attachments
            for update
            to authenticated
            using (public.current_profile_role() = 'admin')
            with check (public.current_profile_role() = 'admin');
        """)
    op.execute("""
        create policy attachments_soft_delete_uploader on public.attachments
            for update
            to authenticated
            using (
                uploaded_by = auth.uid()
                and exists (
                    select 1 from public.requests r
                    where r.id = attachments.request_id
                      and r.status = 'pending'
                )
            )
            with check (uploaded_by = auth.uid());
        """)


def downgrade() -> None:
    op.execute("drop policy if exists attachments_soft_delete_uploader on public.attachments;")
    op.execute("drop policy if exists attachments_moderate_admin on public.attachments;")
    op.execute("drop policy if exists attachments_insert on public.attachments;")
    op.execute("drop policy if exists attachments_select on public.attachments;")
    op.execute("revoke all on public.attachments from authenticated;")
    op.execute("drop table if exists public.attachments;")
