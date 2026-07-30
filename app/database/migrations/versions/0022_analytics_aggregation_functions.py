"""Move ``AnalyticsRepository``'s four aggregate queries from Python-side
grouping to real SQL ``GROUP BY``/``COUNT``/``AVG``, via four Postgres
functions called through PostgREST's RPC endpoint (``.rpc(...)``).

Before this migration, every one of these queries fetched one row per
matching request (or per matching workflow stage) — every column needed
to group in Python via ``collections.Counter``, or to sum/average by
hand — over the wire, then discarded everything except a handful of
counts. For a company with hundreds or thousands of requests, that is
hundreds or thousands of rows transferred and JSON-deserialized to
produce single-digit-cardinality output (at most one row per
``RequestStatus``/department/request type). These functions compute the
same result inside Postgres and return only the aggregated rows:

- ``analytics_count_requests_by_status`` — replaces
  ``AnalyticsRepository.count_requests_by_status``'s
  ``Counter(row["status"] for row in rows)``.
- ``analytics_count_requests_by_type`` — replaces
  ``count_requests_by_type``'s equivalent tally over ``request_type``.
- ``analytics_count_requests_by_department`` — replaces
  ``count_requests_by_department``'s tally over ``department``,
  including its ``"unspecified"`` fallback for both ``null`` and an
  empty string (``coalesce(nullif(department, ''), 'unspecified')``,
  matching the original ``row.get("department") or "unspecified"``
  exactly).
- ``analytics_approval_throughput`` — replaces two separate round trips
  (one full fetch of every matching request's ``id``/``status``, one
  full fetch of every matching decided stage's timestamps via an
  embedded join) with a single function call returning one row: request
  counts for the two terminal statuses computed with ``count(*) filter
  (...)`` in one scan, plus the average decision latency as a real SQL
  ``avg(extract(epoch from ...))`` in another. An empty matching
  population correctly yields ``average_decision_seconds = null`` for
  free (``avg`` over zero rows is ``null`` in standard SQL) — no
  ``if request_ids:`` guard needed, unlike the Python version.

Every function is ``language sql stable`` (a single, non-recursive query,
never mutates), takes the same required ``company_id``-first, optional-
filter-rest shape ``AnalyticsRepository._apply_common_filters`` already
enforced, and is explicitly revoked from ``public`` — ``AnalyticsRepository``
always runs on the service-role client (``app/bootstrap.py``), so nothing
in the running application needs (or should have) these reachable via an
anon/authenticated caller's own RPC call, which PostgREST would otherwise
expose by default the moment a function exists in a queryable schema.

Revision ID: 0022_analytics_aggregation_functions
Revises: 0021_analytics_department_and_type_indexes
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022_analytics_aggregation_functions"
down_revision: str | None = "0021_analytics_department_and_type_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNCTIONS = (
    "analytics_count_requests_by_status(uuid, text, text, timestamptz, timestamptz)",
    "analytics_count_requests_by_type(uuid, text, timestamptz, timestamptz)",
    "analytics_count_requests_by_department(uuid, text, timestamptz, timestamptz)",
    "analytics_approval_throughput(uuid, text, timestamptz, timestamptz)",
)


def upgrade() -> None:
    op.execute("""
        create function public.analytics_count_requests_by_status(
            p_company_id uuid,
            p_department text default null,
            p_request_type text default null,
            p_created_after timestamptz default null,
            p_created_before timestamptz default null
        )
        returns table(status text, request_count bigint)
        language sql
        stable
        as $$
            select r.status::text, count(*)::bigint
            from public.requests r
            where r.company_id = p_company_id
              and r.deleted_at is null
              and (p_department is null or r.department = p_department)
              and (p_request_type is null or r.request_type = p_request_type)
              and (p_created_after is null or r.created_at >= p_created_after)
              and (p_created_before is null or r.created_at <= p_created_before)
            group by r.status;
        $$;
        """)

    op.execute("""
        create function public.analytics_count_requests_by_type(
            p_company_id uuid,
            p_department text default null,
            p_created_after timestamptz default null,
            p_created_before timestamptz default null
        )
        returns table(request_type text, request_count bigint)
        language sql
        stable
        as $$
            select r.request_type, count(*)::bigint
            from public.requests r
            where r.company_id = p_company_id
              and r.deleted_at is null
              and (p_department is null or r.department = p_department)
              and (p_created_after is null or r.created_at >= p_created_after)
              and (p_created_before is null or r.created_at <= p_created_before)
            group by r.request_type;
        $$;
        """)

    op.execute("""
        create function public.analytics_count_requests_by_department(
            p_company_id uuid,
            p_request_type text default null,
            p_created_after timestamptz default null,
            p_created_before timestamptz default null
        )
        returns table(department text, request_count bigint)
        language sql
        stable
        as $$
            select coalesce(nullif(r.department, ''), 'unspecified'), count(*)::bigint
            from public.requests r
            where r.company_id = p_company_id
              and r.deleted_at is null
              and (p_request_type is null or r.request_type = p_request_type)
              and (p_created_after is null or r.created_at >= p_created_after)
              and (p_created_before is null or r.created_at <= p_created_before)
            group by coalesce(nullif(r.department, ''), 'unspecified');
        $$;
        """)

    op.execute("""
        create function public.analytics_approval_throughput(
            p_company_id uuid,
            p_request_type text default null,
            p_created_after timestamptz default null,
            p_created_before timestamptz default null
        )
        returns table(
            completed_count bigint,
            rejected_count bigint,
            average_decision_seconds double precision
        )
        language sql
        stable
        as $$
            with req as (
                select
                    count(*) filter (where r.status = 'completed') as completed_count,
                    count(*) filter (where r.status = 'rejected') as rejected_count
                from public.requests r
                where r.company_id = p_company_id
                  and r.deleted_at is null
                  and (p_request_type is null or r.request_type = p_request_type)
                  and (p_created_after is null or r.created_at >= p_created_after)
                  and (p_created_before is null or r.created_at <= p_created_before)
            ),
            stg as (
                select avg(extract(epoch from (ws.decided_at - ws.created_at)))
                    as average_decision_seconds
                from public.workflow_stages ws
                join public.requests r on r.id = ws.request_id
                where ws.company_id = p_company_id
                  and ws.status in ('approved', 'rejected')
                  and ws.decided_at is not null
                  and r.deleted_at is null
                  and (p_request_type is null or r.request_type = p_request_type)
                  and (p_created_after is null or r.created_at >= p_created_after)
                  and (p_created_before is null or r.created_at <= p_created_before)
            )
            select
                req.completed_count::bigint,
                req.rejected_count::bigint,
                stg.average_decision_seconds
            from req, stg;
        $$;
        """)

    for signature in _FUNCTIONS:
        op.execute(f"revoke execute on function public.{signature} from public;")


def downgrade() -> None:
    for signature in reversed(_FUNCTIONS):
        op.execute(f"drop function if exists public.{signature};")
