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

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
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
        # A separate size=1 call to read only .total_records would be a
        # second, redundant round trip: PagedResult.total_records already
        # reflects the full matching count regardless of the requested
        # page size, so this one size=5 call alone answers both "the 5
        # most recent requests" and "how many open requests total".
        # These calls are independent — none consumes another's result —
        # but each is a separate round trip to a remote Supabase region
        # (~240ms). Issued sequentially, an approver/admin dashboard paid
        # the *sum* of up to five of them; issued concurrently it costs
        # roughly the slowest single one.
        #
        # Each submission gets its OWN contextvars.copy_context()
        # snapshot, for two independent reasons:
        #   1. Correctness. The RLS-scoped tenant database client that
        #      app.api.dependencies.bind_tenant_database_client binds for
        #      this request lives in a ContextVar. A bare pool.submit(fn)
        #      starts its worker with a fresh, empty context, so every
        #      repository would silently fall back to its default
        #      service-role client — bypassing Row-Level Security and
        #      returning rows this caller should not see. copy_context()
        #      carries the binding across the thread hop. (It is captured
        #      here, in the calling thread, where the binding is visible:
        #      anyio already propagates the request's context into the
        #      threadpool worker running this method.)
        #   2. A single Context object cannot be entered by more than one
        #      thread at a time — reusing one shared snapshot across all
        #      five submissions raises "cannot enter context ... is
        #      already entered". Hence one snapshot per submission.
        is_approver_or_admin = identity.role in (UserRole.APPROVER, UserRole.ADMIN)
        with ThreadPoolExecutor(max_workers=5) as pool:
            recent_future = pool.submit(
                contextvars.copy_context().run,
                self._request_service.list_requests,
                identity,
                page=Page(number=1, size=5),
            )
            unread_future = pool.submit(
                contextvars.copy_context().run,
                self._notification_service.get_unread_count,
                identity,
            )
            pending_future = (
                pool.submit(
                    contextvars.copy_context().run,
                    self._approval_service.list_pending_approvals,
                    identity,
                    page=Page(number=1, size=1),
                )
                if is_approver_or_admin
                else None
            )
            status_future = (
                pool.submit(
                    contextvars.copy_context().run,
                    self._analytics_service.get_status_breakdown,
                    identity,
                )
                if is_approver_or_admin
                else None
            )
            throughput_future = (
                pool.submit(
                    contextvars.copy_context().run,
                    self._analytics_service.get_approval_throughput,
                    identity,
                )
                if is_approver_or_admin
                else None
            )

            recent_page = recent_future.result()
            unread_count = unread_future.result()
            pending_approvals_count = pending_future.result().total_records if pending_future else 0
            status_breakdown: StatusBreakdown | None = (
                status_future.result() if status_future else None
            )
            approval_throughput: ApprovalThroughput | None = (
                throughput_future.result() if throughput_future else None
            )

        return DashboardSummary(
            open_requests_count=recent_page.total_records,
            pending_approvals_count=pending_approvals_count,
            unread_notifications_count=unread_count,
            recent_requests=recent_page.items,
            status_breakdown=status_breakdown,
            approval_throughput=approval_throughput,
        )
