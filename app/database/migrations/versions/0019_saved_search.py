"""Add ``saved_filters`` and ``search_history`` tables for enterprise-wide search.

Per the user's explicit decision, saved filters and search history are
backend-persisted (per-user, per-company), not the ``localStorage``-only
pattern ``SavedViewsMenu`` uses elsewhere — this syncs across devices and
lets search history power server-side "recent searches" suggestions.

Both tables mirror ``notification_preferences`` (``0016``): RLS as
defense-in-depth even though the backend always reads/writes through the
service-role client. ``saved_filters`` additionally grants/policies
``delete`` (a saved filter, unlike a preference row, must be removable by
its owner) and reuses ``public.set_updated_at()``. ``search_history`` is
append-only (no ``update`` grant/policy — entries are immutable) and,
like ``audit_logs``/``jobs``, has no retention/cleanup job in this pass;
its unbounded growth is a disclosed, deliberate scope boundary.

Revision ID: 0019_saved_search
Revises: 0018_search_indexes
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019_saved_search"
down_revision: str | None = "0018_search_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        create table public.saved_filters (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.profiles(id) on delete cascade,
            company_id uuid not null references public.companies(id) on delete cascade,
            name text not null,
            query_text text not null default '',
            entity_types text[],
            filters jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (user_id, name)
        );
        """)
    op.execute("create index saved_filters_user_id_idx on public.saved_filters (user_id);")

    op.execute("alter table public.saved_filters enable row level security;")
    op.execute(
        "grant select, insert, update, delete on public.saved_filters to authenticated;"
    )
    op.execute("""
        create policy saved_filters_select_own on public.saved_filters
            for select
            to authenticated
            using (user_id = auth.uid());
        """)
    op.execute("""
        create policy saved_filters_insert_own on public.saved_filters
            for insert
            to authenticated
            with check (user_id = auth.uid());
        """)
    op.execute("""
        create policy saved_filters_update_own on public.saved_filters
            for update
            to authenticated
            using (user_id = auth.uid())
            with check (user_id = auth.uid());
        """)
    op.execute("""
        create policy saved_filters_delete_own on public.saved_filters
            for delete
            to authenticated
            using (user_id = auth.uid());
        """)
    op.execute(
        "create trigger set_saved_filters_updated_at before update "
        "on public.saved_filters for each row execute function public.set_updated_at();"
    )

    op.execute("""
        create table public.search_history (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.profiles(id) on delete cascade,
            company_id uuid not null references public.companies(id) on delete cascade,
            query_text text not null,
            entity_types text[],
            result_count integer not null default 0,
            created_at timestamptz not null default now()
        );
        """)
    op.execute(
        "create index search_history_user_id_created_at_idx "
        "on public.search_history (user_id, created_at desc);"
    )

    op.execute("alter table public.search_history enable row level security;")
    op.execute("grant select, insert, delete on public.search_history to authenticated;")
    op.execute("""
        create policy search_history_select_own on public.search_history
            for select
            to authenticated
            using (user_id = auth.uid());
        """)
    op.execute("""
        create policy search_history_insert_own on public.search_history
            for insert
            to authenticated
            with check (user_id = auth.uid());
        """)
    op.execute("""
        create policy search_history_delete_own on public.search_history
            for delete
            to authenticated
            using (user_id = auth.uid());
        """)


def downgrade() -> None:
    op.execute("drop table if exists public.search_history;")
    op.execute(
        "drop trigger if exists set_saved_filters_updated_at on public.saved_filters;"
    )
    op.execute("drop table if exists public.saved_filters;")
