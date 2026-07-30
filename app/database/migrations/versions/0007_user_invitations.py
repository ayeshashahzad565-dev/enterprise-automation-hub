"""Add the user_invitations table.

Per the Enterprise User Onboarding architecture (Milestone 1), this
application owns its own invitation record and its own opaque token —
the Supabase Auth user (and, in turn, the ``profiles`` row provisioned by
``0002_auth_profile_trigger``) is created only when an invitation is
accepted, never at invite time. ``user_invitations`` therefore has no
foreign key relationship to ``auth.users`` for the invitee — only
``invited_by`` (the inviting admin) and, once accepted,
``accepted_profile_id`` (the resulting profile) reference ``profiles``.

``status`` is a plain, checked ``text`` column rather than a native
Postgres enum, matching the ``attachments.scan_status`` precedent
(``0005_attachments``) used for smaller, less-core vocabularies — this
avoids an ``ALTER TYPE ... ADD VALUE`` migration if a future status is
ever added. Notably, ``'expired'`` is *not* one of the persisted values:
expiry is derived from ``expires_at`` at read time by the Application
Layer, so no background sweep is required to keep ``status`` accurate.

The partial unique index on ``lower(email) where status = 'pending'``
enforces "at most one live invitation per email" at the database level,
closing the race between two admins concurrently inviting the same
address — not just an application-level check.

Grants and RLS mirror every prior migration's posture: this
application's own repository layer runs on the service-role client
(bypasses RLS), so the policy below is a defense-in-depth backstop for
any caller using the anon key directly, not the primary enforcement
mechanism (that is ``app.auth.rbac.require_role(..., UserRole.ADMIN)``
at the Application/API layer).

Revision ID: 0007_user_invitations
Revises: 0006_notification_archive
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_user_invitations"
down_revision: str | None = "0006_notification_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        create table public.user_invitations (
            id                    uuid primary key default gen_random_uuid(),
            email                 text not null,
            full_name             text not null,
            role                  public.user_role not null default 'employee',
            department            text,
            token_hash            text not null,
            status                text not null default 'pending'
                                      check (status in ('pending', 'accepted', 'revoked')),
            invited_by            uuid not null references public.profiles(id),
            expires_at            timestamptz not null,
            accepted_at           timestamptz,
            revoked_at            timestamptz,
            accepted_profile_id   uuid references public.profiles(id),
            resend_count          integer not null default 0 check (resend_count >= 0),
            version               integer not null default 1 check (version > 0),
            created_at            timestamptz not null default now(),
            updated_at            timestamptz not null default now()
        );
        """)

    # Backs InvitationRepository.find_by_token_hash — the lookup the
    # public validate/accept endpoints (a future milestone) hinge on.
    op.execute(
        "create unique index user_invitations_token_hash_idx "
        "on public.user_invitations (token_hash);"
    )
    op.execute("create index user_invitations_status_idx on public.user_invitations (status);")
    op.execute("create index user_invitations_email_idx on public.user_invitations (lower(email));")
    # At most one live (pending) invitation per email address at a time.
    op.execute(
        "create unique index user_invitations_pending_email_idx "
        "on public.user_invitations (lower(email)) where status = 'pending';"
    )

    op.execute("""
        create trigger set_user_invitations_updated_at
        before update on public.user_invitations
        for each row execute function public.set_updated_at();
        """)

    op.execute("alter table public.user_invitations enable row level security;")
    op.execute("grant select, insert, update on public.user_invitations to authenticated;")
    op.execute("""
        create policy user_invitations_admin_all on public.user_invitations
            for all
            to authenticated
            using (public.current_profile_role() = 'admin')
            with check (public.current_profile_role() = 'admin');
        """)


def downgrade() -> None:
    op.execute("drop policy if exists user_invitations_admin_all on public.user_invitations;")
    op.execute("revoke all on public.user_invitations from authenticated;")
    op.execute("drop trigger if exists set_user_invitations_updated_at on public.user_invitations;")
    op.execute("drop index if exists user_invitations_pending_email_idx;")
    op.execute("drop index if exists user_invitations_email_idx;")
    op.execute("drop index if exists user_invitations_status_idx;")
    op.execute("drop index if exists user_invitations_token_hash_idx;")
    op.execute("drop table if exists public.user_invitations;")
