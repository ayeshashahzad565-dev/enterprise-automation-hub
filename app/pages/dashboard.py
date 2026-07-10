"""Role-aware dashboard page.

Per this package's design brief, every figure shown here comes from
``app.services.dashboard_service.DashboardService.get_dashboard_summary``,
which itself already applies the appropriate role-based scoping (an
employee sees only their own requests; an approver/admin additionally
sees organization-wide status and throughput figures). This page
performs no computation of its own.
"""

from __future__ import annotations

import logging

import streamlit as st

from app.database.repositories.base_repository import Page
from app.models.enums import UserRole

from app.pages import components, navigation, session

__all__ = ["render"]

logger = logging.getLogger(__name__)

_PAGE_KEY = "dashboard"


def render() -> None:
    """Render the current user's dashboard."""
    components.flash_messages()
    identity = session.get_identity()
    assert identity is not None
    navigation.render_breadcrumbs("Dashboard")

    container = session.get_container()
    summary = components.run_with_feedback(
        lambda: container.dashboard_service.get_dashboard_summary(identity),
        loading_message="Loading your dashboard...",
    )
    if summary is None:
        return

    st.markdown("## Dashboard")

    col1, col2, col3 = st.columns(3)
    with col1:
        components.metric_card("My Open Requests", summary.open_requests_count)
    with col2:
        components.metric_card("Pending Approvals", summary.pending_approvals_count)
    with col3:
        components.metric_card("Unread Notifications", summary.unread_notifications_count)

    if summary.status_breakdown is not None:
        st.divider()
        components.section_header("Organization Status Breakdown")
        rows = [
            {"Status": status.value.replace("_", " ").title(), "Count": count}
            for status, count in summary.status_breakdown.counts.items()
        ]
        components.render_table(rows)

    if summary.approval_throughput is not None:
        st.divider()
        components.section_header("Approval Throughput")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            avg = summary.approval_throughput.average_decision_seconds
            components.metric_card(
                "Avg. Decision Time",
                f"{avg / 3600:.1f}h" if avg is not None else "N/A",
            )
        with col_b:
            rate = summary.approval_throughput.completion_rate
            components.metric_card(
                "Completion Rate", f"{rate:.1%}" if rate is not None else "N/A"
            )
        with col_c:
            components.metric_card("Completed", summary.approval_throughput.completed_count)

    st.divider()
    components.section_header("My Recent Requests")
    if summary.recent_requests:
        components.render_table(
            [
                {
                    "Title": request.title,
                    "Type": request.request_type,
                    "Status": request.status.value.replace("_", " ").title(),
                    "Created": request.created_at.strftime("%Y-%m-%d"),
                }
                for request in summary.recent_requests
            ]
        )
    else:
        components.empty_state("You have no recent requests.")

    st.divider()
    components.section_header("Recent Notifications")
    notifications_page = components.run_with_feedback(
        lambda: container.notification_service.list_notifications(
            identity, page=Page(number=1, size=5)
        ),
        loading_message="Loading notifications...",
    )
    if notifications_page is not None:
        if notifications_page.items:
            for notification in notifications_page.items:
                icon = "🔵" if not notification.is_read else "⚪"
                st.markdown(f"{icon} **{notification.notification_type.value.title()}** — {notification.message}")
        else:
            components.empty_state("No notifications yet.", icon="🔔")