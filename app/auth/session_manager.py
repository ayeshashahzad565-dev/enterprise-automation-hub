"""Session lifecycle management, storage-agnostic and dependency-injectable.

Per the ADD's session-handling description: "Session state lives in
Streamlit's session state for the duration of the browser session...
this API does not require or expose a server-side session mechanism."
This module does not contradict that — it defines the session lifecycle
as pure data plus pure transition rules, behind a small ``SessionStore``
protocol that any concrete storage backend can satisfy. A future
Presentation Layer package is expected to supply a ``SessionStore``
implementation backed by Streamlit's own ``st.session_state`` (which this
package has no dependency on and never imports); this module also ships
an ``InMemorySessionStore`` reference implementation, suitable for unit
tests (TSD Section 3.1) and for any non-Streamlit context (e.g. a future
CLI or automated test harness) that needs the same session lifecycle
without a browser session backing it.

This module holds no session state of its own at the module level; all
state lives inside whichever ``SessionStore`` instance is injected into a
``SessionManager``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from app.auth.exceptions import SessionExpiredError, SessionNotFoundError
from app.utils.datetime_utils import is_past, utc_now

__all__ = ["Session", "SessionStore", "InMemorySessionStore", "SessionManager"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Session:
    """An immutable representation of one authenticated session.

    Attributes:
        user_id: The session's authenticated user.
        access_token: The current Supabase access token.
        refresh_token: The current Supabase refresh token, used to obtain
            a new access token without re-authenticating (API-ADD
            Section 3.4-3.5).
        expires_at: The access token's expiry timestamp.
    """

    user_id: UUID
    access_token: str
    refresh_token: str
    expires_at: object  # datetime, kept loosely typed here to avoid a
    # hard import cycle risk with datetime typing utilities; see
    # `app.utils.datetime_utils` for the canonical timezone-aware type.

    @property
    def is_expired(self) -> bool:
        """Whether this session's access token has already expired."""
        return is_past(self.expires_at)  # type: ignore[arg-type]


class SessionStore(Protocol):
    """Structural interface for a session storage backend.

    A ``SessionManager`` depends on this protocol, never on a concrete
    storage implementation, so that a future Streamlit-backed store (or
    any other) can be substituted by dependency injection without any
    change to ``SessionManager`` itself.
    """

    def get(self) -> Session | None:
        """Return the currently stored session, or ``None`` if none exists."""
        ...

    def set(self, session: Session) -> None:
        """Persist a session, replacing any previously stored one."""
        ...

    def clear(self) -> None:
        """Remove any currently stored session."""
        ...


class InMemorySessionStore:
    """A simple, process-local ``SessionStore`` implementation.

    Suitable for unit tests and any non-Streamlit execution context.
    This implementation is deliberately not thread-safe beyond what a
    single dict assignment already provides, matching the single-session,
    single-user-per-instance usage pattern the ADD describes for
    Streamlit's own per-browser-session state.
    """

    def __init__(self) -> None:
        self._session: Session | None = None

    def get(self) -> Session | None:
        """Return the currently stored session, or ``None``."""
        return self._session

    def set(self, session: Session) -> None:
        """Store ``session``, replacing any previous value."""
        self._session = session

    def clear(self) -> None:
        """Remove the currently stored session, if any."""
        self._session = None


class SessionManager:
    """Coordinates the lifecycle of a single authenticated session.

    Depends on an injected ``SessionStore`` for all actual state, per
    this module's dependency-injection design — no session data is held
    directly by this class.
    """

    def __init__(self, store: SessionStore) -> None:
        """Initialize the manager with an injected session store.

        Args:
            store: Any object satisfying the ``SessionStore`` protocol.
        """
        self._store = store

    def start_session(
        self,
        *,
        user_id: UUID,
        access_token: str,
        refresh_token: str,
        expires_at: object,
    ) -> Session:
        """Begin a new session, replacing any existing one.

        Args:
            user_id: The authenticated user's id.
            access_token: The Supabase access token.
            refresh_token: The Supabase refresh token.
            expires_at: The access token's expiry timestamp (a
                timezone-aware ``datetime``, per
                ``app.utils.datetime_utils``).

        Returns:
            The newly created ``Session``.
        """
        session = Session(
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )
        self._store.set(session)
        logger.info(
            "Session started for user %s", user_id, extra={"user_id": str(user_id)}
        )
        return session

    def get_current_session(self, *, allow_expired: bool = False) -> Session:
        """Retrieve the currently active session.

        Args:
            allow_expired: If ``False`` (the default), an expired session
                raises ``SessionExpiredError`` rather than being returned
                silently.

        Returns:
            The current ``Session``.

        Raises:
            SessionNotFoundError: If no session is currently stored.
            SessionExpiredError: If a session exists but has expired and
                ``allow_expired`` is ``False``.
        """
        session = self._store.get()
        if session is None:
            raise SessionNotFoundError()
        if session.is_expired and not allow_expired:
            raise SessionExpiredError()
        return session

    def is_session_valid(self) -> bool:
        """Return whether a non-expired session currently exists.

        Returns:
            ``True`` if a session is stored and not expired; ``False``
            otherwise (including if no session exists at all).
        """
        session = self._store.get()
        return session is not None and not session.is_expired

    def refresh_session(self, *, new_access_token: str, new_expires_at: object) -> Session:
        """Replace the current session's access token and expiry after a
        successful token refresh.

        Per the ADD, refresh itself is performed transparently by
        Supabase's own client library; this method only updates the
        locally held session record to reflect the result of that
        refresh.

        Args:
            new_access_token: The newly issued access token.
            new_expires_at: The new token's expiry timestamp.

        Returns:
            The updated ``Session``.

        Raises:
            SessionNotFoundError: If no session currently exists to
                refresh.
        """
        current = self._store.get()
        if current is None:
            raise SessionNotFoundError()
        updated = replace(
            current, access_token=new_access_token, expires_at=new_expires_at
        )
        self._store.set(updated)
        logger.info(
            "Session refreshed for user %s",
            current.user_id,
            extra={"user_id": str(current.user_id)},
        )
        return updated

    def end_session(self) -> None:
        """Terminate the current session, if any.

        Corresponds to the ADD's description of logout instructing
        Supabase to invalidate the refresh token; this method only
        clears the locally held session record — actually invalidating
        the refresh token with Supabase is a service-layer concern
        outside this package's scope.
        """
        self._store.clear()
        logger.info("Session ended.")