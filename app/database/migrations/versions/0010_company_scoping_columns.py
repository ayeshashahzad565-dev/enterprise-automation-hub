"""Add company_id scoping columns, backfill, and company-scoped constraints.

Adds ``company_id`` to every table that needs to be queried directly by
company without already going through a ``request_id``/single-recipient
path (per the multi-tenancy conversion plan's design decision 4):
``profiles``, ``workflow_definitions``, ``requests``, ``workflow_stages``,
``user_invitations`` (all ``not null``), and ``audit_logs`` (nullable — a
genuinely platform-level audit event, e.g. a company's own creation, has
no single owning company). ``comments`` and ``attachments`` deliberately
get no column: every repository query against them is already
``request_id``-scoped, with the calling service always having already
loaded and authorized the parent ``Request`` first, so company scoping is
inherited transitively; their RLS policies are extended in
``0011_company_scoping_functions_and_rls`` via the join they already
perform against ``requests``, at zero schema cost. ``notifications``
likewise gets no column — every query against it is already scoped to a
single ``recipient_id``, who belongs to exactly one company by
construction, so no cross-tenant leak is possible without one.

Each column is added nullable first, backfilled onto the seed company
inserted by ``0009_companies``, then tightened to ``not null`` — the
standard safe sequence for adding a required column to tables that may
already hold data (this repo's seed/demo scripts populate these tables,
so this migration must not assume they are empty).

Also widens two uniqueness rules that were platform-global to be
per-company: ``workflow_definitions``' "(request_type, version) unique"
and "at most one active version per request_type" both gain a
``company_id`` component, and ``user_invitations``' "at most one pending
invitation per email" becomes "...per email, per company" — a disclosed
judgment call: the same email may now be invited to two different
companies, just not twice to the same one while pending.

Finally adds ``profiles.is_platform_admin`` — an orthogonal flag (not a
new ``UserRole`` tier, so it can never accidentally satisfy an existing
``role is UserRole.ADMIN`` business-permission check) gating the small,
new set of platform-only company-management endpoints introduced
alongside this conversion.

Revision ID: 0010_company_scoping_columns
Revises: 0009_companies
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_company_scoping_columns"
down_revision: str | None = "0009_companies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOT_NULL_TABLES = (
    "profiles",
    "workflow_definitions",
    "requests",
    "workflow_stages",
    "user_invitations",
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # company_id: nullable -> backfill -> not null, for every table that
    # requires it. audit_logs stays nullable (see module docstring).
    # ------------------------------------------------------------------
    for table in _NOT_NULL_TABLES:
        op.execute(
            f"alter table public.{table} "
            "add column company_id uuid references public.companies(id);"
        )
        op.execute(
            f"update public.{table} set company_id = "  # nosec B608 - table is from the fixed, hardcoded _NOT_NULL_TABLES tuple above, never user input
            "(select id from public.companies where slug = 'default-organization') "
            "where company_id is null;"
        )
        op.execute(f"alter table public.{table} alter column company_id set not null;")

    op.execute(
        "alter table public.audit_logs "
        "add column company_id uuid references public.companies(id);"
    )
    op.execute(
        "update public.audit_logs set company_id = "
        "(select id from public.companies where slug = 'default-organization') "
        "where company_id is null;"
    )

    # ------------------------------------------------------------------
    # Supporting indexes, matching each table's existing indexing style.
    # ------------------------------------------------------------------
    op.execute("create index profiles_company_id_idx on public.profiles (company_id);")
    op.execute(
        "create index workflow_definitions_company_id_idx "
        "on public.workflow_definitions (company_id);"
    )
    op.execute("create index requests_company_id_idx on public.requests (company_id);")
    op.execute(
        "create index workflow_stages_company_id_idx on public.workflow_stages (company_id);"
    )
    op.execute(
        "create index user_invitations_company_id_idx on public.user_invitations (company_id);"
    )
    op.execute("create index audit_logs_company_id_idx on public.audit_logs (company_id);")

    # ------------------------------------------------------------------
    # workflow_definitions: both uniqueness rules become per-company.
    # ------------------------------------------------------------------
    op.execute("drop index if exists workflow_definitions_active_uidx;")
    op.execute(
        "create unique index workflow_definitions_active_uidx "
        "on public.workflow_definitions (company_id, request_type) where is_active;"
    )
    op.execute(
        "alter table public.workflow_definitions "
        "drop constraint workflow_definitions_type_version_uq;"
    )
    op.execute(
        "alter table public.workflow_definitions "
        "add constraint workflow_definitions_company_type_version_uq "
        "unique (company_id, request_type, version);"
    )

    # ------------------------------------------------------------------
    # user_invitations: pending-email uniqueness becomes per-company.
    # ------------------------------------------------------------------
    op.execute("drop index if exists user_invitations_pending_email_idx;")
    op.execute(
        "create unique index user_invitations_pending_email_idx "
        "on public.user_invitations (lower(email), company_id) where status = 'pending';"
    )

    # ------------------------------------------------------------------
    # Platform-admin bootstrap flag.
    # ------------------------------------------------------------------
    op.execute(
        "alter table public.profiles "
        "add column is_platform_admin boolean not null default false;"
    )


def downgrade() -> None:
    op.execute("alter table public.profiles drop column if exists is_platform_admin;")

    op.execute("drop index if exists user_invitations_pending_email_idx;")
    op.execute(
        "create unique index user_invitations_pending_email_idx "
        "on public.user_invitations (lower(email)) where status = 'pending';"
    )

    op.execute(
        "alter table public.workflow_definitions "
        "drop constraint if exists workflow_definitions_company_type_version_uq;"
    )
    op.execute(
        "alter table public.workflow_definitions "
        "add constraint workflow_definitions_type_version_uq unique (request_type, version);"
    )
    op.execute("drop index if exists workflow_definitions_active_uidx;")
    op.execute(
        "create unique index workflow_definitions_active_uidx "
        "on public.workflow_definitions (request_type) where is_active;"
    )

    op.execute("drop index if exists audit_logs_company_id_idx;")
    op.execute("drop index if exists user_invitations_company_id_idx;")
    op.execute("drop index if exists workflow_stages_company_id_idx;")
    op.execute("drop index if exists requests_company_id_idx;")
    op.execute("drop index if exists workflow_definitions_company_id_idx;")
    op.execute("drop index if exists profiles_company_id_idx;")

    op.execute("alter table public.audit_logs drop column if exists company_id;")
    for table in reversed(_NOT_NULL_TABLES):
        op.execute(f"alter table public.{table} drop column if exists company_id;")
