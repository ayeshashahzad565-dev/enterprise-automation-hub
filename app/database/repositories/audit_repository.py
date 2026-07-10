"""Repository for the ``audit_logs`` table.

Per DSD Section 3.8 and Section 6, ``audit_logs`` is an immutable,
append-only record of every state-changing action in the system. This
repository exposes only ``insert`` and read methods — it deliberately does
not, and must never, expose an update or delete method of any kind,
mirroring the database-level grant restriction (``INSERT``/``SELECT``
only) that the DSD assigns to the application's database role.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.repositories.base_repository import (
    BaseRepository,
    Page,
    PagedResult,
    parse_datetime,
    parse_uuid,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuditLogRecord:
    """An immutable, persistence-level representation of one ``audit_logs``
    row (DSD Section 3.8).

    Attributes:
        id: Primary key.
        actor_id: The user who performed the action, or ``None`` for a
            system-initiated action (e.g. a Scheduler escalation, per WEDD
            Section 8.4).
        request_id: The related request, if any.
        action: A fixed action code (e.g. ``"REQUEST_CREATED"``,
            ``"STAGE_APPROVED"``, per WEDD Section 14.1).
        metadata: A structured snapshot of relevant fields at the time of
            the action, if any.
        created_at: The timestamp the action occurred.
    """

    id: UUID
    actor_id: UUID | None
    request_id: UUID | None
    action: str
    metadata: dict[str, Any] | None
    created_at: datetime


def _map_audit_log_row(row: dict[str, Any]) -> AuditLogRecord:
    """Map a raw Supabase row dict into an ``AuditLogRecord``."""
    return AuditLogRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        actor_id=parse_uuid(row.get("actor_id")),
        request_id=parse_uuid(row.get("request_id")),
        action=row["action"],
        metadata=row.get("metadata"),
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


class AuditRepository(BaseRepository[AuditLogRecord]):
    """Persistence operations for the ``audit_logs`` table.

    Corresponds to ``AuditService``'s persistence needs described in the
    ADD and WEDD Section 14. This class intentionally provides no method
    that updates or deletes an existing row — every method below either
    inserts a new, immutable entry or reads existing ones.
    """

    table_name = "audit_logs"

    def __init__(self, client: DatabaseClient) -> None:
        super().__init__(client)

    def record_event(
        self,
        *,
        action: str,
        actor_id: UUID | None = None,
        request_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLogRecord:
        """Insert a new, immutable audit log entry.

        This is the only write operation this repository exposes. Per
        WEDD Section 14.2, the orchestrating Application Service is
        responsible for issuing this insert within the same database
        transaction as the state change it documents, so that the two
        either both commit or both roll back together.

        Args:
            action: A fixed action code (WEDD Section 14.1), e.g.
                ``"REQUEST_CREATED"``, ``"STAGE_APPROVED"``,
                ``"STAGE_REJECTED"``, ``"STAGE_ESCALATED"``,
                ``"WORKFLOW_DEFINITION_ACTIVATED"``.
            actor_id: The user who performed the action, or ``None`` for
                a system-initiated action.
            request_id: The related request, if any.
            metadata: A structured snapshot of relevant fields at the
                time of the action, if any — for example, the prior
                assignee when recording ``"STAGE_ESCALATED"``, or a
                fallback-assignment marker per WEDD Section 7.5.

        Returns:
            The newly created ``AuditLogRecord``.

        Raises:
            ConstraintViolationError: If ``actor_id`` or ``request_id``
                does not resolve to an existing row.
        """
        values: dict[str, Any] = {
            "actor_id": str(actor_id) if actor_id else None,
            "request_id": str(request_id) if request_id else None,
            "action": action,
            "metadata": metadata,
        }
        return self.insert(values, mapper=_map_audit_log_row)

    def get_by_id(self, audit_log_id: UUID) -> AuditLogRecord:  # type: ignore[override]
        """Fetch a single audit log entry by its id.

        Args:
            audit_log_id: The entry's ``id``.

        Returns:
            The matching ``AuditLogRecord``.

        Raises:
            RecordNotFoundError: If no entry with this id exists or is
                visible under the current client's RLS context.
        """
        return super().get_by_id(audit_log_id, mapper=_map_audit_log_row)

    def list_for_request(
        self, request_id: UUID, *, page: Page = Page(size=100)
    ) -> PagedResult[AuditLogRecord]:
        """List the full audit trail for a request, chronologically.

        Corresponds to ``GET /api/v1/requests/{id}/audit-log`` (API-ADD
        Section 19.10.1), backed by the index on ``request_id`` (DSD
        Section 10.1).

        Args:
            request_id: The request's ``id``.
            page: The page to retrieve, oldest first (chronological
                order, per WEDD Section 14.2).

        Returns:
            A ``PagedResult`` of the request's audit entries.
        """
        builder = self._query().eq("request_id", str(request_id)).order("created_at")
        return self.paginate(builder, page, mapper=_map_audit_log_row)

    def list_for_actor(
        self, actor_id: UUID, *, page: Page = Page()
    ) -> PagedResult[AuditLogRecord]:
        """List the audit entries authored by a specific user.

        Backed by the index on ``actor_id`` (DSD Section 10.1).

        Args:
            actor_id: The acting user's id.
            page: The page to retrieve, newest first.

        Returns:
            A ``PagedResult`` of matching audit entries.
        """
        builder = self._query().eq("actor_id", str(actor_id)).order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_audit_log_row)

    def list_all(
        self,
        *,
        actor_id: UUID | None = None,
        action: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        page: Page = Page(),
    ) -> PagedResult[AuditLogRecord]:
        """Organization-wide audit search.

        Corresponds to ``GET /api/v1/audit-logs`` (API-ADD Section
        19.10.2), an administrator-only operation at the Application
        Layer and RLS level — this repository applies only the explicit
        filters requested.

        Args:
            actor_id: Restrict to entries authored by this user, if
                provided.
            action: Restrict to this action code, if provided.
            created_after: Restrict to entries at or after this
                timestamp, if provided.
            created_before: Restrict to entries at or before this
                timestamp, if provided.
            page: The page to retrieve, newest first.

        Returns:
            A ``PagedResult`` of matching audit entries.
        """
        builder = self._query()
        if actor_id is not None:
            builder = builder.eq("actor_id", str(actor_id))
        if action is not None:
            builder = builder.eq("action", action)
        if created_after is not None:
            builder = builder.gte("created_at", created_after.isoformat())
        if created_before is not None:
            builder = builder.lte("created_at", created_before.isoformat())
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_audit_log_row)