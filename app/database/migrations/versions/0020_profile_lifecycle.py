"""Profile lifecycle (deactivation + GDPR erasure) and FK policy audit.

Per the deletion-strategy design: ``profiles`` gains the same two-tier
lifecycle ``companies`` already has (``0017_platform_admin``) —
``is_active`` (reversible deactivation) and ``deleted_at``/``deleted_by``
(GDPR right-to-erasure; irreversible, since erasure also overwrites
``full_name``/``department`` at the Application Layer — this migration
only adds the columns, ``app.database.repositories.user_repository.
ProfileRepository.erase`` performs the actual anonymizing write).

This migration is also the fix for every foreign key referencing
``profiles`` that this feature's audit found: before this migration,
almost every one of them was the Postgres-default ``NO ACTION`` (blocking
deletion identically to ``RESTRICT``, but never documented as
intentional) — including ``notifications.recipient_id``, which
``docs/database_schema.md`` had long claimed was ``ON DELETE CASCADE``
without the schema ever actually saying so. Each FK below is now an
explicit, deliberate choice:

- ``RESTRICT`` (``audit_logs.actor_id``, ``requests.requester_id`` —
  newly explicit; ``comments.author_id``/``attachments.uploaded_by`` were
  already explicit and are unchanged): core audit/business records that
  must never be silently orphaned. In particular, formalizing
  ``audit_logs.actor_id`` as ``RESTRICT`` is what makes anonymization the
  *only* possible path for any profile with real audit history — a
  profile can never be hard-deleted out from under its own audit trail.
- ``CASCADE`` (``notifications.recipient_id`` — fixed from the
  undocumented default; ``notification_preferences``/``saved_filters``/
  ``search_history``'s own ``user_id`` columns were already ``CASCADE``
  from ``0016``/``0019`` and are unchanged): purely personal, ephemeral
  data with no value once its owner is gone.
- ``SET NULL`` (everything else: the various ``deleted_by``/``updated_by``
  attribution columns, ``workflow_stages.assigned_to``/``decided_by``,
  ``workflow_definitions.created_by``, ``user_invitations.invited_by``/
  ``accepted_profile_id``, ``jobs.actor_id``, ``companies.deleted_by``,
  ``company_licenses.updated_by``, ``feature_flags.updated_by``, and the
  new self-referencing ``profiles.deleted_by``): secondary "who did this"
  metadata where losing the specific attribution is an acceptable
  trade-off, and blocking or cascading the row it's attached to is not.
  ``workflow_definitions.created_by`` and ``user_invitations.invited_by``
  are loosened from ``not null`` first, since a ``SET NULL`` action can
  never fire against a ``not null`` column.

See ``docs/scheduler_distributed_coordination.md``-style candor:
anonymization, not physical deletion, is the actual erasure mechanism —
GDPR Article 17(3) permits retaining data in a form that no longer
identifies the subject where full erasure would conflict with legitimate
audit/record-keeping needs, which is exactly the trade-off the
``RESTRICT`` columns above enforce at the database level.

Revision ID: 0020_profile_lifecycle
Revises: 0019_saved_search
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020_profile_lifecycle"
down_revision: str | None = "0019_saved_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # profiles: the two-tier lifecycle (user_repository.py's ProfileRecord)
    # ------------------------------------------------------------------
    op.execute("""
        alter table public.profiles
            add column is_active boolean not null default true,
            add column deleted_at timestamptz,
            add column deleted_by uuid references public.profiles(id) on delete set null;
        """)
    # Backs the default `deleted_at IS NULL` filter every listing method
    # applies unless include_deleted=True is explicitly requested,
    # mirroring companies_deleted_at_idx (0017_platform_admin).
    op.execute("create index profiles_deleted_at_idx on public.profiles (deleted_at);")

    # ------------------------------------------------------------------
    # RESTRICT: core audit/business records. Newly explicit (formalizing
    # the implicit NO ACTION default this codebase already relied on).
    # ------------------------------------------------------------------
    op.execute("""
        alter table public.audit_logs
            drop constraint audit_logs_actor_id_fkey,
            add constraint audit_logs_actor_id_fkey
                foreign key (actor_id) references public.profiles(id) on delete restrict;
        """)
    op.execute("""
        alter table public.requests
            drop constraint requests_requester_id_fkey,
            add constraint requests_requester_id_fkey
                foreign key (requester_id) references public.profiles(id) on delete restrict;
        """)

    # ------------------------------------------------------------------
    # CASCADE: purely personal, ephemeral data. Fixes the
    # notifications.recipient_id drift against docs/database_schema.md.
    # ------------------------------------------------------------------
    op.execute("""
        alter table public.notifications
            drop constraint notifications_recipient_id_fkey,
            add constraint notifications_recipient_id_fkey
                foreign key (recipient_id) references public.profiles(id) on delete cascade;
        """)

    # ------------------------------------------------------------------
    # SET NULL: secondary "who did this" attribution columns. Two
    # (workflow_definitions.created_by, user_invitations.invited_by) are
    # currently `not null` and must be loosened first.
    # ------------------------------------------------------------------
    op.execute("alter table public.workflow_definitions alter column created_by drop not null;")
    op.execute("""
        alter table public.workflow_definitions
            drop constraint workflow_definitions_created_by_fkey,
            add constraint workflow_definitions_created_by_fkey
                foreign key (created_by) references public.profiles(id) on delete set null;
        """)

    op.execute("alter table public.user_invitations alter column invited_by drop not null;")
    op.execute("""
        alter table public.user_invitations
            drop constraint user_invitations_invited_by_fkey,
            add constraint user_invitations_invited_by_fkey
                foreign key (invited_by) references public.profiles(id) on delete set null,
            drop constraint user_invitations_accepted_profile_id_fkey,
            add constraint user_invitations_accepted_profile_id_fkey
                foreign key (accepted_profile_id) references public.profiles(id)
                on delete set null;
        """)

    op.execute("""
        alter table public.requests
            drop constraint requests_deleted_by_fkey,
            add constraint requests_deleted_by_fkey
                foreign key (deleted_by) references public.profiles(id) on delete set null;
        """)
    op.execute("""
        alter table public.comments
            drop constraint comments_deleted_by_fkey,
            add constraint comments_deleted_by_fkey
                foreign key (deleted_by) references public.profiles(id) on delete set null;
        """)
    op.execute("""
        alter table public.attachments
            drop constraint attachments_deleted_by_fkey,
            add constraint attachments_deleted_by_fkey
                foreign key (deleted_by) references public.profiles(id) on delete set null;
        """)
    op.execute("""
        alter table public.workflow_stages
            drop constraint workflow_stages_assigned_to_fkey,
            add constraint workflow_stages_assigned_to_fkey
                foreign key (assigned_to) references public.profiles(id) on delete set null,
            drop constraint workflow_stages_decided_by_fkey,
            add constraint workflow_stages_decided_by_fkey
                foreign key (decided_by) references public.profiles(id) on delete set null;
        """)
    op.execute("""
        alter table public.jobs
            drop constraint jobs_actor_id_fkey,
            add constraint jobs_actor_id_fkey
                foreign key (actor_id) references public.profiles(id) on delete set null;
        """)
    op.execute("""
        alter table public.companies
            drop constraint companies_deleted_by_fkey,
            add constraint companies_deleted_by_fkey
                foreign key (deleted_by) references public.profiles(id) on delete set null;
        """)
    op.execute("""
        alter table public.company_licenses
            drop constraint company_licenses_updated_by_fkey,
            add constraint company_licenses_updated_by_fkey
                foreign key (updated_by) references public.profiles(id) on delete set null;
        """)
    op.execute("""
        alter table public.feature_flags
            drop constraint feature_flags_updated_by_fkey,
            add constraint feature_flags_updated_by_fkey
                foreign key (updated_by) references public.profiles(id) on delete set null;
        """)


def downgrade() -> None:
    # Reverse in exact opposite order. Restoring `not null` below will
    # fail if any row has actually acquired a NULL via the SET NULL
    # behavior this migration introduced — an inherent, expected limit of
    # downgrading a constraint-loosening migration once it has been
    # exercised against real data (this project's forward-only philosophy
    # treats downgrade() as tested tooling for an empty/fresh database,
    # never as production rollback — see docs/deployment.md Section 18.2).
    op.execute("""
        alter table public.feature_flags
            drop constraint feature_flags_updated_by_fkey,
            add constraint feature_flags_updated_by_fkey
                foreign key (updated_by) references public.profiles(id);
        """)
    op.execute("""
        alter table public.company_licenses
            drop constraint company_licenses_updated_by_fkey,
            add constraint company_licenses_updated_by_fkey
                foreign key (updated_by) references public.profiles(id);
        """)
    op.execute("""
        alter table public.companies
            drop constraint companies_deleted_by_fkey,
            add constraint companies_deleted_by_fkey
                foreign key (deleted_by) references public.profiles(id);
        """)
    op.execute("""
        alter table public.jobs
            drop constraint jobs_actor_id_fkey,
            add constraint jobs_actor_id_fkey
                foreign key (actor_id) references public.profiles(id);
        """)
    op.execute("""
        alter table public.workflow_stages
            drop constraint workflow_stages_decided_by_fkey,
            add constraint workflow_stages_decided_by_fkey
                foreign key (decided_by) references public.profiles(id),
            drop constraint workflow_stages_assigned_to_fkey,
            add constraint workflow_stages_assigned_to_fkey
                foreign key (assigned_to) references public.profiles(id);
        """)
    op.execute("""
        alter table public.attachments
            drop constraint attachments_deleted_by_fkey,
            add constraint attachments_deleted_by_fkey
                foreign key (deleted_by) references public.profiles(id);
        """)
    op.execute("""
        alter table public.comments
            drop constraint comments_deleted_by_fkey,
            add constraint comments_deleted_by_fkey
                foreign key (deleted_by) references public.profiles(id);
        """)
    op.execute("""
        alter table public.requests
            drop constraint requests_deleted_by_fkey,
            add constraint requests_deleted_by_fkey
                foreign key (deleted_by) references public.profiles(id);
        """)

    op.execute("""
        alter table public.user_invitations
            drop constraint user_invitations_accepted_profile_id_fkey,
            add constraint user_invitations_accepted_profile_id_fkey
                foreign key (accepted_profile_id) references public.profiles(id),
            drop constraint user_invitations_invited_by_fkey,
            add constraint user_invitations_invited_by_fkey
                foreign key (invited_by) references public.profiles(id);
        """)
    op.execute("alter table public.user_invitations alter column invited_by set not null;")

    op.execute("""
        alter table public.workflow_definitions
            drop constraint workflow_definitions_created_by_fkey,
            add constraint workflow_definitions_created_by_fkey
                foreign key (created_by) references public.profiles(id);
        """)
    op.execute("alter table public.workflow_definitions alter column created_by set not null;")

    op.execute("""
        alter table public.notifications
            drop constraint notifications_recipient_id_fkey,
            add constraint notifications_recipient_id_fkey
                foreign key (recipient_id) references public.profiles(id);
        """)

    op.execute("""
        alter table public.requests
            drop constraint requests_requester_id_fkey,
            add constraint requests_requester_id_fkey
                foreign key (requester_id) references public.profiles(id);
        """)
    op.execute("""
        alter table public.audit_logs
            drop constraint audit_logs_actor_id_fkey,
            add constraint audit_logs_actor_id_fkey
                foreign key (actor_id) references public.profiles(id);
        """)

    op.execute("drop index if exists profiles_deleted_at_idx;")
    op.execute("""
        alter table public.profiles
            drop column if exists deleted_by,
            drop column if exists deleted_at,
            drop column if exists is_active;
        """)
