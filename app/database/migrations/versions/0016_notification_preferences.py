"""Add the ``notification_preferences`` table.

Per the Enterprise Notification Center's per-event settings requirement:
each user may independently toggle, per ``notification_type``, whether
they receive that event in-app at all (``in_app_enabled``) and whether
that event also emails them (``email_enabled``). No row for a given
``(user_id, notification_type)`` pair means "use the default" — both
``True`` — which is exactly today's unconditional behavior, so a user who
never visits the preferences page sees no change at all.

RLS mirrors ``notifications_select_own``/``notifications_update_own``
(``0003_row_level_security.py``) exactly, even though (like every other
repository in this codebase) the backend always reads/writes through the
service-role client, which bypasses RLS — this is the same "defense in
depth" convention already established for every other user-owned table.

Reuses the existing ``public.set_updated_at()`` trigger function
(``0001_initial_schema.py``) rather than redefining it.

Revision ID: 0016_notification_preferences
Revises: 0015_jobs
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016_notification_preferences"
down_revision: str | None = "0015_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        create table public.notification_preferences (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.profiles(id) on delete cascade,
            notification_type text not null,
            in_app_enabled boolean not null default true,
            email_enabled boolean not null default true,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (user_id, notification_type)
        );
        """)
    op.execute(
        "create index notification_preferences_user_id_idx "
        "on public.notification_preferences (user_id);"
    )

    op.execute("alter table public.notification_preferences enable row level security;")
    op.execute("grant select, insert, update on public.notification_preferences to authenticated;")
    op.execute("""
        create policy notification_preferences_select_own on public.notification_preferences
            for select
            to authenticated
            using (user_id = auth.uid());
        """)
    op.execute("""
        create policy notification_preferences_insert_own on public.notification_preferences
            for insert
            to authenticated
            with check (user_id = auth.uid());
        """)
    op.execute("""
        create policy notification_preferences_update_own on public.notification_preferences
            for update
            to authenticated
            using (user_id = auth.uid())
            with check (user_id = auth.uid());
        """)

    op.execute(
        "create trigger set_notification_preferences_updated_at "
        "before update on public.notification_preferences "
        "for each row execute function public.set_updated_at();"
    )


def downgrade() -> None:
    op.execute(
        "drop trigger if exists set_notification_preferences_updated_at "
        "on public.notification_preferences;"
    )
    op.execute("drop table if exists public.notification_preferences;")
