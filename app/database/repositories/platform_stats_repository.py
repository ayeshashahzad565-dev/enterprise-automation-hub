"""Read-only, cross-tenant aggregation repository for the Platform Administration module.

Every other aggregation repository in this codebase (``AnalyticsRepository``,
``ProfileRepository.list_by_role``, etc.) hard-requires a ``company_id`` —
by design, since ordinary analytics/admin views are always scoped to the
caller's own company. This repository is the deliberate exception: every
method here queries across every tenant, exactly like
``CompanyRepository`` and ``AuditRepository.list_platform_wide`` already
do — enforcement that only a platform admin may call these lives
entirely at the Application Layer (the ``/platform/stats`` router calls
``authorize_platform_admin`` before touching this repository at all).

Matches the existing convention for aggregates PostgREST cannot compute
server-side (no ``SUM``/``GROUP BY`` over the client this codebase uses):
fetch a narrow column projection, aggregate in Python — never ``select
("*")`` for a count/sum, and never one query per group.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.database.client import DatabaseClient
from app.database.repositories.base_repository import BaseRepository, parse_datetime

logger = logging.getLogger(__name__)

__all__ = ["PlatformStatsRepository"]


class PlatformStatsRepository(BaseRepository[Any]):
    """Platform-wide (cross-tenant) counts and sums for the platform stats dashboard.

    Not backed by any single table (it aggregates across ``profiles``,
    ``requests``, ``workflow_definitions``, ``attachments``) — every
    method below builds its own query against the specific table it
    needs via ``self._client.table(...)`` directly, rather than through
    this base class's ``table_name``-driven helpers.
    """

    #: Descriptive only (used solely for this repository's own error
    #: logging context, per ``BaseRepository._translate_and_raise``) —
    #: no method below queries a table literally named this.
    table_name = "platform_stats"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def count_users(self) -> int:
        """Count every profile on the platform, across every company.

        Returns:
            The total user count.
        """
        response = self._execute(
            self._client.table("profiles").select("id", count="exact").limit(1),
            operation="count_users",
        )
        return self._count(response)

    def count_requests(self, *, created_after: datetime | None = None) -> int:
        """Count every request on the platform, across every company.

        Args:
            created_after: Restrict to requests created at or after this
                timestamp, if provided.

        Returns:
            The matching request count.
        """
        builder = self._client.table("requests").select("id", count="exact")
        if created_after is not None:
            builder = builder.gte("created_at", created_after.isoformat())
        response = self._execute(builder.limit(1), operation="count_requests")
        return self._count(response)

    def request_created_timestamps(self, *, created_after: datetime) -> list[datetime]:
        """Fetch every request's ``created_at`` at or after a timestamp.

        A narrow (single-column) projection, not ``select("*")``, fetched
        for the caller to bucket into a trend via
        ``app.analytics.aggregations.build_time_series`` — matching the
        rest of this codebase's Python-side aggregation convention.

        Args:
            created_after: The window's inclusive start.

        Returns:
            Every matching request's ``created_at``, unordered.
        """
        response = self._execute(
            self._client.table("requests")
            .select("created_at")
            .gte("created_at", created_after.isoformat()),
            operation="request_created_timestamps",
        )
        return [parse_datetime(row["created_at"]) for row in self._rows(response)]  # type: ignore[misc]

    def count_active_workflow_definitions(self) -> int:
        """Count every active workflow definition on the platform.

        Returns:
            The active workflow-definition count, across every company.
        """
        response = self._execute(
            self._client.table("workflow_definitions")
            .select("id", count="exact")
            .eq("is_active", True)
            .limit(1),
            operation="count_active_workflow_definitions",
        )
        return self._count(response)

    def sum_attachment_storage_bytes(self) -> int:
        """Sum the size of every non-deleted attachment on the platform.

        Fetches only the ``size_bytes`` column (never full rows) and
        sums it in Python, per this repository's module-level convention.

        Returns:
            The total storage used, in bytes, across every company.
        """
        response = self._execute(
            self._client.table("attachments").select("size_bytes").is_("deleted_at", "null"),
            operation="sum_attachment_storage_bytes",
        )
        return sum(int(row["size_bytes"]) for row in self._rows(response))
