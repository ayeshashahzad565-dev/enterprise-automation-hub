"""HTTP schema for the ``dashboard-summary`` resource.

``app.services.dashboard_service.DashboardSummary`` is a plain frozen
``@dataclass``, not a Pydantic model — this is a thin
``from_attributes=True`` wrapper around it, the same "reuse, don't
re-derive" technique this API layer uses everywhere a lower-layer object
needs a stable, ``extra="forbid"`` HTTP-facing shape. ``recent_requests``
(``list[Request]``), ``status_breakdown`` (``StatusBreakdown | None``),
and ``approval_throughput`` (``ApprovalThroughput | None``) are already
Pydantic models from ``app.models`` — reused directly, not re-wrapped,
matching the same precedent ``app.api.schemas.analytics`` already
documents for these exact two types.
"""

from __future__ import annotations

from pydantic import ConfigDict

from app.models import ApprovalThroughput, Request, StatusBreakdown
from app.models.base import EAHBaseModel

__all__ = ["DashboardSummaryOut"]


class DashboardSummaryOut(EAHBaseModel):
    """Wraps ``app.services.dashboard_service.DashboardSummary``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    open_requests_count: int
    pending_approvals_count: int
    unread_notifications_count: int
    recent_requests: list[Request]
    status_breakdown: StatusBreakdown | None
    approval_throughput: ApprovalThroughput | None
