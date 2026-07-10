"""Application service coordinating read-only analytics queries.

Per the ADD's Component Breakdown, ``AnalyticsService`` queries
aggregated data and prepares it for visualization; this module implements
exactly the query-coordination half of that description — it performs no
chart generation of any kind (that remains the Presentation Layer's
responsibility, using Plotly, per the ADD).

This service applies one authorization policy not explicitly enumerated
in any architecture document: organization-wide analytics (status
breakdowns, volume by type/department, approval throughput) are
restricted to ``approver`` and ``admin`` roles. No document defines an
analytics-specific permission, so this is a deliberate, minimal,
least-privilege default applied at the service layer — documented here
plainly as a services-layer policy decision, not an assertion that the
API Design Document specifies it.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.auth.authentication import AuthenticatedIdentity
from app.auth.rbac import require_role
from app.database.exceptions import DatabaseError
from app.database.repositories.analytics_repository import AnalyticsRepository
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.base_repository import Page
from app.models import ApprovalThroughput, StatusBreakdown, VolumeByKey
from app.models.enums import UserRole
from app.services.exceptions import translate_auth_error, translate_database_error
from app.utils.decorators import log_calls, timed

__all__ = ["AnalyticsService"]

logger = logging.getLogger(__name__)

#: The roles permitted to access organization-wide analytics, per this
#: module's documented, services-layer least-privilege policy.
_ANALYTICS_ROLES: tuple[UserRole, ...] = (UserRole.APPROVER, UserRole.ADMIN)


class AnalyticsService:
    """Coordinates dashboard metrics, approval throughput, and workload queries."""

    def __init__(
        self,
        *,
        analytics_repo: AnalyticsRepository,
        approval_repo: ApprovalRepository,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            analytics_repo: Read-only aggregate queries against
                ``requests`` and ``workflow_stages``.
            approval_repo: Used for pending-workload counts via its
                pending-approvals query.
        """
        self._analytics_repo = analytics_repo
        self._approval_repo = approval_repo
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
    def get_volume_by_type(
        self,
        identity: AuthenticatedIdentity,
        *,
        department: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> VolumeByKey:
        """Return request counts grouped by request type.

        Args:
            identity: The authenticated caller.
            department: Restrict to this department, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.

        Returns:
            A ``VolumeByKey`` domain model.

        Raises:
            PermissionDeniedError: If ``identity`` is an employee.
        """
        self._require_analytics_access(identity)
        try:
            result = self._analytics_repo.count_requests_by_type(
                department=department, created_after=created_after, created_before=created_before
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        return VolumeByKey(counts=result.counts, total=result.total)

    @timed()
    @log_calls()
    def get_volume_by_department(
        self,
        identity: AuthenticatedIdentity,
        *,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> VolumeByKey:
        """Return request counts grouped by department.

        Args:
            identity: The authenticated caller.
            request_type: Restrict to this request type, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before this
                timestamp, if provided.

        Returns:
            A ``VolumeByKey`` domain model.

        Raises:
            PermissionDeniedError: If ``identity`` is an employee.
        """
        self._require_analytics_access(identity)
        try:
            result = self._analytics_repo.count_requests_by_department(
                request_type=request_type, created_after=created_after, created_before=created_before
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        return VolumeByKey(counts=result.counts, total=result.total)

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
                request_type=request_type, created_after=created_after, created_before=created_before
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        return ApprovalThroughput(
            average_decision_seconds=result.average_decision_seconds,
            completed_count=result.completed_count,
            rejected_count=result.rejected_count,
            completion_rate=result.completion_rate,
        )

    @timed()
    @log_calls()
    def get_sla_statistics(
        self,
        identity: AuthenticatedIdentity,
        *,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> ApprovalThroughput:
        """Return SLA-relevant statistics: average decision time and completion rate.

        This is presented as a distinct, business-meaningful method name
        over the same underlying aggregate as ``get_approval_throughput``
        — the DSD and WEDD define no separate SLA-specific data source,
        so this method does not duplicate any query logic; it is a
        semantically named alias over the same repository call.

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
        return self.get_approval_throughput(
            identity,
            request_type=request_type,
            created_after=created_after,
            created_before=created_before,
        )

    @timed()
    @log_calls()
    def get_pending_workload(self, identity: AuthenticatedIdentity) -> int:
        """Return the number of stages currently pending the caller's decision.

        Args:
            identity: The authenticated approver or administrator.

        Returns:
            The count of pending stages assigned to the caller (by
            specific assignment or role eligibility).

        Raises:
            PermissionDeniedError: If ``identity`` is an employee.
        """
        self._require_analytics_access(identity)
        try:
            result = self._approval_repo.list_pending_for_approver(
                assigned_to=identity.user_id, assigned_role=identity.role, page=Page(page_size=1)
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        return result.total_records

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