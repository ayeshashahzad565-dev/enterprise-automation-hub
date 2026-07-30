"""Add the two composite indexes ``0012`` left out for the Analytics
Layer's ``GROUP BY``-shaped queries.

``0012_analytics_company_scoped_indexes`` added ``(company_id, status)``
and ``(company_id, created_at)`` — the two combinations every
``AnalyticsRepository`` aggregate filtered on at the time. Converting
``count_requests_by_type``/``count_requests_by_department`` to real SQL
``GROUP BY`` (this migration's companion,
``0022_analytics_aggregation_functions``) makes ``request_type`` and
``department`` the *grouping* column for their respective queries, not
just an optional equality filter — the same "this table's actual hot
combined-filter query" justification ``0012`` used now applies to these
two columns as well:

- ``requests_company_id_request_type_idx`` backs
  ``count_requests_by_type``'s ``group by request_type`` (and the
  optional ``request_type`` equality filter every other aggregate here
  already accepts).
- ``requests_company_id_department_idx`` backs
  ``count_requests_by_department``'s ``group by
  coalesce(department, 'unspecified')`` (and the optional ``department``
  equality filter ``count_requests_by_status``/``count_requests_by_type``
  already accept).

Purely additive, like ``0012`` — neither existing single-column index
(``requests_request_type_idx``/``requests_department_idx``, both from
``0001_initial_schema``) nor either of ``0012``'s composite indexes is
touched or removed.

Revision ID: 0021_analytics_department_and_type_indexes
Revises: 0020_profile_lifecycle
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021_analytics_department_and_type_indexes"
down_revision: str | None = "0020_profile_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "create index requests_company_id_request_type_idx "
        "on public.requests (company_id, request_type);"
    )
    op.execute(
        "create index requests_company_id_department_idx "
        "on public.requests (company_id, department);"
    )


def downgrade() -> None:
    op.execute("drop index if exists requests_company_id_department_idx;")
    op.execute("drop index if exists requests_company_id_request_type_idx;")
