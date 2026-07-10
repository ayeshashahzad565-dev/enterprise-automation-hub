"""Administrative page: system status, scheduler health, and configuration summary.

Per this package's design brief, this page performs no maintenance
action that is not already exposed through the finalized Application
Service Layer, ``app.scheduler``, or ``app.config`` — no button here is
wired to a fake or partial implementation. Where the Deployment Guide
describes an operational action (applying a migration, restoring a
backup) that is genuinely outside this application's own UI (an
operator-run Alembic/Supabase-platform action, per DG Sections 11 and
17), this page states that plainly instead of fabricating a button for
it.

No secret configuration value is ever rendered on this page — only the
non-secret fields of ``app.config.settings.AppSettings`` are displayed.
"""

from __future__ import annotations

import logging

import streamlit as st

from app.models.enums import UserRole

from app.pages import components, navigation, session

__all__ = ["render"]

logger = logging.getLogger(__name__)


def render() -> None:
    """Render the admin page."""
    components.flash_messages()
    identity = session.get_identity()
    assert identity is not None
    navigation.guard_role(identity, UserRole.ADMIN)
    navigation.render_breadcrumbs("Admin")

    st.markdown("## System Administration")

    tab_status, tab_scheduler, tab_config, tab_maintenance = st.tabs(
        ["System Status", "Scheduler Health", "Configuration", "Maintenance"]
    )
    with tab_status:
        _render_system_status()
    with tab_scheduler:
        _render_scheduler_health()
    with tab_config:
        _render_configuration_summary()
    with tab_maintenance:
        _render_maintenance()


def _render_system_status() -> None:
    """Render a high-level system status summary."""
    container = session.get_container()
    identity = session.get_identity()
    assert identity is not None

    components.section_header("Application")
    col1, col2 = st.columns(2)
    with col1:
        components.metric_card("Environment", container.settings.environment.value.title())
    with col2:
        # Per DG Section 13.2's static-leader-flag design, exactly one
        # instance is ever wired with a non-None scheduler_stats value —
        # a non-leader instance's AppContainer.scheduler_stats is None by
        # construction, so its mere presence already answers "is the
        # Scheduler active on this instance," with no separate
        # is_running check needed.
        components.metric_card(
            "Scheduler Active on This Instance", "Yes" if container.scheduler_stats is not None else "No"
        )

    st.divider()
    components.section_header("My Notifications")
    unread_count = components.run_with_feedback(
        lambda: container.notification_service.get_unread_count(identity),
        loading_message="Checking notifications...",
    )
    if unread_count is not None:
        components.metric_card("My Unread Notifications", unread_count)
    st.caption(
        "Organization-wide notification statistics are not shown: no Application "
        "Service exposes a query across every recipient's notifications."
    )


def _render_scheduler_health() -> None:
    """Render per-job scheduler execution statistics."""
    container = session.get_container()

    if container.scheduler_stats is None:
        st.info(
            "This application instance is not configured as the Scheduler leader "
            "(per the Deployment Guide's SCHEDULER_LEADER convention), so no "
            "execution statistics are available here."
        )
        return

    all_stats = container.scheduler_stats.get_all_statistics()
    if not all_stats:
        components.empty_state("No jobs are currently registered.")
        return

    rows = []
    for name, stats in all_stats.items():
        rows.append(
            {
                "Job": name,
                "Currently Running": "Yes" if stats.currently_running else "No",
                "Runs": stats.run_count,
                "Successes": stats.success_count,
                "Failures": stats.failure_count,
                "Skipped (Overlap)": stats.skipped_overlap_count,
                "Last Run": stats.last_finished_at.strftime("%Y-%m-%d %H:%M:%S")
                if stats.last_finished_at
                else "Never",
                "Last Duration (s)": f"{stats.last_duration_seconds:.2f}"
                if stats.last_duration_seconds is not None
                else "N/A",
                "Next Run": stats.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
                if stats.next_run_time
                else "N/A",
                "Last Error": stats.last_error or "None",
            }
        )
    components.render_table(rows)


def _render_configuration_summary() -> None:
    """Render non-secret configuration values."""
    container = session.get_container()
    settings = container.settings

    st.warning("Only non-secret configuration values are shown below.")

    components.section_header("Scheduler")
    components.render_table(
        [
            {"Setting": "Escalation Interval (minutes)", "Value": settings.scheduler.escalation_interval_minutes},
            {"Setting": "Reminder Interval (hours)", "Value": settings.scheduler.reminder_interval_hours},
            {"Setting": "Analytics Interval (hours)", "Value": settings.scheduler.analytics_interval_hours},
        ]
    )

    components.section_header("Rate Limits")
    components.render_table(
        [
            {"Setting": "Read requests/minute", "Value": settings.rate_limits.read_per_minute},
            {"Setting": "Write requests/minute", "Value": settings.rate_limits.write_per_minute},
            {"Setting": "Upload requests/minute", "Value": settings.rate_limits.upload_per_minute},
            {"Setting": "Login attempts/5 minutes", "Value": settings.rate_limits.login_per_5_minutes},
        ]
    )

    components.section_header("Notifications")
    components.render_table(
        [{"Setting": "Email dispatch enabled", "Value": "Yes" if settings.smtp.is_enabled else "No"}]
    )

    components.section_header("Workflow")
    components.render_table(
        [{"Setting": "Default Escalation (hours)", "Value": settings.workflow.default_escalation_hours}]
    )


def _render_maintenance() -> None:
    """Render an honest statement of what maintenance actions are available."""
    components.section_header("Maintenance")
    st.info(
        "No maintenance action is exposed through this UI. Per the Deployment Guide, "
        "database schema migrations are applied via Alembic, and backups and "
        "point-in-time recovery are performed through Supabase's own platform "
        "tooling — both are operator-run procedures outside this application, "
        "not actions this Application Service Layer currently supports."
    )