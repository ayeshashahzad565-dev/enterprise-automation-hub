"""Fix infinite RLS recursion between ``requests`` and ``workflow_stages``.

``requests_select`` (``0011_company_scoping_functions_and_rls``) checks
stage assignment via a plain ``exists (select 1 from workflow_stages ws
...)`` subquery. Because ``workflow_stages`` has RLS enabled, evaluating
that subquery re-triggers ``workflow_stages_select`` — which itself does
``exists (select 1 from requests r ...)`` to cover the "requester can see
their own request's stages" case. Postgres detects the resulting cycle
and raises ``infinite recursion detected in policy for relation
"workflow_stages"`` (``42P17``).

This never surfaced on most routes because the application's service-role
client bypasses RLS entirely (``app.database.client``); it only fires on
the handful of routes bound to the RLS-enforcing anon-key client
(``bind_tenant_database_client`` — comments, attachments), and on
anything that queries through them (e.g. the AI request-summary endpoint,
which reads a request's comments).

Fix: add ``request_assigned_to_caller()``, a ``stable security definer``
function mirroring the existing ``current_profile_company()``/
``current_profile_role()`` pattern (``0003_row_level_security``,
``0011_company_scoping_functions_and_rls``) — a security-definer
function's body is not itself subject to the calling role's RLS, so its
internal ``workflow_stages`` lookup does not re-enter
``workflow_stages_select``. Repointing ``requests_select`` at this
function instead of a raw subquery removes the only edge that closed the
cycle: ``workflow_stages_select`` still queries ``requests``, but
``requests_select`` no longer queries ``workflow_stages`` through
ordinary (RLS-subject) SQL, so evaluating either policy now terminates.

``comments``/``attachments``/``audit_logs`` keep their own direct
``exists (select 1 from workflow_stages ...)`` clauses unchanged — they
still reach ``workflow_stages_select``, which still reaches (the now-safe)
``requests_select``, which no longer reaches back into
``workflow_stages``. No further policy needs to change.

Revision ID: 0025_fix_requests_workflow_stages_rls_recursion
Revises: 0024_requester_actor_and_invitation_indexes
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025_fix_requests_workflow_stages_rls_recursion"
down_revision: str | None = "0024_requester_actor_and_invitation_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        create function public.request_assigned_to_caller(p_request_id uuid)
        returns boolean
        language sql
        stable
        security definer
        set search_path = public
        as $$
            select exists (
                select 1 from public.workflow_stages ws
                where ws.request_id = p_request_id
                  and (
                      ws.assigned_to = auth.uid()
                      or ws.assigned_role = public.current_profile_role()
                  )
            );
        $$;
        """)

    op.execute("drop policy requests_select on public.requests;")
    op.execute("""
        create policy requests_select on public.requests
            for select
            to authenticated
            using (
                company_id = public.current_profile_company()
                and (
                    requester_id = auth.uid()
                    or public.current_profile_role() = 'admin'
                    or public.request_assigned_to_caller(requests.id)
                )
            );
        """)


def downgrade() -> None:
    op.execute("drop policy if exists requests_select on public.requests;")
    op.execute("""
        create policy requests_select on public.requests
            for select
            to authenticated
            using (
                company_id = public.current_profile_company()
                and (
                    requester_id = auth.uid()
                    or public.current_profile_role() = 'admin'
                    or exists (
                        select 1 from public.workflow_stages ws
                        where ws.request_id = requests.id
                          and (
                              ws.assigned_to = auth.uid()
                              or ws.assigned_role = public.current_profile_role()
                          )
                    )
                )
            );
        """)

    op.execute("drop function if exists public.request_assigned_to_caller(uuid);")
