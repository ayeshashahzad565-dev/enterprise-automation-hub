"""Add a composite index covering AuditRepository.list_all's action filter.

Milestone 13's production-readiness audit found that ``0012``'s
``audit_logs_company_id_created_at_idx (company_id, created_at desc)``
covers every ``list_all`` call that omits ``action``, but not the very
common case where a caller (``OperationalAnalyticsEngine._fetch_all_audit``,
used for approval/rejection-trend bucketing and workload-summary activity
counts) also filters on ``action`` — that query still has to fall back to
scanning by ``company_id`` alone and filtering/sorting the rest in memory.
This migration is purely additive, mirroring ``0012``'s own precedent —
it does not touch or remove any existing index.

Revision ID: 0013_audit_logs_action_index
Revises: 0012_analytics_company_scoped_indexes
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_audit_logs_action_index"
down_revision: str | None = "0012_analytics_company_scoped_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "create index audit_logs_company_id_action_created_at_idx "
        "on public.audit_logs (company_id, action, created_at desc);"
    )


def downgrade() -> None:
    op.execute("drop index if exists audit_logs_company_id_action_created_at_idx;")
