"""Add three more composite indexes surfaced by re-auditing every
repository method that filters ``company_id`` together with another
column, following the same review that produced ``0012``, ``0013``,
``0021``, and ``0023``.

- ``requests (company_id, requester_id)`` — ``RequestRepository
  .list_requests`` is called with an explicit ``requester_id`` filter for
  every ``employee``-role caller of ``GET /api/v1/requests``
  (``RequestService.list_requests`` sets ``requester_id =
  identity.user_id`` whenever ``identity.role is UserRole.EMPLOYEE``) —
  an employee's own "my requests" view, the single most frequently hit
  list query in the application. Only single-column ``company_id``/
  ``requester_id`` indexes existed before this.
- ``audit_logs (company_id, actor_id, created_at desc)`` — mirrors
  ``0013``'s ``(company_id, action, created_at desc)`` exactly, but for
  ``actor_id``: ``GET /api/v1/activity`` ("the caller's own activity
  feed", ``app/api/routers/activity.py``) calls ``AuditRepository
  .list_all(company_id=..., actor_id=identity.user_id, ...)`` for every
  authenticated user, newest first — the identical shape ``0013``
  already justified for ``action``, just never extended to ``actor_id``.
- ``user_invitations (company_id, status, expires_at)`` — the same
  pre-multi-tenancy-retrofit gap ``0023`` closed for
  ``profiles (role, department)``: ``user_invitations_status_expires_at_idx``
  (``0008``) predates ``company_id`` existing on this table at all
  (``0010``) and has no ``company_id`` leading column, even though
  ``InvitationRepository.list_invitations`` always filters on
  ``company_id`` together with the optional ``status``/``expires_at``
  pair it was built for.

Not added, and deliberately so: a ``workflow_definitions (company_id,
request_type)`` composite for the general ``list_definitions``/
``search_definitions`` browsing path. Unlike the three above, this table
holds a handful of rows per company (one workflow definition per
request type per version, not one row per business transaction), the
access pattern is a rare admin operation, and the highest-value case
(finding *the* active definition for a type) is already served by the
existing partial unique index, ``workflow_definitions_active_uidx
(company_id, request_type) where is_active`` (``0010``, already
company-scoped) — adding a further non-partial composite here would be
speculative, not justified by either query frequency or table growth,
unlike the three added here.

Purely additive, like every composite-index migration before it — no
existing index is touched or removed.

Revision ID: 0024_requester_actor_and_invitation_indexes
Revises: 0023_profiles_company_role_department_index
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024_requester_actor_and_invitation_indexes"
down_revision: str | None = "0023_profiles_company_role_department_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "create index requests_company_id_requester_id_idx "
        "on public.requests (company_id, requester_id);"
    )
    op.execute(
        "create index audit_logs_company_id_actor_id_created_at_idx "
        "on public.audit_logs (company_id, actor_id, created_at desc);"
    )
    op.execute(
        "create index user_invitations_company_id_status_expires_at_idx "
        "on public.user_invitations (company_id, status, expires_at);"
    )


def downgrade() -> None:
    op.execute("drop index if exists user_invitations_company_id_status_expires_at_idx;")
    op.execute("drop index if exists audit_logs_company_id_actor_id_created_at_idx;")
    op.execute("drop index if exists requests_company_id_requester_id_idx;")
