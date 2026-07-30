"""Add composite indexes for the now company-scoped Analytics Layer queries.

Milestone 11 made every ``AnalyticsRepository``/``AuditRepository.list_all``/
``ApprovalRepository.list_pending_for_approver``/``list_overdue_stages``
aggregate query filter on ``company_id`` unconditionally, in combination
with exactly one other column: ``status`` (``count_requests_by_status``,
the two approval-queue queries), or a ``created_at`` range
(``count_requests_by_type``/``count_requests_by_department``/
``approval_throughput``/``get_request_trend``, and the "Recent Activity"/
"my activity" audit feeds' default, unfiltered-by-action case).

``0010_company_scoping_columns`` already added a plain, single-column
index on ``company_id`` for each of these tables; that index alone leaves
the query planner to bitmap-AND it against the pre-existing single-column
``status``/``created_at`` indexes from ``0001_initial_schema``, which is
correct but less efficient than a single composite index once every one
of these queries is guaranteed to filter both columns together (per this
milestone's own review requirement: "add indexes only where justified").
This migration is purely additive — it does not touch or remove any
existing index — mirroring this repo's established pattern of composite
indexes for a table's actual hot combined-filter queries (e.g.
``workflow_stages_assigned_to_status_idx``, ``requests_active_created_at_idx``).

Revision ID: 0012_analytics_company_scoped_indexes
Revises: 0011_company_scoping_functions_and_rls
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_analytics_company_scoped_indexes"
down_revision: str | None = "0011_company_scoping_functions_and_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "create index requests_company_id_status_idx " "on public.requests (company_id, status);"
    )
    op.execute(
        "create index requests_company_id_created_at_idx "
        "on public.requests (company_id, created_at desc);"
    )
    op.execute(
        "create index workflow_stages_company_id_status_idx "
        "on public.workflow_stages (company_id, status);"
    )
    op.execute(
        "create index audit_logs_company_id_created_at_idx "
        "on public.audit_logs (company_id, created_at desc);"
    )


def downgrade() -> None:
    op.execute("drop index if exists audit_logs_company_id_created_at_idx;")
    op.execute("drop index if exists workflow_stages_company_id_status_idx;")
    op.execute("drop index if exists requests_company_id_created_at_idx;")
    op.execute("drop index if exists requests_company_id_status_idx;")
