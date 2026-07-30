"""Enable RLS on companies; FORCE ROW LEVEL SECURITY everywhere RLS exists.

Milestone 13's production-readiness audit found two related gaps:

1. ``companies`` (added in ``0009_companies``) never had Row-Level
   Security enabled at all — inconsistent with every other table's
   explicit-by-default posture (``0003_row_level_security``'s own
   documented philosophy: "a bare table with no grant would still deny
   all access" — true today only because nothing yet grants
   ``authenticated`` access to it, which is a trap for a future
   migration that adds a grant without remembering RLS). This migration
   enables RLS and adds a single, narrow ``select``-only policy scoped
   to the caller's own company (via ``current_profile_company()``,
   ``0011_company_scoping_functions_and_rls``) — company management
   itself (create/update) remains exclusively a service-role,
   platform-admin-gated operation (``CompanyService``), so no
   insert/update/delete grant is added.
2. No table anywhere in this schema uses ``FORCE ROW LEVEL SECURITY``.
   RLS is already correctly bypassed by the service-role client's
   ``BYPASSRLS`` role attribute — ``FORCE`` has no effect on a role with
   that attribute, so this migration changes nothing about the
   application's actual behavior. What ``FORCE`` adds is protection
   against a *different, latent* gap: a connection authenticated as the
   tables' owner (e.g. a future direct ``psql`` session, migration
   role, or admin tool) bypasses RLS by default even without
   ``BYPASSRLS`` unless ``FORCE`` is set. This migration applies
   ``FORCE ROW LEVEL SECURITY`` to every table RLS has ever been enabled
   on, closing that gap uniformly rather than only for the new
   ``companies`` policy above.

Revision ID: 0014_companies_rls_and_force_rls
Revises: 0013_audit_logs_action_index
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_companies_rls_and_force_rls"
down_revision: str | None = "0013_audit_logs_action_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Every table RLS has been enabled on across this schema's history —
#: 0003 (profiles, workflow_definitions, requests, workflow_stages,
#: notifications, audit_logs), 0004 (comments), 0005 (attachments),
#: 0007 (user_invitations), plus companies (this migration).
_RLS_TABLES: tuple[str, ...] = (
    "profiles",
    "workflow_definitions",
    "requests",
    "workflow_stages",
    "notifications",
    "audit_logs",
    "comments",
    "attachments",
    "user_invitations",
    "companies",
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # companies — a caller may see only their own company's row. Writes
    # (create/update) remain exclusively a service-role, platform-admin
    # operation (CompanyService), so no write grant/policy is added.
    # ------------------------------------------------------------------
    op.execute("alter table public.companies enable row level security;")
    op.execute("grant select on public.companies to authenticated;")
    op.execute("""
        create policy companies_select_own on public.companies
            for select
            to authenticated
            using (id = public.current_profile_company());
        """)

    # ------------------------------------------------------------------
    # FORCE ROW LEVEL SECURITY everywhere RLS is enabled — see module
    # docstring. No effect on the service-role client (BYPASSRLS always
    # wins); closes the table-owner-connection gap for every other case.
    # ------------------------------------------------------------------
    for table in _RLS_TABLES:
        op.execute(
            f"alter table public.{table} force row level security;"
        )  # nosec B608 - table is from the fixed _RLS_TABLES tuple above, never user input


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(
            f"alter table public.{table} no force row level security;"
        )  # nosec B608 - table is from the fixed _RLS_TABLES tuple above, never user input

    op.execute("drop policy if exists companies_select_own on public.companies;")
    op.execute("revoke select on public.companies from authenticated;")
    op.execute("alter table public.companies disable row level security;")
