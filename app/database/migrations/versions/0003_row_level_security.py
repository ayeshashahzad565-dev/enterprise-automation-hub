"""Row-Level Security: grants and policies for every table.

Per DSD Section 9, an anon-key Supabase client (constructed by
``SupabaseAuthGateway``/``SupabaseClientFactory.create_anon_client``,
used for every direct Auth call this app makes) is subject to RLS; the
running application's own repository reads/writes go through the
service-role client instead (see ``app.py``'s ``_build_global_resources``
Conflict 4 note), which carries Postgres's ``BYPASSRLS`` attribute in a
standard Supabase project and is therefore unaffected by anything in
this migration. What's defined here is the defense-in-depth boundary
for any caller using the anon key directly (a future direct-from-browser
client, Supabase's auto-generated REST/GraphQL API, or the SQL editor
acting as ``authenticated``) — matching the ownership/role-based
visibility rules each repository's own docstrings already describe
("visible under the current client's Row-Level Security context").

Newly created tables grant **no** privileges to ``anon``/``authenticated``
by default, so every table below needs an explicit ``GRANT`` in addition
to its policies — a bare ``ENABLE ROW LEVEL SECURITY`` with policies but
no grant would still deny all access.

``current_profile_role()`` is a ``security definer`` helper (owned by
the migration-running role, which is not subject to the RLS it queries
under) so that a policy needing "is the caller an admin" does not
recurse into ``profiles``' own RLS policy while evaluating it — the
standard pattern for a role-lookup helper used inside that same table's
policies.

Revision ID: 0003_row_level_security
Revises: 0002_auth_profile_trigger
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_row_level_security"
down_revision: str | None = "0002_auth_profile_trigger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Helper: the caller's own role, bypassing profiles' RLS (avoids
    # self-recursion when used inside a profiles policy).
    # ------------------------------------------------------------------
    op.execute(
        """
        create function public.current_profile_role()
        returns public.user_role
        language sql
        stable
        security definer
        set search_path = public
        as $$
            select role from public.profiles where id = auth.uid();
        $$;
        """
    )

    op.execute("grant usage on schema public to authenticated;")

    # ------------------------------------------------------------------
    # profiles — readable by any authenticated user (requester/assignee
    # names are displayed throughout the UI); a row is updatable by its
    # own owner or an admin. Role/department changes are additionally
    # restricted to administrators at the Application Layer (per
    # ProfileUpdate's docstring in app/models/user.py) — RLS enforces
    # row-level ownership only, not column-level restriction. Inserts
    # happen exclusively via the on_auth_user_created trigger
    # (security definer, so it needs no policy of its own).
    # ------------------------------------------------------------------
    op.execute("alter table public.profiles enable row level security;")
    op.execute("grant select, update on public.profiles to authenticated;")
    op.execute(
        """
        create policy profiles_select_authenticated on public.profiles
            for select
            to authenticated
            using (true);
        """
    )
    op.execute(
        """
        create policy profiles_update_self_or_admin on public.profiles
            for update
            to authenticated
            using (auth.uid() = id or public.current_profile_role() = 'admin')
            with check (auth.uid() = id or public.current_profile_role() = 'admin');
        """
    )

    # ------------------------------------------------------------------
    # workflow_definitions — any authenticated user may see active
    # definitions (needed to submit a request of that type); only an
    # admin may see inactive versions, create, or edit them (API-ADD
    # Section 19.9's administrator-only endpoints).
    # ------------------------------------------------------------------
    op.execute("alter table public.workflow_definitions enable row level security;")
    op.execute(
        "grant select, insert, update on public.workflow_definitions to authenticated;"
    )
    op.execute(
        """
        create policy workflow_definitions_select on public.workflow_definitions
            for select
            to authenticated
            using (is_active or public.current_profile_role() = 'admin');
        """
    )
    op.execute(
        """
        create policy workflow_definitions_write_admin on public.workflow_definitions
            for insert
            to authenticated
            with check (public.current_profile_role() = 'admin');
        """
    )
    op.execute(
        """
        create policy workflow_definitions_update_admin on public.workflow_definitions
            for update
            to authenticated
            using (public.current_profile_role() = 'admin')
            with check (public.current_profile_role() = 'admin');
        """
    )

    # ------------------------------------------------------------------
    # requests — visible to its requester, any approver assigned to one
    # of its stages, or an admin (matches
    # app/auth/authorization.py's authorize_request_view predicate
    # shape: is_requester / is_assigned_approver / admin). A requester
    # may create their own requests and edit/withdraw them via UPDATE
    # (soft-delete is an UPDATE of deleted_at, per DSD Section 3.10);
    # rows are never hard-deleted, so no DELETE grant is given.
    # ------------------------------------------------------------------
    op.execute("alter table public.requests enable row level security;")
    op.execute("grant select, insert, update on public.requests to authenticated;")
    op.execute(
        """
        create policy requests_select on public.requests
            for select
            to authenticated
            using (
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
            );
        """
    )
    op.execute(
        """
        create policy requests_insert_own on public.requests
            for insert
            to authenticated
            with check (requester_id = auth.uid());
        """
    )
    op.execute(
        """
        create policy requests_update_own_or_admin on public.requests
            for update
            to authenticated
            using (requester_id = auth.uid() or public.current_profile_role() = 'admin')
            with check (requester_id = auth.uid() or public.current_profile_role() = 'admin');
        """
    )

    # ------------------------------------------------------------------
    # workflow_stages — visible to the parent request's requester (audit
    # visibility of their own approval chain), the stage's assignee
    # (specific user or role-eligible pool), or an admin. Updatable
    # (decision recording) only by the assignee or an admin.
    # ------------------------------------------------------------------
    op.execute("alter table public.workflow_stages enable row level security;")
    op.execute("grant select, update on public.workflow_stages to authenticated;")
    op.execute(
        """
        create policy workflow_stages_select on public.workflow_stages
            for select
            to authenticated
            using (
                assigned_to = auth.uid()
                or assigned_role = public.current_profile_role()
                or public.current_profile_role() = 'admin'
                or exists (
                    select 1 from public.requests r
                    where r.id = workflow_stages.request_id
                      and r.requester_id = auth.uid()
                )
            );
        """
    )
    op.execute(
        """
        create policy workflow_stages_update_assignee_or_admin on public.workflow_stages
            for update
            to authenticated
            using (
                assigned_to = auth.uid()
                or assigned_role = public.current_profile_role()
                or public.current_profile_role() = 'admin'
            )
            with check (
                assigned_to = auth.uid()
                or assigned_role = public.current_profile_role()
                or public.current_profile_role() = 'admin'
            );
        """
    )

    # ------------------------------------------------------------------
    # notifications — visible and updatable (mark-read) only by their
    # own recipient, or an admin. Never inserted by an authenticated
    # caller directly (system-generated only, per NotificationCreate's
    # docstring: "not a client-facing API request body").
    # ------------------------------------------------------------------
    op.execute("alter table public.notifications enable row level security;")
    op.execute("grant select, update on public.notifications to authenticated;")
    op.execute(
        """
        create policy notifications_select_own on public.notifications
            for select
            to authenticated
            using (recipient_id = auth.uid() or public.current_profile_role() = 'admin');
        """
    )
    op.execute(
        """
        create policy notifications_update_own on public.notifications
            for update
            to authenticated
            using (recipient_id = auth.uid())
            with check (recipient_id = auth.uid());
        """
    )

    # ------------------------------------------------------------------
    # audit_logs — read-only for authenticated callers (mirrors
    # app/auth/authorization.py's authorize_audit_trail_view: the
    # related request's requester, an assigned approver on it, or an
    # admin). No INSERT/UPDATE/DELETE grant is given to authenticated or
    # anon at all — entries are written exclusively by the
    # service-role-backed AuditService, matching the immutable,
    # append-only design audit_repository.py documents (it exposes no
    # update/delete method of its own).
    # ------------------------------------------------------------------
    op.execute("alter table public.audit_logs enable row level security;")
    op.execute("grant select on public.audit_logs to authenticated;")
    op.execute(
        """
        create policy audit_logs_select on public.audit_logs
            for select
            to authenticated
            using (
                public.current_profile_role() = 'admin'
                or exists (
                    select 1 from public.requests r
                    where r.id = audit_logs.request_id
                      and r.requester_id = auth.uid()
                )
                or exists (
                    select 1 from public.workflow_stages ws
                    where ws.request_id = audit_logs.request_id
                      and (
                          ws.assigned_to = auth.uid()
                          or ws.assigned_role = public.current_profile_role()
                      )
                )
            );
        """
    )


def downgrade() -> None:
    for table in (
        "audit_logs",
        "notifications",
        "workflow_stages",
        "requests",
        "workflow_definitions",
        "profiles",
    ):
        op.execute(f"drop policy if exists {table}_select on public.{table};")

    op.execute("drop policy if exists notifications_update_own on public.notifications;")
    op.execute(
        "drop policy if exists workflow_stages_update_assignee_or_admin "
        "on public.workflow_stages;"
    )
    op.execute("drop policy if exists requests_update_own_or_admin on public.requests;")
    op.execute("drop policy if exists requests_insert_own on public.requests;")
    op.execute(
        "drop policy if exists workflow_definitions_update_admin "
        "on public.workflow_definitions;"
    )
    op.execute(
        "drop policy if exists workflow_definitions_write_admin on public.workflow_definitions;"
    )
    op.execute("drop policy if exists profiles_update_self_or_admin on public.profiles;")
    op.execute("drop policy if exists profiles_select_authenticated on public.profiles;")

    for table in (
        "audit_logs",
        "notifications",
        "workflow_stages",
        "requests",
        "workflow_definitions",
        "profiles",
    ):
        op.execute(f"revoke all on public.{table} from authenticated;")
        op.execute(f"alter table public.{table} disable row level security;")

    op.execute("revoke usage on schema public from authenticated;")
    op.execute("drop function if exists public.current_profile_role();")
