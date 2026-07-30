"""Company-scope the auth-provisioning trigger and every RLS policy.

Two Postgres-function changes:

- ``handle_new_user()`` (``0002_auth_profile_trigger``) now also copies
  ``company_id`` out of ``auth.users.raw_user_meta_data``. Unlike
  ``role`` (which falls back to ``'employee'`` on a missing/invalid
  value), ``company_id`` has no sensible fallback — ``profiles.company_id``
  is ``not null``, so a missing/invalid value fails the insert and, since
  this trigger runs inside the same transaction as the triggering
  ``auth.users`` insert, rolls back user creation entirely. This is
  intentional, fail-closed behavior: no Supabase Auth user can ever be
  created without a valid company. ``InvitationService.accept_invitation``
  is updated (application-layer change, not part of this migration) to
  always pass the invitation's own ``company_id`` in ``user_metadata``.
- ``current_profile_company()`` is added, mirroring
  ``current_profile_role()`` (``0003_row_level_security``) exactly:
  ``stable security definer`` so a ``profiles`` policy calling it does
  not recurse into ``profiles``' own RLS.

Every RLS policy touched by company scoping gets exactly one added
predicate, ``company_id = public.current_profile_company()`` — including
the ``admin`` branches, since "admin" now means "admin of their own
company," not the whole platform. ``comments``/``attachments`` have no
``company_id`` column of their own (per ``0010``'s docstring): their
policies instead extend the ``exists (select 1 from requests r ...)``
join they already perform with one more ``and r.company_id = ...``
predicate. Every policy below remains exactly what it has always been —
a defense-in-depth backstop for a hypothetical anon-key caller; the
application's own service-role client bypasses RLS entirely, and real
enforcement continues to live in ``app.auth.rbac``/the service layer.

Revision ID: 0011_company_scoping_functions_and_rls
Revises: 0010_company_scoping_columns
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_company_scoping_functions_and_rls"
down_revision: str | None = "0010_company_scoping_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # handle_new_user(): also copy company_id.
    # ------------------------------------------------------------------
    op.execute("""
        create or replace function public.handle_new_user()
        returns trigger
        language plpgsql
        security definer
        set search_path = public
        as $$
        declare
            resolved_role public.user_role;
        begin
            begin
                resolved_role := (new.raw_user_meta_data->>'role')::public.user_role;
            exception when invalid_text_representation then
                resolved_role := 'employee';
            end;
            if resolved_role is null then
                resolved_role := 'employee';
            end if;

            insert into public.profiles (id, full_name, role, company_id)
            values (
                new.id,
                coalesce(new.raw_user_meta_data->>'full_name', new.email),
                resolved_role,
                (new.raw_user_meta_data->>'company_id')::uuid
            )
            on conflict (id) do nothing;

            return new;
        end;
        $$;
        """)

    # ------------------------------------------------------------------
    # current_profile_company(): mirrors current_profile_role() exactly.
    # ------------------------------------------------------------------
    op.execute("""
        create function public.current_profile_company()
        returns uuid
        language sql
        stable
        security definer
        set search_path = public
        as $$
            select company_id from public.profiles where id = auth.uid();
        $$;
        """)

    # ------------------------------------------------------------------
    # profiles
    # ------------------------------------------------------------------
    op.execute("drop policy profiles_select_authenticated on public.profiles;")
    op.execute("""
        create policy profiles_select_authenticated on public.profiles
            for select
            to authenticated
            using (company_id = public.current_profile_company());
        """)
    op.execute("drop policy profiles_update_self_or_admin on public.profiles;")
    op.execute("""
        create policy profiles_update_self_or_admin on public.profiles
            for update
            to authenticated
            using (
                (auth.uid() = id or public.current_profile_role() = 'admin')
                and company_id = public.current_profile_company()
            )
            with check (
                (auth.uid() = id or public.current_profile_role() = 'admin')
                and company_id = public.current_profile_company()
            );
        """)

    # ------------------------------------------------------------------
    # workflow_definitions
    # ------------------------------------------------------------------
    op.execute("drop policy workflow_definitions_select on public.workflow_definitions;")
    op.execute("""
        create policy workflow_definitions_select on public.workflow_definitions
            for select
            to authenticated
            using (
                company_id = public.current_profile_company()
                and (is_active or public.current_profile_role() = 'admin')
            );
        """)
    op.execute("drop policy workflow_definitions_write_admin on public.workflow_definitions;")
    op.execute("""
        create policy workflow_definitions_write_admin on public.workflow_definitions
            for insert
            to authenticated
            with check (
                public.current_profile_role() = 'admin'
                and company_id = public.current_profile_company()
            );
        """)
    op.execute("drop policy workflow_definitions_update_admin on public.workflow_definitions;")
    op.execute("""
        create policy workflow_definitions_update_admin on public.workflow_definitions
            for update
            to authenticated
            using (
                public.current_profile_role() = 'admin'
                and company_id = public.current_profile_company()
            )
            with check (
                public.current_profile_role() = 'admin'
                and company_id = public.current_profile_company()
            );
        """)

    # ------------------------------------------------------------------
    # requests
    # ------------------------------------------------------------------
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
    op.execute("drop policy requests_insert_own on public.requests;")
    op.execute("""
        create policy requests_insert_own on public.requests
            for insert
            to authenticated
            with check (
                requester_id = auth.uid()
                and company_id = public.current_profile_company()
            );
        """)
    op.execute("drop policy requests_update_own_or_admin on public.requests;")
    op.execute("""
        create policy requests_update_own_or_admin on public.requests
            for update
            to authenticated
            using (
                company_id = public.current_profile_company()
                and (requester_id = auth.uid() or public.current_profile_role() = 'admin')
            )
            with check (
                company_id = public.current_profile_company()
                and (requester_id = auth.uid() or public.current_profile_role() = 'admin')
            );
        """)

    # ------------------------------------------------------------------
    # workflow_stages
    # ------------------------------------------------------------------
    op.execute("drop policy workflow_stages_select on public.workflow_stages;")
    op.execute("""
        create policy workflow_stages_select on public.workflow_stages
            for select
            to authenticated
            using (
                company_id = public.current_profile_company()
                and (
                    assigned_to = auth.uid()
                    or assigned_role = public.current_profile_role()
                    or public.current_profile_role() = 'admin'
                    or exists (
                        select 1 from public.requests r
                        where r.id = workflow_stages.request_id
                          and r.requester_id = auth.uid()
                    )
                )
            );
        """)
    op.execute("drop policy workflow_stages_update_assignee_or_admin on public.workflow_stages;")
    op.execute("""
        create policy workflow_stages_update_assignee_or_admin on public.workflow_stages
            for update
            to authenticated
            using (
                company_id = public.current_profile_company()
                and (
                    assigned_to = auth.uid()
                    or assigned_role = public.current_profile_role()
                    or public.current_profile_role() = 'admin'
                )
            )
            with check (
                company_id = public.current_profile_company()
                and (
                    assigned_to = auth.uid()
                    or assigned_role = public.current_profile_role()
                    or public.current_profile_role() = 'admin'
                )
            );
        """)

    # ------------------------------------------------------------------
    # audit_logs — company_id is nullable, so a null-company row (a
    # genuine platform-level event) is visible only via the
    # requester/approver branches below, never the admin branch, since
    # no admin's own company can ever equal null.
    # ------------------------------------------------------------------
    op.execute("drop policy audit_logs_select on public.audit_logs;")
    op.execute("""
        create policy audit_logs_select on public.audit_logs
            for select
            to authenticated
            using (
                (
                    public.current_profile_role() = 'admin'
                    and company_id = public.current_profile_company()
                )
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
        """)

    # ------------------------------------------------------------------
    # comments — no company_id column; scoped via the existing requests join.
    # ------------------------------------------------------------------
    op.execute("drop policy comments_select on public.comments;")
    op.execute("""
        create policy comments_select on public.comments
            for select
            to authenticated
            using (
                exists (
                    select 1 from public.requests r
                    where r.id = comments.request_id
                      and r.company_id = public.current_profile_company()
                      and (
                          r.requester_id = auth.uid()
                          or public.current_profile_role() = 'admin'
                          or exists (
                              select 1 from public.workflow_stages ws
                              where ws.request_id = comments.request_id
                                and (
                                    ws.assigned_to = auth.uid()
                                    or ws.assigned_role = public.current_profile_role()
                                )
                          )
                      )
                )
            );
        """)
    op.execute("drop policy comments_insert on public.comments;")
    op.execute("""
        create policy comments_insert on public.comments
            for insert
            to authenticated
            with check (
                author_id = auth.uid()
                and exists (
                    select 1 from public.requests r
                    where r.id = comments.request_id
                      and r.company_id = public.current_profile_company()
                      and (
                          r.requester_id = auth.uid()
                          or exists (
                              select 1 from public.workflow_stages ws
                              where ws.request_id = comments.request_id
                                and (
                                    ws.assigned_to = auth.uid()
                                    or ws.assigned_role = public.current_profile_role()
                                )
                          )
                      )
                )
            );
        """)
    op.execute("drop policy comments_moderate_admin on public.comments;")
    op.execute("""
        create policy comments_moderate_admin on public.comments
            for update
            to authenticated
            using (
                public.current_profile_role() = 'admin'
                and exists (
                    select 1 from public.requests r
                    where r.id = comments.request_id
                      and r.company_id = public.current_profile_company()
                )
            )
            with check (
                public.current_profile_role() = 'admin'
                and exists (
                    select 1 from public.requests r
                    where r.id = comments.request_id
                      and r.company_id = public.current_profile_company()
                )
            );
        """)

    # ------------------------------------------------------------------
    # attachments — no company_id column; scoped via the existing
    # requests join, same shape as comments above.
    # ------------------------------------------------------------------
    op.execute("drop policy attachments_select on public.attachments;")
    op.execute("""
        create policy attachments_select on public.attachments
            for select
            to authenticated
            using (
                exists (
                    select 1 from public.requests r
                    where r.id = attachments.request_id
                      and r.company_id = public.current_profile_company()
                      and (
                          r.requester_id = auth.uid()
                          or public.current_profile_role() = 'admin'
                          or exists (
                              select 1 from public.workflow_stages ws
                              where ws.request_id = attachments.request_id
                                and (
                                    ws.assigned_to = auth.uid()
                                    or ws.assigned_role = public.current_profile_role()
                                )
                          )
                      )
                )
            );
        """)
    op.execute("drop policy attachments_insert on public.attachments;")
    op.execute("""
        create policy attachments_insert on public.attachments
            for insert
            to authenticated
            with check (
                uploaded_by = auth.uid()
                and exists (
                    select 1 from public.requests r
                    where r.id = attachments.request_id
                      and r.company_id = public.current_profile_company()
                      and (
                          r.requester_id = auth.uid()
                          or exists (
                              select 1 from public.workflow_stages ws
                              where ws.request_id = attachments.request_id
                                and (
                                    ws.assigned_to = auth.uid()
                                    or ws.assigned_role = public.current_profile_role()
                                )
                          )
                      )
                )
            );
        """)
    op.execute("drop policy attachments_moderate_admin on public.attachments;")
    op.execute("""
        create policy attachments_moderate_admin on public.attachments
            for update
            to authenticated
            using (
                public.current_profile_role() = 'admin'
                and exists (
                    select 1 from public.requests r
                    where r.id = attachments.request_id
                      and r.company_id = public.current_profile_company()
                )
            )
            with check (
                public.current_profile_role() = 'admin'
                and exists (
                    select 1 from public.requests r
                    where r.id = attachments.request_id
                      and r.company_id = public.current_profile_company()
                )
            );
        """)
    op.execute("drop policy attachments_soft_delete_uploader on public.attachments;")
    op.execute("""
        create policy attachments_soft_delete_uploader on public.attachments
            for update
            to authenticated
            using (
                uploaded_by = auth.uid()
                and exists (
                    select 1 from public.requests r
                    where r.id = attachments.request_id
                      and r.status = 'pending'
                      and r.company_id = public.current_profile_company()
                )
            )
            with check (uploaded_by = auth.uid());
        """)

    # ------------------------------------------------------------------
    # user_invitations
    # ------------------------------------------------------------------
    op.execute("drop policy user_invitations_admin_all on public.user_invitations;")
    op.execute("""
        create policy user_invitations_admin_all on public.user_invitations
            for all
            to authenticated
            using (
                public.current_profile_role() = 'admin'
                and company_id = public.current_profile_company()
            )
            with check (
                public.current_profile_role() = 'admin'
                and company_id = public.current_profile_company()
            );
        """)


def downgrade() -> None:
    op.execute("drop policy if exists user_invitations_admin_all on public.user_invitations;")
    op.execute("""
        create policy user_invitations_admin_all on public.user_invitations
            for all
            to authenticated
            using (public.current_profile_role() = 'admin')
            with check (public.current_profile_role() = 'admin');
        """)

    op.execute("drop policy if exists attachments_soft_delete_uploader on public.attachments;")
    op.execute("""
        create policy attachments_soft_delete_uploader on public.attachments
            for update
            to authenticated
            using (
                uploaded_by = auth.uid()
                and exists (
                    select 1 from public.requests r
                    where r.id = attachments.request_id
                      and r.status = 'pending'
                )
            )
            with check (uploaded_by = auth.uid());
        """)
    op.execute("drop policy if exists attachments_moderate_admin on public.attachments;")
    op.execute("""
        create policy attachments_moderate_admin on public.attachments
            for update
            to authenticated
            using (public.current_profile_role() = 'admin')
            with check (public.current_profile_role() = 'admin');
        """)
    op.execute("drop policy if exists attachments_insert on public.attachments;")
    op.execute("""
        create policy attachments_insert on public.attachments
            for insert
            to authenticated
            with check (
                uploaded_by = auth.uid()
                and (
                    exists (
                        select 1 from public.requests r
                        where r.id = attachments.request_id
                          and r.requester_id = auth.uid()
                    )
                    or exists (
                        select 1 from public.workflow_stages ws
                        where ws.request_id = attachments.request_id
                          and (
                              ws.assigned_to = auth.uid()
                              or ws.assigned_role = public.current_profile_role()
                          )
                    )
                )
            );
        """)
    op.execute("drop policy if exists attachments_select on public.attachments;")
    op.execute("""
        create policy attachments_select on public.attachments
            for select
            to authenticated
            using (
                public.current_profile_role() = 'admin'
                or exists (
                    select 1 from public.requests r
                    where r.id = attachments.request_id
                      and r.requester_id = auth.uid()
                )
                or exists (
                    select 1 from public.workflow_stages ws
                    where ws.request_id = attachments.request_id
                      and (
                          ws.assigned_to = auth.uid()
                          or ws.assigned_role = public.current_profile_role()
                      )
                )
            );
        """)

    op.execute("drop policy if exists comments_moderate_admin on public.comments;")
    op.execute("""
        create policy comments_moderate_admin on public.comments
            for update
            to authenticated
            using (public.current_profile_role() = 'admin')
            with check (public.current_profile_role() = 'admin');
        """)
    op.execute("drop policy if exists comments_insert on public.comments;")
    op.execute("""
        create policy comments_insert on public.comments
            for insert
            to authenticated
            with check (
                author_id = auth.uid()
                and (
                    exists (
                        select 1 from public.requests r
                        where r.id = comments.request_id
                          and r.requester_id = auth.uid()
                    )
                    or exists (
                        select 1 from public.workflow_stages ws
                        where ws.request_id = comments.request_id
                          and (
                              ws.assigned_to = auth.uid()
                              or ws.assigned_role = public.current_profile_role()
                          )
                    )
                )
            );
        """)
    op.execute("drop policy if exists comments_select on public.comments;")
    op.execute("""
        create policy comments_select on public.comments
            for select
            to authenticated
            using (
                public.current_profile_role() = 'admin'
                or exists (
                    select 1 from public.requests r
                    where r.id = comments.request_id
                      and r.requester_id = auth.uid()
                )
                or exists (
                    select 1 from public.workflow_stages ws
                    where ws.request_id = comments.request_id
                      and (
                          ws.assigned_to = auth.uid()
                          or ws.assigned_role = public.current_profile_role()
                      )
                )
            );
        """)

    op.execute("drop policy if exists audit_logs_select on public.audit_logs;")
    op.execute("""
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
        """)

    op.execute(
        "drop policy if exists workflow_stages_update_assignee_or_admin "
        "on public.workflow_stages;"
    )
    op.execute("""
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
        """)
    op.execute("drop policy if exists workflow_stages_select on public.workflow_stages;")
    op.execute("""
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
        """)

    op.execute("drop policy if exists requests_update_own_or_admin on public.requests;")
    op.execute("""
        create policy requests_update_own_or_admin on public.requests
            for update
            to authenticated
            using (requester_id = auth.uid() or public.current_profile_role() = 'admin')
            with check (requester_id = auth.uid() or public.current_profile_role() = 'admin');
        """)
    op.execute("drop policy if exists requests_insert_own on public.requests;")
    op.execute("""
        create policy requests_insert_own on public.requests
            for insert
            to authenticated
            with check (requester_id = auth.uid());
        """)
    op.execute("drop policy if exists requests_select on public.requests;")
    op.execute("""
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
        """)

    op.execute(
        "drop policy if exists workflow_definitions_update_admin " "on public.workflow_definitions;"
    )
    op.execute("""
        create policy workflow_definitions_update_admin on public.workflow_definitions
            for update
            to authenticated
            using (public.current_profile_role() = 'admin')
            with check (public.current_profile_role() = 'admin');
        """)
    op.execute(
        "drop policy if exists workflow_definitions_write_admin on public.workflow_definitions;"
    )
    op.execute("""
        create policy workflow_definitions_write_admin on public.workflow_definitions
            for insert
            to authenticated
            with check (public.current_profile_role() = 'admin');
        """)
    op.execute("drop policy if exists workflow_definitions_select on public.workflow_definitions;")
    op.execute("""
        create policy workflow_definitions_select on public.workflow_definitions
            for select
            to authenticated
            using (is_active or public.current_profile_role() = 'admin');
        """)

    op.execute("drop policy if exists profiles_update_self_or_admin on public.profiles;")
    op.execute("""
        create policy profiles_update_self_or_admin on public.profiles
            for update
            to authenticated
            using (auth.uid() = id or public.current_profile_role() = 'admin')
            with check (auth.uid() = id or public.current_profile_role() = 'admin');
        """)
    op.execute("drop policy if exists profiles_select_authenticated on public.profiles;")
    op.execute("""
        create policy profiles_select_authenticated on public.profiles
            for select
            to authenticated
            using (true);
        """)

    op.execute("drop function if exists public.current_profile_company();")

    op.execute("""
        create or replace function public.handle_new_user()
        returns trigger
        language plpgsql
        security definer
        set search_path = public
        as $$
        declare
            resolved_role public.user_role;
        begin
            begin
                resolved_role := (new.raw_user_meta_data->>'role')::public.user_role;
            exception when invalid_text_representation then
                resolved_role := 'employee';
            end;
            if resolved_role is null then
                resolved_role := 'employee';
            end if;

            insert into public.profiles (id, full_name, role)
            values (
                new.id,
                coalesce(new.raw_user_meta_data->>'full_name', new.email),
                resolved_role
            )
            on conflict (id) do nothing;

            return new;
        end;
        $$;
        """)
