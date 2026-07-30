"""Structured report DTO construction.

Per this package's design brief, this module returns structured Python
objects only — no PDF, Excel, or CSV generation, and no chart rendering
of any kind. ``ReportingEngine`` depends only on the
``AnalyticsProvider`` protocol, never on ``AnalyticsEngine`` directly.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from app.analytics.dto import AnalyticsSummary, TimeGranularity
from app.analytics.exceptions import ReportingError
from app.analytics.interfaces import AnalyticsProvider
from app.utils.datetime_utils import utc_now

__all__ = ["ReportingEngine"]

logger = logging.getLogger(__name__)

#: The text substituted for any figure that is ``None`` (unavailable)
#: when building a narrative summary — never rendered as ``"None"`` or
#: silently omitted.
_UNAVAILABLE = "unavailable"


def _fmt(value, *, suffix: str = "") -> str:
    """Format an optional numeric value for inclusion in a narrative string.

    Args:
        value: The value to format, or ``None``.
        suffix: A unit suffix to append when ``value`` is not ``None``.

    Returns:
        The formatted string, or ``_UNAVAILABLE`` if ``value`` is
        ``None``.
    """
    if value is None:
        return _UNAVAILABLE
    return f"{value:.1f}{suffix}"


class ReportingEngine:
    """Assembles ``AnalyticsSummary`` report DTOs from an analytics provider."""

    def __init__(self, *, analytics_provider: AnalyticsProvider) -> None:
        """Initialize the engine with an injected analytics provider.

        Args:
            analytics_provider: Any object satisfying the
                ``AnalyticsProvider`` protocol (in production, an
                ``analytics_engine.AnalyticsEngine`` instance).
        """
        self._analytics = analytics_provider
        self._logger = logging.getLogger(f"{__name__}.ReportingEngine")

    def build_executive_summary(
        self,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> AnalyticsSummary:
        """Build a high-level, company-wide summary.

        Args:
            company_id: Restricts every figure to this company (tenant).
            created_after: Restrict to activity at or after this
                timestamp, if provided.
            created_before: Restrict to activity at or before this
                timestamp, if provided.

        Returns:
            An ``AnalyticsSummary`` with ``dashboard`` and a monthly
            ``trend`` populated.

        Raises:
            ReportingError: If any underlying analytics computation
                fails.
        """
        try:
            dashboard = self._analytics.get_dashboard_metrics(
                company_id=company_id, created_after=created_after, created_before=created_before
            )
            trend = self._analytics.get_request_trend(
                company_id=company_id,
                granularity=TimeGranularity.MONTH,
                created_after=created_after,
                created_before=created_before,
            )
        except Exception as exc:  # noqa: BLE001 - translated into a typed error below
            raise ReportingError(f"Failed to build executive summary: {exc}") from exc

        completion = dashboard.approval_metrics.throughput.completion_rate
        completion_text = f"{completion:.1%}" if completion is not None else _UNAVAILABLE
        narrative = (
            f"{dashboard.total_requests} total request(s): {dashboard.active_requests} active, "
            f"{dashboard.completed_requests} completed, {dashboard.rejected_requests} rejected. "
            f"Completion rate: {completion_text}."
        )

        return AnalyticsSummary(
            title="Executive Summary",
            generated_at=utc_now(),
            dashboard=dashboard,
            trend=trend,
            narrative=narrative,
        )

    def build_operational_summary(
        self,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> AnalyticsSummary:
        """Build a day-to-day operational summary.

        Args:
            company_id: Restricts every figure to this company (tenant).
            created_after: Restrict to activity at or after this
                timestamp, if provided.
            created_before: Restrict to activity at or before this
                timestamp, if provided.

        Returns:
            An ``AnalyticsSummary`` with ``dashboard`` and a daily
            ``trend`` populated.

        Raises:
            ReportingError: If any underlying analytics computation
                fails.
        """
        try:
            dashboard = self._analytics.get_dashboard_metrics(
                company_id=company_id, created_after=created_after, created_before=created_before
            )
            trend = self._analytics.get_request_trend(
                company_id=company_id,
                granularity=TimeGranularity.DAY,
                created_after=created_after,
                created_before=created_before,
            )
        except Exception as exc:  # noqa: BLE001 - translated into a typed error below
            raise ReportingError(f"Failed to build operational summary: {exc}") from exc

        escalations = dashboard.approval_metrics.escalation_count
        reminders = dashboard.approval_metrics.reminder_count
        escalations_text = str(escalations) if escalations is not None else _UNAVAILABLE
        reminders_text = str(reminders) if reminders is not None else _UNAVAILABLE
        narrative = (
            f"{dashboard.active_requests} request(s) currently active. "
            f"Escalations: {escalations_text}; Reminders sent: {reminders_text}."
        )

        return AnalyticsSummary(
            title="Operational Summary",
            generated_at=utc_now(),
            dashboard=dashboard,
            trend=trend,
            narrative=narrative,
        )

    def build_workflow_summary(
        self,
        request_type: str,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> AnalyticsSummary:
        """Build a summary scoped to a single request type within a company.

        Args:
            request_type: The request type to summarize.
            company_id: Restricts every figure to this company (tenant).
            created_after: Restrict to activity at or after this
                timestamp, if provided.
            created_before: Restrict to activity at or before this
                timestamp, if provided.

        Returns:
            An ``AnalyticsSummary`` with ``workflow_metrics`` and a
            weekly ``trend`` populated.

        Raises:
            ReportingError: If any underlying analytics computation
                fails.
        """
        try:
            workflow_metrics = self._analytics.get_workflow_metrics(
                request_type,
                company_id=company_id,
                created_after=created_after,
                created_before=created_before,
            )
            trend = self._analytics.get_request_trend(
                company_id=company_id,
                granularity=TimeGranularity.WEEK,
                request_type=request_type,
                created_after=created_after,
                created_before=created_before,
            )
        except Exception as exc:  # noqa: BLE001 - translated into a typed error below
            raise ReportingError(
                f"Failed to build workflow summary for '{request_type}': {exc}"
            ) from exc

        throughput_text = _fmt(workflow_metrics.throughput_per_day, suffix=" completed/day")
        narrative = (
            f"Workflow '{request_type}': {workflow_metrics.status_breakdown.total} request(s), "
            f"{throughput_text}."
        )

        return AnalyticsSummary(
            title=f"Workflow Summary: {request_type}",
            generated_at=utc_now(),
            workflow_metrics=(workflow_metrics,),
            trend=trend,
            narrative=narrative,
        )

    def build_department_summary(
        self,
        department: str,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> AnalyticsSummary:
        """Build a summary scoped to a single department within a company.

        Args:
            department: The department to summarize.
            company_id: Restricts every figure to this company (tenant).
            created_after: Restrict to activity at or after this
                timestamp, if provided.
            created_before: Restrict to activity at or before this
                timestamp, if provided.

        Returns:
            An ``AnalyticsSummary`` with ``department_metrics`` and a
            weekly ``trend`` populated.

        Raises:
            ReportingError: If any underlying analytics computation
                fails.
        """
        try:
            department_metrics = self._analytics.get_department_metrics(
                department,
                company_id=company_id,
                created_after=created_after,
                created_before=created_before,
            )
            trend = self._analytics.get_request_trend(
                company_id=company_id,
                granularity=TimeGranularity.WEEK,
                department=department,
                created_after=created_after,
                created_before=created_before,
            )
        except Exception as exc:  # noqa: BLE001 - translated into a typed error below
            raise ReportingError(
                f"Failed to build department summary for '{department}': {exc}"
            ) from exc

        narrative = (
            f"Department '{department}': {department_metrics.status_breakdown.total} "
            f"request(s), {department_metrics.workload} currently active."
        )

        return AnalyticsSummary(
            title=f"Department Summary: {department}",
            generated_at=utc_now(),
            department_metrics=(department_metrics,),
            trend=trend,
            narrative=narrative,
        )

    def build_user_summary(self, user_id: UUID, *, company_id: UUID) -> AnalyticsSummary:
        """Build a summary scoped to a single user within a company.

        Args:
            user_id: The user's id.
            company_id: The caller's own company (tenant); see
                ``AnalyticsProvider.get_user_metrics`` for how an
                out-of-company ``user_id`` is handled.

        Returns:
            An ``AnalyticsSummary`` with ``user_metrics`` populated.

        Raises:
            ReportingError: If the underlying analytics computation
                fails.
        """
        try:
            user_metrics = self._analytics.get_user_metrics(user_id, company_id=company_id)
        except Exception as exc:  # noqa: BLE001 - translated into a typed error below
            raise ReportingError(f"Failed to build user summary for {user_id}: {exc}") from exc

        narrative = (
            f"{user_metrics.full_name} ({user_metrics.role.value}): "
            f"{user_metrics.decisions_made} decision(s) made, "
            f"{user_metrics.pending_assigned_count} pending assignment(s)."
        )

        return AnalyticsSummary(
            title=f"User Summary: {user_metrics.full_name}",
            generated_at=utc_now(),
            user_metrics=(user_metrics,),
            narrative=narrative,
        )
