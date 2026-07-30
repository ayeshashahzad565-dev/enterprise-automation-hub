"""Application service coordinating read-only analytics queries.

Per the ADD's Component Breakdown, ``AnalyticsService`` queries
aggregated data and prepares it for visualization; this module implements
exactly the query-coordination half of that description — it performs no
chart generation of any kind (that remains the Presentation Layer's
responsibility, using Plotly, per the ADD).

This service applies one authorization policy not explicitly enumerated
in any architecture document: organization-wide analytics (status
breakdowns, approval throughput) are restricted to ``approver`` and
``admin`` roles. No document defines an analytics-specific permission,
so this is a deliberate, minimal, least-privilege default applied at
the service layer — documented here plainly as a services-layer policy
decision, not an assertion that the API Design Document specifies it.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.auth.authentication import AuthenticatedIdentity
from app.auth.rbac import require_role
from app.database.exceptions import DatabaseError
from app.database.repositories.analytics_repository import AnalyticsRepository
from app.models import ApprovalThroughput, StatusBreakdown
from app.models.enums import UserRole
from app.services.exceptions import translate_auth_error, translate_database_error
from app.utils.decorators import log_calls, timed

__all__ = ["AnalyticsService"]

logger = logging.getLogger(__name__)

#: The roles permitted to access organization-wide analytics, per this
#: module's documented, services-layer least-privilege policy.
_ANALYTICS_ROLES: tuple[UserRole, ...] = (UserRole.APPROVER, UserRole.ADMIN)


class AnalyticsService:
    """Coordinates status-breakdown and approval-throughput analytics queries."""

    def __init__(self, *, analytics_repo: AnalyticsRepository) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            analytics_repo: Read-only aggregate queries against
                ``requests`` and ``workflow_stages``.
        """
        self._analytics_repo = analytics_repo
        self._logger = logging.getLogger(f"{__name__}.AnalyticsService")

    @timed()
    @log_calls()
    def get_status_breakdown(
        self,
        identity: AuthenticatedIdentity,
        *,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> StatusBreakdown:
        """Return request counts grouped by lifecycle status.

        Args:
            identity: The authenticated caller.
            department: Restrict to this department, if provided.
            request_type: Restrict to this request type, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.

        Returns:
            A ``StatusBreakdown`` domain model.

        Raises:
            PermissionDeniedError: If ``identity`` is an employee.
        """
        self._require_analytics_access(identity)
        try:
            result = self._analytics_repo.count_requests_by_status(
                company_id=identity.company_id,
                department=department,
                request_type=request_type,
                created_after=created_after,
                created_before=created_before,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        return StatusBreakdown(counts=result.counts, total=result.total)

    @timed()
    @log_calls()
    def get_approval_throughput(
        self,
        identity: AuthenticatedIdentity,
        *,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> ApprovalThroughput:
        """Return average decision latency and completion rate.

        Args:
            identity: The authenticated caller.
            request_type: Restrict to this request type, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.

        Returns:
            An ``ApprovalThroughput`` domain model.

        Raises:
            PermissionDeniedError: If ``identity`` is an employee.
        """
        self._require_analytics_access(identity)
        try:
            result = self._analytics_repo.approval_throughput(
                company_id=identity.company_id,
                request_type=request_type,
                created_after=created_after,
                created_before=created_before,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        return ApprovalThroughput(
            average_decision_seconds=result.average_decision_seconds,
            completed_count=result.completed_count,
            rejected_count=result.rejected_count,
            completion_rate=result.completion_rate,
        )

    def _require_analytics_access(self, identity: AuthenticatedIdentity) -> None:
        """Enforce this module's documented least-privilege analytics policy.

        Args:
            identity: The authenticated caller.

        Raises:
            PermissionDeniedError: If ``identity.role`` is not in
                ``_ANALYTICS_ROLES``.
        """
        try:
            require_role(identity.role, *_ANALYTICS_ROLES)
        except Exception as exc:  # noqa: BLE001
            raise translate_auth_error(exc) from exc
