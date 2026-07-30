"""Add the companies table — multi-tenancy foundation.

Per the multi-tenancy conversion plan, a company becomes a first-class
entity: every user belongs to exactly one company, and all data is
scoped to it. This migration only creates the table itself and seeds one
row ("Default Organization") — the target every pre-existing row across
every other table backfills onto in ``0010_company_scoping_columns``,
which is what makes that migration safe and non-destructive against any
already-seeded dev/demo database.

``slug`` is reserved for a future subdomain-based tenant-routing feature
(explicitly out of scope for this conversion — see the plan's "Explicitly
out of scope" section); it is not read or used anywhere yet, kept unique
purely so it is ready to serve that purpose later without a further
schema change.

Revision ID: 0009_companies
Revises: 0008_user_invitations_status_expires_at_index
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009_companies"
down_revision: str | None = "0008_user_invitations_status_expires_at_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        create table public.companies (
            id          uuid primary key default gen_random_uuid(),
            name        text not null check (char_length(name) between 1 and 200),
            slug        text not null unique,
            is_active   boolean not null default true,
            version     integer not null default 1 check (version > 0),
            created_at  timestamptz not null default now(),
            updated_at  timestamptz not null default now()
        );
        """)
    op.execute(
        "create trigger set_companies_updated_at "
        "before update on public.companies "
        "for each row execute function public.set_updated_at();"
    )
    op.execute("""
        insert into public.companies (name, slug)
        values ('Default Organization', 'default-organization');
        """)


def downgrade() -> None:
    op.execute("drop trigger if exists set_companies_updated_at on public.companies;")
    op.execute("drop table if exists public.companies;")
