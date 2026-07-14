"""Centralized Streamlit session state management.

Per this package's design brief, this module is the single place in
``app.pages`` that touches ``st.session_state`` directly — every page
module reads and writes session state exclusively through the typed
functions defined here, never through ``st.session_state`` itself. This
module also defines ``AppContainer``, the dependency-injection bundle
every page consumes, and ``AuthGateway``, the one protocol boundary this
package needs but no lower layer implements (see this module's
``AuthGateway`` docstring for why).

This module contains no authentication logic of its own: it stores and
retrieves an already-constructed ``AuthenticatedIdentity``, and it never
constructs, verifies, or refreshes one itself. Constructing the
``AppContainer`` (wiring real repositories, services, and an
``AuthGateway`` implementation) is the responsibility of a composition
root outside this package (a bootstrap script) — this module only
defines the container's shape and how to store/retrieve it for the
duration of a Streamlit session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

import streamlit as st

from app.analytics.interfaces import AnalyticsProvider, ReportingProvider
from app.auth.authentication import AuthenticatedIdentity
from app.auth.session_manager import SessionManager
from app.config.settings import AppSettings
from app.scheduler.interfaces import SchedulerStatisticsProvider
from app.services.approval_service import ApprovalService
from app.services.dashboard_service import DashboardService
from app.services.notification_service import NotificationService
from app.services.request_service import RequestService
from app.services.workflow_definition_service import WorkflowDefinitionService

__all__ = [
    "FlashMessage",
    "FlashLevel",
    "AuthResult",
    "AuthGateway",
    "AppContainer",
    "set_container",
    "get_container",
    "has_container",
    "get_identity",
    "set_identity",
    "clear_identity",
    "is_authenticated",
    "set_recovery_pending",
    "is_recovery_pending",
    "clear_recovery_pending",
    "get_active_page",
    "set_active_page",
    "get_filters",
    "set_filters",
    "get_pagination",
    "set_pagination",
    "reset_pagination",
    "push_flash",
    "drain_flash_messages",
    "get_cached_selection",
    "set_cached_selection",
    "clear_cached_selection",
    "request_confirmation",
    "is_confirmation_pending",
    "clear_confirmation",
]

logger = logging.getLogger(__name__)

FlashLevel = Literal["success", "error", "warning", "info"]

# ---------------------------------------------------------------------------
# Session state key constants — the only place these string keys are
# spelled out, so a rename is a one-line change.
# ---------------------------------------------------------------------------
_KEY_CONTAINER = "eah_container"
_KEY_IDENTITY = "eah_identity"
_KEY_ACTIVE_PAGE = "eah_active_page"
_KEY_FILTERS = "eah_filters"
_KEY_PAGINATION = "eah_pagination"
_KEY_FLASH_MESSAGES = "eah_flash_messages"
_KEY_CACHED_SELECTIONS = "eah_cached_selections"
_KEY_PENDING_CONFIRMATIONS = "eah_pending_confirmations"
_KEY_RECOVERY_PENDING = "eah_recovery_pending"

_DEFAULT_PAGE_NUMBER = 1
_DEFAULT_PAGE_SIZE = 20


@dataclass(frozen=True, slots=True)
class FlashMessage:
    """A single, queued, one-shot notification banner.

    Attributes:
        level: The visual severity of the message.
        text: The message body.
    """

    level: FlashLevel
    text: str


@dataclass(frozen=True, slots=True)
class AuthResult:
    """The outcome of a successful sign-in, as returned by an ``AuthGateway``.

    Attributes:
        identity: The resulting authenticated identity.
        access_token: The Supabase access token, for
            ``app.auth.session_manager.SessionManager`` to track.
        refresh_token: The Supabase refresh token.
        expires_at: The access token's expiry timestamp.
    """

    identity: AuthenticatedIdentity
    access_token: str
    refresh_token: str
    expires_at: datetime


@runtime_checkable
class AuthGateway(Protocol):
    """The one capability this package needs that no finalized lower
    layer provides: verifying a user's credentials against Supabase Auth
    and issuing a real session.

    Per ``app.auth``'s own documented design, that package deliberately
    performs no network access — it builds ``AuthenticatedIdentity``
    from *already-verified* claims and leaves obtaining those claims to
    a caller. No module in ``app.services`` wraps this either. This
    protocol is therefore the explicit, injected boundary
    ``login.py`` depends on, mirroring the same pattern already used for
    ``app.notifications.interfaces.EmailSender``: this package defines
    the interface and consumes it; a concrete implementation (calling
    Supabase's ``client.auth.sign_in_with_password`` and
    ``client.auth.sign_out``) is provided by the composition root that
    constructs ``AppContainer``, not by anything in ``app.pages``.
    """

    def sign_in(self, *, email: str, password: str) -> AuthResult:
        """Verify credentials and return a new session.

        Args:
            email: The user's email address.
            password: The user's password.

        Returns:
            The resulting ``AuthResult``.

        Raises:
            app.auth.exceptions.AuthenticationError: If the credentials
                are invalid.
        """
        ...

    def sign_out(self, identity: AuthenticatedIdentity) -> None:
        """Invalidate a user's current session.

        Args:
            identity: The identity whose session should be invalidated.
        """
        ...

    def send_password_reset_email(self, email: str) -> None:
        """Trigger Supabase Auth's password reset flow for an address.

        Args:
            email: The address to send a reset link to.
        """
        ...

    def exchange_code_for_session(self, *, code: str) -> AuthResult:
        """Exchange a Supabase PKCE auth callback code for a real session.

        Used for the signup-confirmation, invite, and recovery email
        links Supabase redirects back to this application with a
        ``?code=...`` query parameter.

        Args:
            code: The ``code`` value from the callback URL.

        Returns:
            The resulting ``AuthResult``.

        Raises:
            app.auth.exceptions.AuthenticationError: If the code is
                invalid, expired, or already used.
        """
        ...

    def restore_session(self, *, access_token: str, refresh_token: str) -> AuthResult:
        """Restore a session directly from a callback's access/refresh tokens.

        Args:
            access_token: The access token from the callback URL.
            refresh_token: The refresh token from the callback URL.

        Returns:
            The resulting ``AuthResult``.

        Raises:
            app.auth.exceptions.AuthenticationError: If the tokens are
                invalid or expired.
        """
        ...

    def update_password(
        self, *, access_token: str, refresh_token: str, new_password: str
    ) -> None:
        """Set a new password for the user identified by a session's tokens.

        Used to complete the recovery/invite flow, via Supabase Auth's
        ``client.auth.update_user({"password": new_password})``.

        Args:
            access_token: The access token of the session to act as.
            refresh_token: The refresh token of the session to act as.
            new_password: The new password to set.

        Raises:
            app.auth.exceptions.AuthenticationError: If Supabase rejects
                the update.
        """
        ...


@dataclass(frozen=True, slots=True)
class AppContainer:
    """The dependency-injection bundle every page in this package consumes.

    An instance of this class is constructed exactly once, by a
    composition root outside this package, and stored via
    ``set_container`` before any page is rendered. No page module
    constructs a service, a repository, or a Supabase client itself.

    Attributes:
        request_service: Orchestrates request creation, editing,
            withdrawal, and reads.
        approval_service: Orchestrates stage approval, rejection, and
            the pending-approvals queue.
        workflow_definition_service: Orchestrates workflow definition
            lifecycle operations.
        notification_service: Orchestrates notification reads and
            read-status updates.
        dashboard_service: Aggregates the services above into a single
            dashboard DTO.
        analytics_provider: The read-only analytics engine
            (``app.analytics``), used directly by ``analytics.py`` per
            this package's explicit design brief for that page.
        reporting_provider: The read-only reporting engine
            (``app.analytics``), used by ``analytics.py``.
        auth_gateway: The injected Supabase Auth boundary (see
            ``AuthGateway``'s own docstring).
        session_manager: Tracks the current Supabase session's token
            lifecycle.
        settings: The application's non-secret configuration, for
            read-only display on the admin page. This container is
            expected to hold only ``AppSettings`` fields that are safe
            to display; ``admin.py`` additionally never renders any
            field containing a credential.
        scheduler_stats: Exposes execution statistics for the
            in-process Scheduler, if this instance is the configured
            Scheduler leader (per DG Section 13); ``None`` otherwise.
    """

    request_service: RequestService
    approval_service: ApprovalService
    workflow_definition_service: WorkflowDefinitionService
    notification_service: NotificationService
    dashboard_service: DashboardService
    analytics_provider: AnalyticsProvider
    reporting_provider: ReportingProvider
    auth_gateway: AuthGateway
    session_manager: SessionManager
    settings: AppSettings
    scheduler_stats: SchedulerStatisticsProvider | None = None


def set_container(container: AppContainer) -> None:
    """Store the application's dependency-injection container for this session.

    Args:
        container: The fully constructed ``AppContainer``.
    """
    st.session_state[_KEY_CONTAINER] = container


def get_container() -> AppContainer:
    """Retrieve the application's dependency-injection container.

    Returns:
        The stored ``AppContainer``.

    Raises:
        RuntimeError: If no container has been set — indicating the
            composition root has not yet called ``set_container`` before
            a page attempted to render.
    """
    container = st.session_state.get(_KEY_CONTAINER)
    if container is None:
        raise RuntimeError(
            "No AppContainer has been configured for this session. "
            "The application's bootstrap entry point must call "
            "app.pages.session.set_container(...) before rendering any page."
        )
    return container


def has_container() -> bool:
    """Return whether a container has been configured for this session."""
    return st.session_state.get(_KEY_CONTAINER) is not None


def get_identity() -> AuthenticatedIdentity | None:
    """Return the currently authenticated identity, if any."""
    return st.session_state.get(_KEY_IDENTITY)


def set_identity(identity: AuthenticatedIdentity) -> None:
    """Store the currently authenticated identity.

    Args:
        identity: The identity to store.
    """
    st.session_state[_KEY_IDENTITY] = identity
    logger.info(
        "Session identity set for user %s (role=%s)",
        identity.user_id,
        identity.role.value,
        extra={"user_id": str(identity.user_id), "role": identity.role.value},
    )


def clear_identity() -> None:
    """Remove the currently authenticated identity, if any."""
    user_id = st.session_state.get(_KEY_IDENTITY)
    st.session_state.pop(_KEY_IDENTITY, None)
    if user_id is not None:
        logger.info("Session identity cleared for user %s", user_id.user_id)


def is_authenticated() -> bool:
    """Return whether a non-expired identity is currently stored.

    Returns:
        ``True`` if an identity is stored and its token has not expired.
    """
    identity = get_identity()
    return identity is not None and not identity.is_expired


def set_recovery_pending() -> None:
    """Mark that the current session must set a new password before
    proceeding, per a recovery or invite callback (see ``login.handle_auth_callback``).
    """
    st.session_state[_KEY_RECOVERY_PENDING] = True


def is_recovery_pending() -> bool:
    """Return whether the current session must set a new password before
    accessing the rest of the application.
    """
    return bool(st.session_state.get(_KEY_RECOVERY_PENDING, False))


def clear_recovery_pending() -> None:
    """Clear the pending-password-recovery flag, once a new password has
    been set.
    """
    st.session_state.pop(_KEY_RECOVERY_PENDING, None)


def get_active_page() -> str | None:
    """Return the currently active page key, if set."""
    return st.session_state.get(_KEY_ACTIVE_PAGE)


def set_active_page(page_key: str) -> None:
    """Set the currently active page key.

    Args:
        page_key: The page's stable identifier (e.g. ``"dashboard"``).
    """
    st.session_state[_KEY_ACTIVE_PAGE] = page_key


def get_filters(page_key: str) -> dict[str, Any]:
    """Return the currently stored filter values for a page.

    Args:
        page_key: The page's stable identifier.

    Returns:
        A mapping of filter name to value. Empty if no filters have been
        set for this page yet.
    """
    all_filters: dict[str, dict[str, Any]] = st.session_state.setdefault(_KEY_FILTERS, {})
    return dict(all_filters.get(page_key, {}))


def set_filters(page_key: str, filters: dict[str, Any]) -> None:
    """Store filter values for a page.

    Args:
        page_key: The page's stable identifier.
        filters: The filter values to store.
    """
    all_filters: dict[str, dict[str, Any]] = st.session_state.setdefault(_KEY_FILTERS, {})
    all_filters[page_key] = dict(filters)


def get_pagination(page_key: str) -> tuple[int, int]:
    """Return the currently stored ``(page_number, page_size)`` for a page.

    Args:
        page_key: The page's stable identifier.

    Returns:
        A tuple of ``(page_number, page_size)``, defaulting to
        ``(1, 20)`` if not previously set.
    """
    all_pagination: dict[str, tuple[int, int]] = st.session_state.setdefault(_KEY_PAGINATION, {})
    return all_pagination.get(page_key, (_DEFAULT_PAGE_NUMBER, _DEFAULT_PAGE_SIZE))


def set_pagination(page_key: str, *, page_number: int, page_size: int) -> None:
    """Store the current ``(page_number, page_size)`` for a page.

    Args:
        page_key: The page's stable identifier.
        page_number: The 1-indexed page number.
        page_size: The page size.
    """
    all_pagination: dict[str, tuple[int, int]] = st.session_state.setdefault(_KEY_PAGINATION, {})
    all_pagination[page_key] = (page_number, page_size)


def reset_pagination(page_key: str) -> None:
    """Reset a page's pagination back to page 1, preserving its page size.

    Args:
        page_key: The page's stable identifier.
    """
    _, page_size = get_pagination(page_key)
    set_pagination(page_key, page_number=_DEFAULT_PAGE_NUMBER, page_size=page_size)


def push_flash(level: FlashLevel, text: str) -> None:
    """Queue a one-shot flash message to be displayed on the next render.

    Args:
        level: The message's visual severity.
        text: The message body.
    """
    messages: list[FlashMessage] = st.session_state.setdefault(_KEY_FLASH_MESSAGES, [])
    messages.append(FlashMessage(level=level, text=text))


def drain_flash_messages() -> list[FlashMessage]:
    """Retrieve and clear every currently queued flash message.

    Returns:
        The messages that were queued, in the order they were pushed.
    """
    messages: list[FlashMessage] = st.session_state.get(_KEY_FLASH_MESSAGES, [])
    st.session_state[_KEY_FLASH_MESSAGES] = []
    return messages


def get_cached_selection(key: str) -> Any | None:
    """Return a previously cached UI selection (e.g. a selected row's id).

    Args:
        key: The selection's name.

    Returns:
        The cached value, or ``None`` if not set.
    """
    selections: dict[str, Any] = st.session_state.setdefault(_KEY_CACHED_SELECTIONS, {})
    return selections.get(key)


def set_cached_selection(key: str, value: Any) -> None:
    """Cache a UI selection for later retrieval.

    Args:
        key: The selection's name.
        value: The value to cache.
    """
    selections: dict[str, Any] = st.session_state.setdefault(_KEY_CACHED_SELECTIONS, {})
    selections[key] = value


def clear_cached_selection(key: str) -> None:
    """Remove a previously cached UI selection, if any.

    Args:
        key: The selection's name.
    """
    selections: dict[str, Any] = st.session_state.setdefault(_KEY_CACHED_SELECTIONS, {})
    selections.pop(key, None)


def request_confirmation(key: str) -> None:
    """Mark a two-step confirmation as pending.

    Args:
        key: A unique identifier for the action awaiting confirmation.
    """
    pending: set[str] = st.session_state.setdefault(_KEY_PENDING_CONFIRMATIONS, set())
    pending.add(key)


def is_confirmation_pending(key: str) -> bool:
    """Return whether a two-step confirmation is currently pending.

    Args:
        key: The action's unique identifier.

    Returns:
        ``True`` if ``request_confirmation`` was called for ``key`` and
        it has not yet been cleared.
    """
    pending: set[str] = st.session_state.setdefault(_KEY_PENDING_CONFIRMATIONS, set())
    return key in pending


def clear_confirmation(key: str) -> None:
    """Clear a pending two-step confirmation.

    Args:
        key: The action's unique identifier.
    """
    pending: set[str] = st.session_state.setdefault(_KEY_PENDING_CONFIRMATIONS, set())
    pending.discard(key)