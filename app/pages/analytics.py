"""Analytics dashboard UI.

Per this package's explicit instruction, this page displays analytics
returned by ``app.analytics`` directly (its ``AnalyticsProvider`` and
``ReportingProvider`` protocols), not via
``app.services.analytics_service``. Because
``app.analytics.AnalyticsEngine`` itself applies no role-based access
control (it is a read-only computation engine, not an authorization
boundary — see its own docstring), this page applies the same
least-privilege policy at the UI layer using ``app.auth.rbac`` directly,
which is reuse of an existing authorization primitive, not a
reimplementation of one.

This page performs no calculation of any kind: every number, table, and
chart is built directly from a DTO already computed by
``app.analytics``. Charts use Plotly, per the fixed technology stack.
"""

from __future__ import annotations

import logging

import plotly.express as px
import streamlit as st

from app.analytics.dto import TimeGranularity
from app.models.enums import UserRole

from app.pages import components, navigation, session

__all__ = ["render"]

logger = logging.getLogger(__name__)

_ALLOWED_ROLES = (UserRole.APPROVER, UserRole.ADMIN)


def render() -> None:
    """Render the analytics page."""
    components.flash_messages()
    identity = session.get_identity()
    assert identity is not None
    navigation.guard_role(identity, *_ALLOWED_ROLES)
    navigation.render_breadcrumbs("Analytics")

    st.markdown("## Analytics")

    tab_overview, tab_workload, tab_scoped = st.tabs(
        ["Overview", "Workload", "Workflow / Department Detail"]
    )
    with tab_overview:
        _render_overview()
    with tab_workload:
        _render_workload()
    with tab_scoped:
        _render_scoped_detail()


def _render_overview() -> None:
    """Render organization-wide dashboard metrics and a request trend chart."""
    container = session.get_container()
    provider = container.analytics_provider

    metrics = components.run_with_feedback(
        lambda: provider.get_dashboard_metrics(), loading_message="Loading dashboard metrics..."
    )
    if metrics is None:
        return

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        components.metric_card("Total Requests", metrics.total_requests)
    with col2:
        components.metric_card("Active", metrics.active_requests)
    with col3:
        components.metric_card("Completed", metrics.completed_requests)
    with col4:
        components.metric_card("Rejected", metrics.rejected_requests)

    st.divider()
    components.section_header("Approval Metrics")
    approval = metrics.approval_metrics
    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        components.metric_card(
            "Avg. Approval Time",
            f"{approval.average_stage_duration_seconds / 3600:.1f}h"
            if approval.average_stage_duration_seconds is not None
            else "N/A",
        )
    with col_b:
        rate = approval.throughput.completion_rate
        components.metric_card("Completion Rate", f"{rate:.1%}" if rate is not None else "N/A")
    with col_c:
        components.metric_card(
            "Escalations",
            approval.escalation_count if approval.escalation_count is not None else "N/A",
        )
    with col_d:
        components.metric_card(
            "Reminders Sent",
            approval.reminder_count if approval.reminder_count is not None else "N/A",
        )
    if approval.escalation_count is None or approval.reminder_count is None:
        st.caption(
            "Some figures show 'N/A' because they cannot be computed accurately from "
            "the current Repository Layer for this scope — see the Analytics Layer's "
            "documented limitations."
        )

    st.divider()
    components.section_header("Request Trend (Monthly)")
    trend = components.run_with_feedback(
        lambda: provider.get_request_trend(granularity=TimeGranularity.MONTH),
        loading_message="Loading trend...",
    )
    if trend is not None and trend.points:
        fig = px.bar(
            x=[point.label for point in trend.points],
            y=[point.value for point in trend.points],
            labels={"x": "Month", "y": "Requests Submitted"},
        )
        st.plotly_chart(fig, use_container_width=True)
    elif trend is not None:
        components.empty_state("No request activity to chart yet.")


def _render_workload() -> None:
    """Render per-user workload metrics for approvers and administrators."""
    container = session.get_container()
    provider = container.analytics_provider

    department_filter = st.text_input("Filter by department (optional)", key="workload_department")

    workload = components.run_with_feedback(
        lambda: provider.get_workload_summary(department=department_filter.strip() or None),
        loading_message="Loading workload summary...",
    )
    if workload is None:
        return

    if not workload:
        components.empty_state("No approvers or administrators match this filter.")
        return

    components.render_table(
        [
            {
                "Name": user.full_name,
                "Role": user.role.value.title(),
                "Approved": user.decisions_approved,
                "Rejected": user.decisions_rejected,
                "Pending Assigned": user.pending_assigned_count,
            }
            for user in workload
        ]
    )
    st.caption(
        "Average decision time per user is not shown — no Application Service exposes "
        "workflow stages filtered by decider, so this figure cannot be computed accurately."
    )


def _render_scoped_detail() -> None:
    """Render workflow-type-scoped or department-scoped metrics on demand."""
    container = session.get_container()
    provider = container.analytics_provider

    col_workflow, col_department = st.columns(2)

    with col_workflow:
        st.markdown("#### By Request Type")
        request_type = st.text_input("Request type", key="analytics_request_type")
        if request_type.strip():
            wf_metrics = components.run_with_feedback(
                lambda: provider.get_workflow_metrics(request_type.strip()),
                loading_message="Loading workflow metrics...",
            )
            if wf_metrics is not None:
                components.metric_card("Total Requests", wf_metrics.status_breakdown.total)
                components.metric_card(
                    "Throughput/Day",
                    f"{wf_metrics.throughput_per_day:.2f}"
                    if wf_metrics.throughput_per_day is not None
                    else "N/A (requires an explicit date range)",
                )

    with col_department:
        st.markdown("#### By Department")
        department = st.text_input("Department", key="analytics_department")
        if department.strip():
            dept_metrics = components.run_with_feedback(
                lambda: provider.get_department_metrics(department.strip()),
                loading_message="Loading department metrics...",
            )
            if dept_metrics is not None:
                components.metric_card("Total Requests", dept_metrics.status_breakdown.total)
                components.metric_card("Active Workload", dept_metrics.workload)
                avg = dept_metrics.approval_metrics.average_stage_duration_seconds
                components.metric_card(
                    "Avg. Approval Time",
                    f"{avg / 3600:.1f}h" if avg is not None else "N/A (department-scoped)",
                )