"""Domain models for the ``audit_logs`` table.

Per DSD Section 3.8 and Section 6, and WEDD Section 14, ``audit_logs`` is
an immutable, append-only record of every state-changing action in the
system. Corresponds to the persistence layer's
``app.database.repositories.audit_repository.AuditRepository``, which
exposes only ``insert`` and read methods.

This module deliberately defines no update model of any kind. There is no
``AuditLogUpdate`` class here, and there must never be one — an audit
entry, once created, is never modified, matching the database-level grant
restriction (``INSERT``/``SELECT`` only) described in DSD Section 6.1.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.models.base import EAHBaseModel, IdentifiedModel, TimestampedModel
from app.models.enums import AuditAction

__all__ = ["AuditLogEntry", "AuditLogCreate"]


class AuditLogEntry(IdentifiedModel, TimestampedModel):
    """A fully validated, persisted representation of an ``audit_logs``
    row.

    Mirrors DSD Section 3.8's column list exactly and corresponds
    directly to
    ``app.database.repositories.audit_repository.AuditLogRecord``.

    Attributes:
        actor_id: The user who performed the action, or ``None`` for a
            system-initiated action (e.g. a Scheduler escalation, per
            WEDD Section 8.4).
        request_id: The related request, if any.
        action: A fixed action code (WEDD Section 14.1).
        metadata: A structured snapshot of relevant fields at the time of
            the action, if any.
    """

    actor_id: UUID | None = None
    request_id: UUID | None = None
    action: AuditAction
    metadata: dict[str, Any] | None = None


class AuditLogCreate(EAHBaseModel):
    """Input model for recording a new, immutable audit log entry.

    Constructed by ``AuditService`` (per the ADD) at every state-changing
    action, always within the same database transaction as the state
    change it documents (WEDD Section 14.2) — this model itself performs
    no transactional coordination; it only validates the shape of the
    entry to be recorded.

    Attributes:
        action: A fixed action code.
        actor_id: The user who performed the action, or ``None`` for a
            system-initiated action.
        request_id: The related request, if any.
        metadata: A structured snapshot of relevant fields at the time of
            the action, if any.
    """

    action: AuditAction
    actor_id: UUID | None = None
    request_id: UUID | None = None
    metadata: dict[str, Any] | None = None