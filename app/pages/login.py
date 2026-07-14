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

__all__ = ["render", "logout", "handle_auth_callback", "render_password_reset"]

logger = logging.getLogger(__name__)

#: Callback ``type`` values (per Supabase's confirmation-email query
#: parameter) that require the user to set a new password before
#: proceeding: a recovery link's whole purpose is a password reset, and
#: an invited user has no password yet.
_RECOVERY_LIKE_CALLBACK_TYPES = frozenset({"recovery", "invite"})

#: The complete set of query-parameter keys a Supabase Auth callback may
#: arrive with, across the PKCE (``code``) and token (``access_token``/
#: ``refresh_token``) redirect shapes, plus the error shape Supabase uses
#: for an invalid/expired link. Cleared from the URL once processed.
_AUTH_CALLBACK_PARAM_KEYS = (
    "code",
    "type",
    "access_token",
    "refresh_token",
    "token_hash",
    "error",
    "error_description",
    "error_code",
)


def _clear_auth_callback_params() -> None:
    """Remove only the known Supabase auth-callback keys from the URL.

    Deliberately narrower than ``st.query_params.clear()`` so any other,
    unrelated query parameter a page might use in the future survives.
    """
    for key in _AUTH_CALLBACK_PARAM_KEYS:
        if key in st.query_params:
            del st.query_params[key]


def handle_auth_callback() -> bool:
    """Process a Supabase Auth callback arriving via URL query parameters.

    Covers the signup-confirmation, invite, and password-recovery email
    links Supabase redirects back to this application with, in either of
    its two redirect shapes: a PKCE ``?code=...`` to exchange, or a
    direct ``?access_token=...&refresh_token=...`` pair to restore. On
    success, this establishes the session exactly as a normal sign-in
    does (``session.set_identity`` + ``session_manager.start_session``),
    marks recovery/invite links as needing a new password, and always
    strips the auth parameters from the URL before returning so a
    subsequent rerun (e.g. a widget interaction) never re-processes an
    already-consumed code or exposes tokens in the address bar.

    Returns:
        ``True`` if a callback was present and has been handled (the
        caller should stop rendering for this run; a ``st.rerun()`` has
        already been triggered). ``False`` if there was nothing to
        process, in which case rendering should continue as normal.
    """
    params = st.query_params
    code = params.get("code")
    access_token = params.get("access_token")
    refresh_token = params.get("refresh_token")
    callback_type = params.get("type")
    error_description = params.get("error_description") or params.get("error")

    if not code and not (access_token and refresh_token):
        if error_description:
            logger.warning("Auth callback arrived with an error: %s", error_description)
            _clear_auth_callback_params()
            session.push_flash(
                "error", "This link is invalid or has expired. Please try again."
            )
            st.rerun()
            return True
        return False

    container = session.get_container()
    try:
        if code:
            result = container.auth_gateway.exchange_code_for_session(code=code)
        else:
            result = container.auth_gateway.restore_session(
                access_token=access_token, refresh_token=refresh_token
            )
    except AuthenticationError as exc:
        logger.warning("Auth callback processing failed: %s", exc.message)
        _clear_auth_callback_params()
        session.push_flash("error", "This link is invalid or has expired. Please try again.")
        st.rerun()
        return True

    _clear_auth_callback_params()

    session.set_identity(result.identity)
    container.session_manager.start_session(
        user_id=result.identity.user_id,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_at=result.expires_at,
    )

    if callback_type in _RECOVERY_LIKE_CALLBACK_TYPES:
        session.set_recovery_pending()
        session.push_flash("info", "Please set a new password to continue.")
    else:
        session.set_active_page("dashboard")
        session.push_flash("success", f"Welcome, {result.identity.email or 'there'}.")

    st.rerun()
    return True


def render_password_reset() -> None:
    """Render the "set a new password" form for a pending recovery/invite session.

    Shown by ``app.pages.navigation.render_app`` in place of the rest of
    the application whenever ``session.is_recovery_pending()`` is
    ``True``, so a recovery or invite link's session cannot be used to
    reach any other authenticated route until a new password is set.
    """
    components.flash_messages()

    st.markdown("## Set a new password")
    st.caption("Please choose a new password to finish signing in.")

    with st.form("password_reset_form"):
        new_password = st.text_input("New password", type="password")
        confirm_password = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Update password", type="primary")

    if not submitted:
        return

    if not new_password:
        session.push_flash("error", "Password is required.")
        st.rerun()
        return
    if new_password != confirm_password:
        session.push_flash("error", "Passwords do not match.")
        st.rerun()
        return

    container = session.get_container()
    current_session = container.session_manager.get_current_session(allow_expired=True)

    with st.spinner("Updating password..."):
        try:
            container.auth_gateway.update_password(
                access_token=current_session.access_token,
                refresh_token=current_session.refresh_token,
                new_password=new_password,
            )
        except AuthenticationError as exc:
            logger.warning("Password update failed for %s: %s", current_session.user_id, exc.message)
            session.push_flash("error", "Unable to update your password. Please try again.")
            st.rerun()
            return

    session.clear_recovery_pending()
    session.set_active_page("dashboard")
    session.push_flash("success", "Your password has been updated.")
    st.rerun()


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
    session.clear_recovery_pending()
    session.push_flash("info", "You have been signed out.")