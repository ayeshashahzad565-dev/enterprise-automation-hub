"""Add the ``jobs`` table — the durable system of record for the background job system.

Per the Production-Grade Job System design: Redis (``app.jobs.redis_queue``)
is only ever the live dispatch mechanism — a job's Redis footprint is an
ephemeral ``{"job_id", "priority"}`` pointer with no independent meaning.
This table is the actual source of truth for a job's status and history,
following the same "Postgres is truth, Redis is acceleration" principle
already documented for the analytics response cache
(``docs/deployment.md`` Section 16.5).

No ``company_id`` column and no tenant-scoped RLS policy: unlike every
other table in this schema, a job is platform infrastructure state, never
tenant-facing data — there is no authenticated end-user use case for
reading this table directly. Every consumer (``JobRepository``, the
worker processes, the admin-only ``/admin/jobs`` API) uses the
service-role client, which bypasses RLS via ``BYPASSRLS``, exactly like
``audit_logs``'s existing platform-event rows. RLS is still enabled and
forced (per ``0014_companies_rls_and_force_rls``'s "a bare table with no
grant already denies all access, FORCE closes the table-owner-connection
gap too" precedent) even though no policy is ever added — no grant to
``authenticated`` is made at all.

Revision ID: 0015_jobs
Revises: 0014_companies_rls_and_force_rls
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015_jobs"
down_revision: str | None = "0014_companies_rls_and_force_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        create table public.jobs (
            id uuid primary key default gen_random_uuid(),
            task_type text not null,
            queue_name text not null default 'default',
            priority text not null default 'normal',
            status text not null default 'queued',
            payload jsonb not null,
            attempts integer not null default 0,
            max_attempts integer not null default 5,
            last_error text,
            error_history jsonb not null default '[]'::jsonb,
            scheduled_for timestamptz,
            started_at timestamptz,
            finished_at timestamptz,
            locked_by text,
            request_id uuid references public.requests(id),
            actor_id uuid references public.profiles(id),
            version integer not null default 1,
            created_at timestamptz not null default now(),
            constraint jobs_status_check check (
                status in ('queued', 'running', 'retrying', 'succeeded', 'dead_lettered')
            ),
            constraint jobs_priority_check check (priority in ('high', 'normal', 'low')),
            constraint jobs_version_check check (version > 0),
            constraint jobs_attempts_check check (attempts >= 0 and attempts <= max_attempts)
        );
        """)

    op.execute("""
        create index jobs_status_queue_priority_created_idx
            on public.jobs (status, queue_name, priority, created_at desc);
        """)
    op.execute("create index jobs_task_type_status_idx on public.jobs (task_type, status);")
    op.execute("""
        create index jobs_scheduled_for_idx on public.jobs (scheduled_for)
            where status in ('retrying', 'queued');
        """)
    op.execute("""
        create index jobs_request_id_idx on public.jobs (request_id)
            where request_id is not null;
        """)

    # RLS enabled + forced with no policy and no grant to `authenticated` —
    # see module docstring. Every consumer is the service-role client.
    op.execute("alter table public.jobs enable row level security;")
    op.execute("alter table public.jobs force row level security;")


def downgrade() -> None:
    op.execute("drop table if exists public.jobs;")
