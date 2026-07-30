"""Add a composite (status, expires_at) index on user_invitations.

Per Milestone 9's Performance audit: the Milestone 1-5 cleanup pass
(``InvitationRepository.list_invitations``) added ``expires_after``/
``expires_at_or_before`` filters so ``InvitationService.list_invitations``
could express "effective status" (``pending`` vs. ``expired`` — both
persisted as ``status = 'pending'``, distinguished only by comparing
``expires_at`` to the current time) as a single, correctly-paginated
database query — combining an equality filter on ``status`` with a range
filter on ``expires_at`` in the same query. ``0007_user_invitations``
never added an index supporting that combined access pattern: only a
single-column index on ``status`` existed, leaving the ``expires_at``
range condition with no index to use once ``status`` narrowed the
candidate rows.

This is a pure, additive migration — no existing index is dropped (the
single-column ``user_invitations_status_idx`` from migration 0007 is left
in place; a composite ``(status, expires_at)`` index does make it
redundant for a status-only equality query via the leftmost-prefix rule,
but removing it is a separate, non-additive decision out of scope for a
hardening pass whose own engineering rules prefer minimal, low-risk
changes with a clear production justification over speculative cleanup)
and does not change any query's behavior, only its performance
characteristics.

Revision ID: 0008_user_invitations_status_expires_at_index
Revises: 0007_user_invitations
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_user_invitations_status_expires_at_index"
down_revision: str | None = "0007_user_invitations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "create index user_invitations_status_expires_at_idx "
        "on public.user_invitations (status, expires_at);"
    )


def downgrade() -> None:
    op.execute("drop index if exists user_invitations_status_expires_at_idx;")
