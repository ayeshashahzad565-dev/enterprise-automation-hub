"""Domain model for the platform-wide statistics dashboard.

Not backed by any single table — assembled by composing
``PlatformStatsRepository``'s cross-tenant counts/sums with
``app.analytics.aggregations.build_time_series`` for the request-volume
trend, mirroring ``app.analytics.dto``'s existing DTO style (frozen,
immutable, no behavior beyond the data itself).
"""

from __future__ import annotations

from app.analytics.dto import TrendPoint
from app.models.base import EAHBaseModel

__all__ = ["PlatformStats"]


class PlatformStats(EAHBaseModel):
    """Platform-wide statistics, across every tenant.

    Attributes:
        total_tenants: The total number of companies, including
            deactivated ones but excluding soft-deleted ones.
        active_tenants: The number of active (non-deactivated,
            non-deleted) companies.
        total_users: The total number of users, across every company.
        total_requests: The total number of requests, across every
            company.
        request_volume_trend: Daily request-creation counts over the
            requested trailing window.
        active_workflow_definitions: The number of active workflow
            definitions, across every company.
        total_storage_bytes: The total size of every non-deleted
            attachment, across every company.
    """

    total_tenants: int
    active_tenants: int
    total_users: int
    total_requests: int
    request_volume_trend: list[TrendPoint]
    active_workflow_definitions: int
    total_storage_bytes: int
