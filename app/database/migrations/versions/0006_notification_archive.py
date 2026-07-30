"""Add archive support to the notifications table.

Per this feature's own notification-management UX build-out, ``archived_at``
lets a recipient remove a notification from their default, active view
without deleting it or losing its read/unread history — distinct from this
schema's existing soft-deletion strategy (DSD Section 3.10), which hides a
row from every ordinary view by default. An archived notification is only
excluded when a caller asks for the active view specifically
(``NotificationRepository.list_for_recipient``'s ``is_archived=False``
default); it remains fully queryable and reversible (``unarchive``), unlike
a soft-deleted row.

No RLS change is required: ``notifications_update_own`` (``0003_row_level_
security``) already grants the recipient ``UPDATE`` on their own row without
restricting which columns may change, so it already covers writes to this
new column.

Revision ID: 0006_notification_archive
Revises: 0005_attachments
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_notification_archive"
down_revision: str | None = "0005_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("alter table public.notifications add column archived_at timestamptz;")
    op.execute(
        "create index notifications_recipient_archived_idx "
        "on public.notifications (recipient_id, archived_at);"
    )


def downgrade() -> None:
    op.execute("drop index if exists notifications_recipient_archived_idx;")
    op.execute("alter table public.notifications drop column if exists archived_at;")
