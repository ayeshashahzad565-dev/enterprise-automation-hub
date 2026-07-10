"""Login, logout, and session-initialization UI.

Per this package's design brief, this page delegates authentication
entirely: credential verification is performed by the injected
``session.AuthGateway`` (see that module's docstring for why this
boundary exists), session lifecycle tracking is performed by
``app.auth.session_manager.SessionManager``, and identity representation
is ``app.auth.authentication.AuthenticatedIdentity``. This page itself
contains no credential verification, no token parsing, and no
authorization logic — only form rendering and delegation.
"""

from __future__ import annotations

import logging

import streamlit as st

from app.auth.exceptions import AuthenticationError

from app.pages import components, session

__all__ = ["render", "logout"]

logger = logging.getLogger(__name__)


def render() -> None:
    """Render the login form, or a redirect notice if already authenticated."""
    components.flash_messages()

    if session.is_authenticated():
        st.success("You are already signed in.")
        if st.button("Go to Dashboard"):
            session.set_active_page("dashboard")
            st.rerun()
        return

    st.markdown("## Sign in to Enterprise Automation Hub")

    with st.form("login_form"):
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")

    if not submitted:
        return

    if not email or not email.strip():
        session.push_flash("error", "Email is required.")
        st.rerun()
        return
    if not password:
        session.push_flash("error", "Password is required.")
        st.rerun()
        return

    container = session.get_container()

    with st.spinner("Signing in..."):
        try:
            result = container.auth_gateway.sign_in(email=email.strip(), password=password)
        except AuthenticationError as exc:
            logger.warning("Login failed for %s: %s", email, exc.message)
            session.push_flash("error", "Invalid email or password.")
            st.rerun()
            return

    session.set_identity(result.identity)
    container.session_manager.start_session(
        user_id=result.identity.user_id,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_at=result.expires_at,
    )
    session.set_active_page("dashboard")
    session.push_flash("success", f"Welcome back, {result.identity.email or 'there'}.")
    st.rerun()


def logout() -> None:
    """Sign the current user out, delegating invalidation to the auth gateway.

    Safe to call even if no identity is currently stored; in that case
    this function is a no-op beyond clearing local session state.
    """
    identity = session.get_identity()
    if identity is None:
        return

    container = session.get_container()
    try:
        container.auth_gateway.sign_out(identity)
    except AuthenticationError as exc:
        # Per the ADD's session-handling description, logout instructs
        # Supabase to invalidate the refresh token; a failure to do so
        # server-side should not prevent the local session from ending.
        logger.warning("Sign-out request failed for user %s: %s", identity.user_id, exc.message)

    container.session_manager.end_session()
    session.clear_identity()
    session.push_flash("info", "You have been signed out.")