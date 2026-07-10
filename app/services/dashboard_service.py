"""High-level aggregation service producing presentation-ready dashboard DTOs.

Per this package's design brief, ``DashboardService`` is a thin
composition layer used by the (future) Streamlit Presentation Layer: it
calls ``RequestService``, ``ApprovalService``, ``NotificationService``,
and ``AnalyticsService`` — never a repository directly — and assembles
their results into a single ``DashboardSummary`` DTO optimized for
rendering. It contains no chart-generation code, no Streamlit import, and
no business logic of its own: every number in ``DashboardSummary`` is
produced by one of the four services above, not recomputed here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.auth.authentication import AuthenticatedIdentity
from app.database.repositories.base_repository import Page
from app.models import ApprovalThroughput, Request, StatusBreakdown
from app.models.enums import UserRole
from app.services.analytics_service import AnalyticsService
from app.services.approval_service import ApprovalService
from app.services.notification_service import NotificationService
from app.services.request_service import RequestService
from app.utils.decorators import log_calls, timed

__all__ = ["DashboardSummary", "DashboardService"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    """A presentation-ready summary of a caller's dashboard view.

    Attributes:
        open_requests_count: The number of the caller's own requests not
            yet in a terminal status.
        pending_approvals_count: The number of stages currently awaiting
            the caller's decision. Always ``0`` for an ``employee``, who
            has no approval queue.
        unread_notifications_count: The caller's unread notification
            count.
        recent_requests: The caller's most recently created requests
            (first page, newest first).
        status_breakdown: Organization-wide request status counts, or
            ``None`` for an ``employee`` caller (per
            ``AnalyticsService``'s least-privilege policy, this data is
            simply omitted rather than raising an error, so the dashboard
            degrades gracefully by role).
        approval_throughput: Organization-wide approval latency and
            completion-rate figures, or ``None`` for an ``employee``
            caller, for the same reason as ``status_breakdown``.
    """

    open_requests_count: int
    pending_approvals_count: int
    unread_notifications_count: int
    recent_requests: list[Request]
    status_breakdown: StatusBreakdown | None
    approval_throughput: ApprovalThroughput | None


class DashboardService:
    """Aggregates other Application Services into a single dashboard DTO."""

    def __init__(
        self,
        *,
        request_service: RequestService,
        approval_service: ApprovalService,
        notification_service: NotificationService,
        analytics_service: AnalyticsService,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            request_service: Used for the caller's own request count and
                recent requests list.
            approval_service: Used for the caller's pending approvals
                count.
            notification_service: Used for the caller's unread
                notification count.
            analytics_service: Used for organization-wide status and
                throughput figures, for approver/admin callers only.
        """
        self._request_service = request_service
        self._approval_service = approval_service
        self._notification_service = notification_service
        self._analytics_service = analytics_service
        self._logger = logging.getLogger(f"{__name__}.DashboardService")

    @timed()
    @log_calls()
    def get_dashboard_summary(self, identity: AuthenticatedIdentity) -> DashboardSummary:
        """Assemble the caller's dashboard summary.

        Args:
            identity: The authenticated caller.

        Returns:
            A ``DashboardSummary`` DTO ready for presentation.
        """
        recent_page = self._request_service.list_requests(
            identity, page=Page(page=1, page_size=5)
        )
        open_requests_result = self._request_service.list_requests(
            identity, page=Page(page=1, page_size=1)
        )

        pending_approvals_count = 0
        if identity.role in (UserRole.APPROVER, UserRole.ADMIN):
            pending_page = self._approval_service.list_pending_approvals(
                identity, page=Page(page=1, page_size=1)
            )
            pending_approvals_count = pending_page.total_records

        unread_count = self._notification_service.get_unread_count(identity)

        status_breakdown: StatusBreakdown | None = None
        approval_throughput: ApprovalThroughput | None = None
        if identity.role in (UserRole.APPROVER, UserRole.ADMIN):
            status_breakdown = self._analytics_service.get_status_breakdown(identity)
            approval_throughput = self._analytics_service.get_approval_throughput(identity)

        return DashboardSummary(
            open_requests_count=open_requests_result.total_records,
            pending_approvals_count=pending_approvals_count,
            unread_notifications_count=unread_count,
            recent_requests=recent_page.items,
            status_breakdown=status_breakdown,
            approval_throughput=approval_throughput,
        )