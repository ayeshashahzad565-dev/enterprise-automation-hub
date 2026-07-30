"""Platform Administration module: company soft-delete/settings, licenses, feature flags.

Per the Platform Administration module's design: suspending a company
(``is_active=false``, already existed) is made meaningful by
``app.auth.supabase_verifier.SupabaseTokenVerifier`` (application-layer
enforcement, not RLS); deleting a company is soft (``deleted_at``/
``deleted_by``, mirroring ``requests``' own soft-delete convention) so
tenant data is never destroyed by a platform-admin mistake.

``company_licenses`` and ``feature_flags`` are platform infrastructure
state, never tenant-facing — RLS enabled and forced, with no grant to
``authenticated`` at all, exactly mirroring the ``jobs`` table's
precedent (``0015_jobs``): every consumer (the new repositories, the
platform-admin-only API) uses the service-role client, which bypasses
RLS.

Revision ID: 0017_platform_admin
Revises: 0016_notification_preferences
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_platform_admin"
down_revision: str | None = "0016_notification_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        alter table public.companies
            add column deleted_at timestamptz,
            add column deleted_by uuid references public.profiles(id),
            add column contact_email text,
            add column notes text;
        """)
    op.execute("create index companies_deleted_at_idx on public.companies (deleted_at);")

    op.execute("""
        create table public.company_licenses (
            company_id uuid primary key references public.companies(id) on delete cascade,
            plan_tier text not null default 'free',
            seat_limit integer,
            expires_at timestamptz,
            notes text,
            updated_at timestamptz not null default now(),
            updated_by uuid references public.profiles(id)
        );
        """)
    op.execute(
        "create trigger set_company_licenses_updated_at before update "
        "on public.company_licenses for each row execute function public.set_updated_at();"
    )

    op.execute("""
        create table public.feature_flags (
            key text primary key,
            description text not null,
            enabled boolean not null default false,
            updated_at timestamptz not null default now(),
            updated_by uuid references public.profiles(id)
        );
        """)
    op.execute(
        "create trigger set_feature_flags_updated_at before update "
        "on public.feature_flags for each row execute function public.set_updated_at();"
    )

    op.execute("alter table public.company_licenses enable row level security;")
    op.execute("alter table public.company_licenses force row level security;")
    op.execute("alter table public.feature_flags enable row level security;")
    op.execute("alter table public.feature_flags force row level security;")


def downgrade() -> None:
    op.execute("drop trigger if exists set_feature_flags_updated_at on public.feature_flags;")
    op.execute("drop table if exists public.feature_flags;")
    op.execute(
        "drop trigger if exists set_company_licenses_updated_at on public.company_licenses;"
    )
    op.execute("drop table if exists public.company_licenses;")
    op.execute("drop index if exists companies_deleted_at_idx;")
    op.execute("""
        alter table public.companies
            drop column if exists notes,
            drop column if exists contact_email,
            drop column if exists deleted_by,
            drop column if exists deleted_at;
        """)
