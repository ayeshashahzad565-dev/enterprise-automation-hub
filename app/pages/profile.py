"""Profile summary, preferences, notification settings, and password-change entry point.

No Application Service in the finalized architecture exposes reading or
updating an arbitrary user's ``profiles`` row for display purposes
(``ProfileRepository`` exists at the persistence layer, but ``app/pages``
must never call a repository directly, and no service wraps a "get my
profile" or "update my profile" operation). This page therefore displays
only the fields already present on the current session's
``AuthenticatedIdentity`` (id, email, role) and states the limitation
plainly rather than fabricating a profile-editing form with nothing real
behind it.

Password change is delegated entirely to the injected
``session.AuthGateway`` — Supabase Auth's own password-reset-email flow
— consistent with every other authentication concern in this
application.
"""

from __future__ import annotations

import logging

import streamlit as st

from app.pages import components, navigation, session

__all__ = ["render"]

logger = logging.getLogger(__name__)


def render() -> None:
    """Render the profile page."""
    components.flash_messages()
    identity = session.get_identity()
    assert identity is not None
    navigation.render_breadcrumbs("Profile")

    st.markdown("## My Profile")

    components.section_header("Account")
    components.render_table(
        [
            {"Field": "User ID", "Value": str(identity.user_id)},
            {"Field": "Email", "Value": identity.email or "N/A"},
            {"Field": "Role", "Value": identity.role.value.title()},
        ]
    )
    st.caption(
        "Additional profile details (display name, department) and profile editing "
        "are not available: no Application Service currently exposes reading or "
        "updating an arbitrary user's profile."
    )

    st.divider()
    components.section_header("Notification Preferences")
    _render_notification_settings()

    st.divider()
    components.section_header("Password")
    _render_password_reset()


def _render_notification_settings() -> None:
    """Render the caller's current notification read status summary.

    No preference-toggling service exists (e.g. "disable email
    notifications"); this section shows the caller's own unread-count
    figure, which the Application Service Layer does support, rather
    than a settings form with no backing capability.
    """
    container = session.get_container()
    identity = session.get_identity()
    assert identity is not None

    unread_count = components.run_with_feedback(
        lambda: container.notification_service.get_unread_count(identity),
        loading_message="Loading notification status...",
    )
    if unread_count is not None:
        components.metric_card("Unread Notifications", unread_count)
    st.caption(
        "Per-channel notification preferences (e.g. disabling email) are not "
        "configurable: the Notification Layer dispatches both in-app and email "
        "notifications for every event by default, per the Architecture Design "
        "Document, with no per-user override currently exposed."
    )


def _render_password_reset() -> None:
    """Render the password-change entry point, delegating entirely to the auth gateway."""
    container = session.get_container()
    identity = session.get_identity()
    assert identity is not None

    st.caption(
        "Password changes are handled by Supabase Auth. Clicking below sends a "
        "password reset link to your email address."
    )
    if st.button("Send Password Reset Email"):
        components.run_with_feedback(
            lambda: container.auth_gateway.send_password_reset_email(identity.email or ""),
            loading_message="Sending reset email...",
            success_message="A password reset email has been sent, if an account exists for this address.",
        )