"""Add the composite index the production-readiness audit flagged as
missing: ``profiles (company_id, role, department)``.

``ProfileRepository.list_by_role`` (used by ``AssignmentResolver``'s
``department_queue`` strategy — WEDD Section 7.3, and by the admin user
directory) always filters on ``role`` *and* ``company_id`` together, with
``department`` as a common third predicate. The only indexes that existed
before this migration were a plain single-column ``company_id`` index
(``0010_company_scoping_columns``) and a pre-multi-tenancy composite
``(role, department)`` index with no ``company_id`` component at all
(``0001_initial_schema``, predating the company-scoping retrofit) — the
same gap already closed for ``requests``/``workflow_stages`` in
``0012_analytics_company_scoped_indexes`` and
``0021_analytics_department_and_type_indexes``, just not yet for
``profiles``.

Purely additive: neither existing index is touched or removed.

Revision ID: 0023_profiles_company_role_department_index
Revises: 0022_analytics_aggregation_functions
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023_profiles_company_role_department_index"
down_revision: str | None = "0022_analytics_aggregation_functions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "create index profiles_company_id_role_department_idx "
        "on public.profiles (company_id, role, department);"
    )


def downgrade() -> None:
    op.execute("drop index if exists profiles_company_id_role_department_idx;")
