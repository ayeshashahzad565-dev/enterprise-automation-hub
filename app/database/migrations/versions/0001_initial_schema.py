"""Initial schema: enums, core tables, indexes, and constraints.

Creates every table, native enum type, index, and constraint the
Database Schema Design Document specifies and every repository under
``app.database.repositories`` relies on as-is. Column names, types,
defaults, and constraints here are taken directly from each
repository's ``*Record`` dataclass and row mapper, and cross-checked
against the corresponding Domain Layer model in ``app.models`` (field
lengths, ``version``/``row_version`` optimistic-locking conventions,
``UpdatableTimestampModel`` vs ``TimestampedModel`` usage):

- ``profiles``                — user_repository.py / app/models/user.py
- ``workflow_definitions``    — workflow_repository.py / app/models/workflow.py
- ``requests``                — request_repository.py / app/models/request.py
- ``workflow_stages``         — workflow_repository.py / app/models/workflow.py
- ``notifications``           — notification_repository.py / app/models/notification.py
- ``audit_logs``               — audit_repository.py / app/models/audit.py

``requests.current_stage_id`` and ``workflow_stages.request_id``
reference each other, so the ``requests`` table is created first
without that one foreign key, and it is added once ``workflow_stages``
exists.

No repository ever sets ``updated_at`` explicitly on a write (see
``base_repository.py``'s ``insert``/``update_with_optimistic_lock``) or
``version``/``row_version`` on insert — both are exclusively
database-maintained, via the defaults and trigger defined here.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions. gen_random_uuid() is a core builtin as of Postgres 13+
    # (Supabase's minimum supported version), but pgcrypto is created
    # defensively for portability with older/self-hosted Postgres.
    # ------------------------------------------------------------------
    op.execute('create extension if not exists "pgcrypto";')

    # ------------------------------------------------------------------
    # Native enum types. Values are lowercase strings matching
    # app.models.enums and the matching *Repository module's Enum class
    # exactly (UserRole, RequestStatus, StageStatus, NotificationType),
    # per each repository module's own docstring ("a lowercase string
    # matching the native PostgreSQL enum type... exactly"). AuditAction
    # is deliberately NOT a native enum here: audit_logs.action is a
    # plain text column (see audit_repository.py / app/models/audit.py).
    # ------------------------------------------------------------------
    op.execute("create type public.user_role as enum ('employee', 'approver', 'admin');")
    op.execute(
        "create type public.request_status as enum "
        "('pending', 'in_review', 'approved', 'rejected', 'completed');"
    )
    op.execute(
        "create type public.stage_status as enum "
        "('pending', 'approved', 'rejected', 'skipped');"
    )
    op.execute(
        "create type public.notification_type as enum "
        "('assignment', 'reminder', 'escalation', 'decision', 'completion', 'system');"
    )

    # ------------------------------------------------------------------
    # profiles — extends auth.users (user_repository.py:47-86)
    # ------------------------------------------------------------------
    op.execute(
        """
        create table public.profiles (
            id          uuid primary key references auth.users(id) on delete cascade,
            full_name   text not null,
            role        public.user_role not null default 'employee',
            department  text,
            version     integer not null default 1 check (version > 0),
            created_at  timestamptz not null default now(),
            updated_at  timestamptz not null default now()
        );
        """
    )
    # Backs ProfileRepository.list_by_role(role, department=...), used by
    # AssignmentResolver's department_queue strategy. A composite index
    # on (role, department) also serves role-only lookups via its
    # leftmost prefix, so no separate single-column index is needed.
    op.execute(
        "create index profiles_role_department_idx on public.profiles (role, department);"
    )

    # ------------------------------------------------------------------
    # workflow_definitions (workflow_repository.py:53-96)
    # ------------------------------------------------------------------
    op.execute(
        """
        create table public.workflow_definitions (
            id           uuid primary key default gen_random_uuid(),
            request_type text not null,
            version      integer not null check (version >= 1),
            definition   jsonb not null,
            is_active    boolean not null default false,
            created_by   uuid not null references public.profiles(id),
            row_version  integer not null default 1 check (row_version > 0),
            created_at   timestamptz not null default now(),
            constraint workflow_definitions_type_version_uq unique (request_type, version)
        );
        """
    )
    # Enforces "at most one active version per request_type" (relied on
    # by activate_definition's deactivate-then-activate transaction) and
    # backs find_active_for_request_type's lookup, per
    # workflow_repository.py's own docstring referencing this exact
    # partial index.
    op.execute(
        "create unique index workflow_definitions_active_uidx "
        "on public.workflow_definitions (request_type) where is_active;"
    )

    # ------------------------------------------------------------------
    # requests (request_repository.py:48-90). current_stage_id's foreign
    # key to workflow_stages is added further below, once that table
    # exists.
    # ------------------------------------------------------------------
    op.execute(
        """
        create table public.requests (
            id                      uuid primary key default gen_random_uuid(),
            requester_id            uuid not null references public.profiles(id),
            workflow_definition_id  uuid not null references public.workflow_definitions(id),
            request_type            text not null,
            title                   text not null check (char_length(title) between 1 and 200),
            description             text check (char_length(description) <= 5000),
            department              text,
            status                  public.request_status not null default 'pending',
            current_stage_id        uuid,
            version                 integer not null default 1 check (version > 0),
            deleted_at              timestamptz,
            deleted_by              uuid references public.profiles(id),
            created_at              timestamptz not null default now(),
            updated_at              timestamptz not null default now(),
            completed_at            timestamptz
        );
        """
    )
    op.execute("create index requests_requester_id_idx on public.requests (requester_id);")
    op.execute(
        "create index requests_workflow_definition_id_idx "
        "on public.requests (workflow_definition_id);"
    )
    op.execute("create index requests_status_idx on public.requests (status);")
    op.execute("create index requests_request_type_idx on public.requests (request_type);")
    op.execute("create index requests_department_idx on public.requests (department);")
    op.execute("create index requests_created_at_idx on public.requests (created_at desc);")
    # Backs list_requests'/search_requests' default sort (newest first)
    # under their default `deleted_at IS NULL` filter (DSD Section
    # 3.10's soft-deletion convention).
    op.execute(
        "create index requests_active_created_at_idx "
        "on public.requests (created_at desc) where deleted_at is null;"
    )

    # ------------------------------------------------------------------
    # workflow_stages (workflow_repository.py:99-150)
    # ------------------------------------------------------------------
    op.execute(
        """
        create table public.workflow_stages (
            id             uuid primary key default gen_random_uuid(),
            request_id     uuid not null references public.requests(id) on delete cascade,
            stage_order    integer not null check (stage_order > 0),
            stage_name     text not null,
            assigned_role  public.user_role,
            assigned_to    uuid references public.profiles(id),
            status         public.stage_status not null default 'pending',
            decided_by     uuid references public.profiles(id),
            decided_at     timestamptz,
            decision_note  text check (char_length(decision_note) <= 1000),
            version        integer not null default 1 check (version > 0),
            created_at     timestamptz not null default now(),
            constraint workflow_stages_request_order_uq unique (request_id, stage_order)
        );
        """
    )
    op.execute(
        "create index workflow_stages_request_id_idx on public.workflow_stages (request_id);"
    )
    # Backs list_pending_for_approver (API-ADD Section 19.5.3), per
    # approval_repository.py's own docstring referencing this exact
    # composite index.
    op.execute(
        "create index workflow_stages_assigned_to_status_idx "
        "on public.workflow_stages (assigned_to, status);"
    )
    op.execute(
        "create index workflow_stages_assigned_role_status_idx "
        "on public.workflow_stages (assigned_role, status);"
    )
    # Backs the Scheduler's list_overdue_stages threshold scan
    # (Escalation Check / Reminder Dispatch jobs).
    op.execute(
        "create index workflow_stages_status_created_at_idx "
        "on public.workflow_stages (status, created_at);"
    )

    # Now that workflow_stages exists, close the circular reference.
    op.execute(
        "alter table public.requests "
        "add constraint requests_current_stage_id_fkey "
        "foreign key (current_stage_id) references public.workflow_stages(id);"
    )
    op.execute(
        "create index requests_current_stage_id_idx on public.requests (current_stage_id);"
    )

    # ------------------------------------------------------------------
    # notifications (notification_repository.py:42-86)
    # ------------------------------------------------------------------
    op.execute(
        """
        create table public.notifications (
            id                 uuid primary key default gen_random_uuid(),
            recipient_id       uuid not null references public.profiles(id),
            request_id         uuid references public.requests(id) on delete cascade,
            notification_type  public.notification_type not null,
            message            text not null,
            is_read            boolean not null default false,
            read_at            timestamptz,
            email_sent         boolean not null default false,
            email_sent_at      timestamptz,
            created_at         timestamptz not null default now()
        );
        """
    )
    # Backs list_for_recipient / get_unread_count (API-ADD Section
    # 19.8), per notification_repository.py's own docstring referencing
    # this exact composite index.
    op.execute(
        "create index notifications_recipient_read_idx "
        "on public.notifications (recipient_id, is_read);"
    )
    op.execute(
        "create index notifications_request_id_idx on public.notifications (request_id);"
    )

    # ------------------------------------------------------------------
    # audit_logs (audit_repository.py:31-66) — append-only; this
    # repository exposes no update/delete method, matching the
    # database-level grant restriction applied in 0003.
    # ------------------------------------------------------------------
    op.execute(
        """
        create table public.audit_logs (
            id          uuid primary key default gen_random_uuid(),
            actor_id    uuid references public.profiles(id),
            request_id  uuid references public.requests(id),
            action      text not null,
            metadata    jsonb,
            created_at  timestamptz not null default now()
        );
        """
    )
    op.execute("create index audit_logs_request_id_idx on public.audit_logs (request_id);")
    op.execute("create index audit_logs_actor_id_idx on public.audit_logs (actor_id);")
    op.execute("create index audit_logs_action_idx on public.audit_logs (action);")
    op.execute("create index audit_logs_created_at_idx on public.audit_logs (created_at desc);")

    # ------------------------------------------------------------------
    # updated_at maintenance. Per app/models/base.py's
    # UpdatableTimestampModel docstring, profiles and requests are the
    # only two tables that carry both created_at and updated_at; no
    # repository method ever sets updated_at itself (see
    # base_repository.py's insert/update_with_optimistic_lock), so it is
    # exclusively maintained here.
    # ------------------------------------------------------------------
    op.execute(
        """
        create function public.set_updated_at()
        returns trigger
        language plpgsql
        as $$
        begin
            new.updated_at = now();
            return new;
        end;
        $$;
        """
    )
    op.execute(
        "create trigger set_profiles_updated_at "
        "before update on public.profiles "
        "for each row execute function public.set_updated_at();"
    )
    op.execute(
        "create trigger set_requests_updated_at "
        "before update on public.requests "
        "for each row execute function public.set_updated_at();"
    )


def downgrade() -> None:
    op.execute("drop trigger if exists set_requests_updated_at on public.requests;")
    op.execute("drop trigger if exists set_profiles_updated_at on public.profiles;")
    op.execute("drop function if exists public.set_updated_at();")
    op.execute("drop table if exists public.audit_logs;")
    op.execute("drop table if exists public.notifications;")
    op.execute(
        "alter table public.requests drop constraint if exists requests_current_stage_id_fkey;"
    )
    op.execute("drop table if exists public.workflow_stages;")
    op.execute("drop table if exists public.requests;")
    op.execute("drop table if exists public.workflow_definitions;")
    op.execute("drop table if exists public.profiles;")
    op.execute("drop type if exists public.notification_type;")
    op.execute("drop type if exists public.stage_status;")
    op.execute("drop type if exists public.request_status;")
    op.execute("drop type if exists public.user_role;")
