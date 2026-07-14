"""Composition root for the Enterprise Automation Hub.

This module is the single place every package in this codebase is wired
together: configuration is loaded, the Supabase client(s) are
constructed, every repository and Application Service is instantiated,
the in-process Scheduler is started (only on the configured leader
instance), and the resulting dependency-injection container is handed
to the Streamlit Presentation Layer (``app.pages``).

This module contains no business logic of its own. Every non-trivial
decision made here is an integration decision, not a domain one, and is
documented inline where it departs from a purely mechanical wiring of
already-finalized packages — see the accompanying conflict notes
delivered alongside this file for the full rationale behind each one.
"""

from __future__ import annotations

import atexit
import dataclasses
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import streamlit as st

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.reporting import ReportingEngine
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import AuthenticationError
from app.auth.session_manager import InMemorySessionStore, SessionManager
from app.config.constants import APP_NAME
from app.config.logging_config import configure_logging, get_logger
from app.config.settings import AppSettings, load_settings
from app.database.client import SupabaseClientFactory, SupabaseConnectionSettings
from app.database.repositories.analytics_repository import AnalyticsRepository
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.notification_repository import NotificationRepository
from app.database.repositories.request_repository import RequestRepository
from app.database.repositories.user_repository import ProfileRepository
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
    WorkflowStageRepository,
)
from app.notifications.email_sender import EmailNotificationChannel, SmtpEmailProvider
from app.notifications.exceptions import EmailDeliveryError, NotificationConfigurationError
from app.notifications.in_app_notifier import InAppNotifier
from app.notifications.notification_factory import NotificationFactory
from app.notifications.notification_manager import NotificationManager
from app.notifications.templates import DefaultTemplateRenderer
from app.pages import navigation, session
from app.scheduler.escalation_job import EscalationJob
from app.scheduler.health_check_job import HealthCheckJob
from app.scheduler.registry import JobRegistry
from app.scheduler.reminder_job import ReminderJob
from app.scheduler.scheduler import APSchedulerBackend, SchedulerCoordinator
from app.services.analytics_service import AnalyticsService as ServicesAnalyticsService
from app.services.approval_service import ApprovalService
from app.services.dashboard_service import DashboardService
from app.services.notification_service import NotificationService
from app.services.request_service import RequestService
from app.services.workflow_definition_service import WorkflowDefinitionService
from app.workflow.engine import WorkflowEngine

logger = logging.getLogger(__name__)

_PAGE_ICON = "🏢"


class SupabaseAuthGateway:
    """The composition root's implementation of ``app.pages.session.AuthGateway``.

    Per this file's accompanying conflict notes (Conflict 1), no
    finalized package performs a real Supabase Auth network call —
    ``app.auth`` deliberately builds ``AuthenticatedIdentity`` from
    already-verified claims and never calls Supabase itself. This class
    is that missing, explicitly-injected boundary.

    A fresh, unauthenticated anon-key client is constructed for every
    individual sign-in/sign-out/reset call (rather than reusing one
    shared client) specifically to avoid any possibility of one Streamlit
    session's authentication call mutating shared client-side auth state
    that another concurrent session might also be relying on. This
    trades a small amount of per-call construction cost for full
    isolation between concurrent users' authentication flows.
    """

    def __init__(self, *, supabase_settings: SupabaseConnectionSettings, profile_repo: ProfileRepository) -> None:
        """Initialize the gateway.

        Args:
            supabase_settings: The Supabase project's connection
                settings, used to construct a fresh anon-key client per
                call.
            profile_repo: Used to resolve the authenticated user's RBAC
                role from ``profiles`` after Supabase verifies their
                credentials — per the ADD, a role is always resolved
                from the database, never trusted from a raw JWT claim.
        """
        self._supabase_settings = supabase_settings
        self._profile_repo = profile_repo
        self._logger = get_logger(f"{__name__}.SupabaseAuthGateway")

    def sign_in(self, *, email: str, password: str) -> session.AuthResult:
        """Verify credentials against Supabase Auth and resolve the caller's role.

        Args:
            email: The user's email address.
            password: The user's password.

        Returns:
            The resulting ``session.AuthResult``.

        Raises:
            AuthenticationError: If Supabase rejects the credentials, or
                no ``profiles`` row exists for the authenticated user.
        """
        client = SupabaseClientFactory.create_anon_client(self._supabase_settings)
        try:
            response = client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as exc:  # noqa: BLE001 - translated below; Supabase's own
            # exception type (gotrue's AuthApiError) is not part of any
            # finalized package's exception hierarchy, so it is caught
            # broadly here and translated into this project's own
            # AuthenticationError, exactly as every other integration
            # boundary in this codebase translates a third-party failure.
            self._logger.warning("Supabase sign-in failed for %s: %s", email, exc)
            raise AuthenticationError("Invalid email or password.") from exc

        result = self._build_auth_result(response)
        self._logger.info(
            "User %s signed in successfully.",
            result.identity.user_id,
            extra={"user_id": str(result.identity.user_id)},
        )
        return result

    def exchange_code_for_session(self, *, code: str) -> session.AuthResult:
        """Exchange a Supabase PKCE auth callback code for a real session.

        Handles the signup-confirmation, invite, and recovery email links
        Supabase redirects back to this application with a ``?code=...``
        query parameter (API-ADD/ADD auth callback handling).

        Args:
            code: The ``code`` value from the callback URL.

        Returns:
            The resulting ``session.AuthResult``.

        Raises:
            AuthenticationError: If the code is invalid, expired, or has
                already been used.
        """
        client = SupabaseClientFactory.create_anon_client(self._supabase_settings)
        try:
            response = client.auth.exchange_code_for_session({"auth_code": code})
        except Exception as exc:  # noqa: BLE001 - translated below
            self._logger.warning("Supabase auth-code exchange failed: %s", exc)
            raise AuthenticationError(
                "This confirmation or recovery link is invalid or has expired."
            ) from exc

        result = self._build_auth_result(response)
        self._logger.info(
            "Auth callback code exchanged successfully for user %s.",
            result.identity.user_id,
            extra={"user_id": str(result.identity.user_id)},
        )
        return result

    def restore_session(self, *, access_token: str, refresh_token: str) -> session.AuthResult:
        """Restore a session directly from a pair of callback tokens.

        Args:
            access_token: The access token from the callback URL.
            refresh_token: The refresh token from the callback URL.

        Returns:
            The resulting ``session.AuthResult``.

        Raises:
            AuthenticationError: If the tokens are invalid or expired.
        """
        client = SupabaseClientFactory.create_anon_client(self._supabase_settings)
        try:
            response = client.auth.set_session(access_token, refresh_token)
        except Exception as exc:  # noqa: BLE001 - translated below
            self._logger.warning("Supabase session restore failed: %s", exc)
            raise AuthenticationError(
                "Unable to restore your session from the supplied tokens."
            ) from exc

        return self._build_auth_result(response)

    def update_password(
        self, *, access_token: str, refresh_token: str, new_password: str
    ) -> None:
        """Set a new password for the user identified by a session's tokens.

        Hydrates a fresh anon client with the given session (via
        ``set_session``) before calling Supabase Auth's
        ``update_user({"password": new_password})``, since password
        update requires an authenticated session context. A fresh client
        is still used per call, consistent with this class's isolation
        rationale (see class docstring): no client here is ever shared
        or reused across calls.

        Args:
            access_token: The access token of the session to act as.
            refresh_token: The refresh token of the session to act as.
            new_password: The new password to set.

        Raises:
            AuthenticationError: If Supabase rejects the update.
        """
        client = SupabaseClientFactory.create_anon_client(self._supabase_settings)
        try:
            client.auth.set_session(access_token, refresh_token)
            client.auth.update_user({"password": new_password})
        except Exception as exc:  # noqa: BLE001 - translated below
            self._logger.warning("Password update failed: %s", exc)
            raise AuthenticationError("Unable to update your password.") from exc

    def _build_auth_result(self, response: Any) -> session.AuthResult:
        """Build a ``session.AuthResult`` from a Supabase Auth response.

        Shared by every method above that obtains a session from Supabase
        (sign-in, auth-code exchange, and token-based restore), so the
        "resolve the caller's RBAC role from ``profiles``, never trust a
        raw token claim" rule (per the ADD) is applied in exactly one
        place.

        Args:
            response: The ``AuthResponse`` (or equivalent) Supabase's
                GoTrue client returned, carrying ``.session`` and
                ``.user``.

        Returns:
            The resulting ``session.AuthResult``.

        Raises:
            AuthenticationError: If ``response`` carries no valid
                session/user, or no ``profiles`` row exists for the
                authenticated user.
        """
        if response.session is None or response.user is None:
            raise AuthenticationError("Supabase did not return a valid session.")

        try:
            profile = self._profile_repo.get_by_id(UUID(response.user.id))
        except Exception as exc:  # noqa: BLE001 - translated below
            self._logger.error(
                "No profile exists for authenticated user %s: %s", response.user.id, exc
            )
            raise AuthenticationError(
                "Your account is not fully provisioned. Contact an administrator."
            ) from exc

        claims = {
            "sub": str(profile.id),
            "email": response.user.email,
            "role": profile.role.value,
            "exp": response.session.expires_at,
        }
        identity = AuthenticatedIdentity.from_claims(claims)
        expires_at = datetime.fromtimestamp(response.session.expires_at, tz=UTC)

        return session.AuthResult(
            identity=identity,
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
            expires_at=expires_at,
        )

    def sign_out(self, identity: AuthenticatedIdentity) -> None:
        """Best-effort sign-out notice.

        Per this file's accompanying conflict notes (Conflict 6), the
        ``AuthGateway`` protocol's fixed signature provides only an
        ``AuthenticatedIdentity``, which carries no refresh token —
        there is therefore no way for this method to instruct Supabase
        to revoke a specific server-side session. The caller
        (``app.pages.login.logout``) already clears this application's
        own local identity and ends its own ``SessionManager`` session
        regardless of what happens here, which is what actually gates
        every subsequent Application Service call in this application.

        Args:
            identity: The identity requesting sign-out, logged for
                traceability only.
        """
        self._logger.info(
            "Local sign-out completed for user %s. No server-side Supabase session "
            "revocation was performed, since this method's fixed signature carries no "
            "refresh token to revoke.",
            identity.user_id,
            extra={"user_id": str(identity.user_id)},
        )

    def send_password_reset_email(self, email: str) -> None:
        """Trigger Supabase Auth's password reset email flow.

        Args:
            email: The address to send a reset link to.

        Raises:
            AuthenticationError: If Supabase rejects the request.
        """
        client = SupabaseClientFactory.create_anon_client(self._supabase_settings)
        try:
            client.auth.reset_password_email(email)
        except Exception as exc:  # noqa: BLE001 - translated below
            self._logger.warning("Password reset request failed for %s: %s", email, exc)
            raise AuthenticationError("Unable to send a password reset email.") from exc


class _EmailSenderAdapter:
    """Bridges ``app.notifications.email_sender.SmtpEmailProvider`` to the
    narrower ``app.services.notification_service.EmailSender`` protocol.

    Per this file's accompanying conflict notes (Conflict 2), two
    independent notification stacks exist. This adapter lets
    ``app.services.notification_service.NotificationService`` (the stack
    actually wired into ``RequestService``/``ApprovalService``) reuse the
    same SMTP mechanism ``app.notifications`` already implements, rather
    than requiring a second, separate SMTP implementation.
    """

    def __init__(self, provider: SmtpEmailProvider) -> None:
        """Initialize the adapter.

        Args:
            provider: The underlying SMTP provider to delegate to.
        """
        self._provider = provider

    def send(self, *, to_address: str, subject: str, body: str) -> bool:
        """Send an email, satisfying the services-layer ``EmailSender`` protocol.

        Args:
            to_address: The recipient's email address.
            subject: The email subject line.
            body: The plain-text email body.

        Returns:
            ``True`` if delivery succeeded, ``False`` otherwise.
        """
        try:
            self._provider.send_email(to_address=to_address, subject=subject, text_body=body)
        except EmailDeliveryError:
            return False
        return True


@dataclasses.dataclass(frozen=True, slots=True)
class _GlobalResources:
    """The process-wide singleton bundle built once per Python process.

    Attributes:
        base_container: A fully wired ``session.AppContainer`` whose
            ``session_manager`` field is a placeholder — every
            individual Streamlit session replaces it with its own fresh
            ``SessionManager`` via ``dataclasses.replace`` (Conflict 5),
            since every other field is safe to share across concurrent
            sessions.
        notification_manager: The constructed, but currently unconsumed,
            ``app.notifications.NotificationManager`` (Conflict 2),
            retained here for future integration.
    """

    base_container: session.AppContainer
    notification_manager: NotificationManager


def _build_email_sender(settings: AppSettings) -> tuple[_EmailSenderAdapter | None, SmtpEmailProvider | None]:
    """Construct the shared SMTP provider and its services-layer adapter, if enabled.

    Args:
        settings: The loaded application settings.

    Returns:
        A tuple of ``(adapter, provider)``, both ``None`` if SMTP is
        disabled for this environment (per DG Section 8.1, permitted in
        Development/Testing).
    """
    if not settings.smtp.is_enabled:
        logger.info("SMTP is disabled for this environment; email dispatch will be skipped.")
        return None, None
    try:
        provider = SmtpEmailProvider(settings=settings.smtp)
    except NotificationConfigurationError as exc:
        logger.error("Failed to construct SMTP provider despite is_enabled=True: %s", exc)
        return None, None
    return _EmailSenderAdapter(provider), provider


@st.cache_resource(show_spinner="Starting Enterprise Automation Hub...")
def _build_global_resources() -> _GlobalResources:
    """Construct every process-wide singleton this application needs.

    Cached via ``st.cache_resource`` so this body runs exactly once per
    Python process, regardless of how many Streamlit browser sessions
    connect to it — consistent with the ADD's stateless, horizontally
    scalable process design (ADD Section 10) and with Conflict 4's
    resolution that every Application Service here is safe to share
    across sessions, since identity is passed per-call, not held as
    connection state.

    Returns:
        The constructed ``_GlobalResources`` bundle.
    """
    settings = load_settings()
    configure_logging(settings.logging.level)
    logger.info("Loaded configuration for environment: %s", settings.environment.value)

    # --- Database client and repositories -----------------------------
    # Per Conflict 4, every repository behind the Application Service
    # Layer is backed by the service-role client: every app.services
    # method already performs a mandatory authorization check against
    # the caller's AuthenticatedIdentity before any repository call, and
    # this Streamlit process has no client-side Supabase caller of its
    # own — every database call already originates from trusted,
    # server-side code that has already passed through that check.
    service_role_client = SupabaseClientFactory.create_service_role_client(settings.supabase)

    profile_repo = ProfileRepository(service_role_client)
    request_repo = RequestRepository(service_role_client)
    workflow_definition_repo = WorkflowDefinitionRepository(service_role_client)
    workflow_stage_repo = WorkflowStageRepository(service_role_client)
    approval_repo = ApprovalRepository(service_role_client)
    notification_repo = NotificationRepository(service_role_client)
    audit_repo = AuditRepository(service_role_client)
    analytics_repo = AnalyticsRepository(service_role_client)

    # --- Workflow Engine ------------------------------------------------
    workflow_engine = WorkflowEngine()

    # --- Notification Layer (app.services stack; the one actually
    # wired into RequestService/ApprovalService/the Scheduler) ----------
    email_adapter, smtp_provider = _build_email_sender(settings)
    notification_service = NotificationService(
        notification_repo=notification_repo, email_sender=email_adapter
    )

    # --- Application Services -------------------------------------------
    request_service = RequestService(
        request_repo=request_repo,
        workflow_definition_repo=workflow_definition_repo,
        workflow_stage_repo=workflow_stage_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        notification_service=notification_service,
        workflow_engine=workflow_engine,
    )
    approval_service = ApprovalService(
        approval_repo=approval_repo,
        workflow_stage_repo=workflow_stage_repo,
        request_repo=request_repo,
        workflow_definition_repo=workflow_definition_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        notification_service=notification_service,
        workflow_engine=workflow_engine,
    )
    workflow_definition_service = WorkflowDefinitionService(
        workflow_definition_repo=workflow_definition_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        workflow_engine=workflow_engine,
    )
    services_analytics_service = ServicesAnalyticsService(
        analytics_repo=analytics_repo, approval_repo=approval_repo
    )
    dashboard_service = DashboardService(
        request_service=request_service,
        approval_service=approval_service,
        notification_service=notification_service,
        analytics_service=services_analytics_service,
    )

    # --- Analytics Layer (app.analytics stack; used directly by the
    # analytics.py page per its own explicit design brief — Conflict 3) --
    analytics_engine = AnalyticsEngine(
        analytics_repo=analytics_repo,
        request_repo=request_repo,
        approval_repo=approval_repo,
        workflow_stage_repo=workflow_stage_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        notification_repo=notification_repo,
    )
    reporting_engine = ReportingEngine(analytics_provider=analytics_engine)

    # --- Authentication --------------------------------------------------
    auth_gateway = SupabaseAuthGateway(
        supabase_settings=settings.supabase, profile_repo=profile_repo
    )

    # --- Scheduler (leader instances only) --------------------------------
    scheduler_stats = None
    if settings.scheduler.is_leader:
        coordinator = SchedulerCoordinator(backend=APSchedulerBackend(), registry=JobRegistry())
        escalation_job = EscalationJob(
            approval_service=approval_service,
            approval_repo=approval_repo,
            request_repo=request_repo,
            workflow_definition_repo=workflow_definition_repo,
            workflow_engine=workflow_engine,
            interval_seconds=settings.scheduler.escalation_interval_minutes * 60,
        )
        reminder_job = ReminderJob(
            notification_service=notification_service,
            approval_repo=approval_repo,
            request_repo=request_repo,
            workflow_definition_repo=workflow_definition_repo,
            notification_repo=notification_repo,
            workflow_engine=workflow_engine,
            interval_seconds=settings.scheduler.reminder_interval_hours * 3600,
        )
        health_check_job = HealthCheckJob(statistics_provider=coordinator)

        coordinator.register_job(escalation_job)
        coordinator.register_job(reminder_job)
        coordinator.register_job(health_check_job)
        coordinator.start()
        atexit.register(lambda: _shutdown_scheduler(coordinator))

        scheduler_stats = coordinator
        logger.info("Scheduler started on this instance (SCHEDULER_LEADER=true).")
    else:
        logger.info("This instance is not the Scheduler leader; no jobs were registered.")

    # --- Notification Manager (app.notifications stack; Conflict 2) ------
    # Constructed per the explicit integration instruction. No package in
    # this codebase currently consumes it — app.services and app.scheduler
    # both depend on app.services.notification_service.NotificationService
    # instead. It is retained on the returned bundle, not on
    # session.AppContainer (whose shape is fixed by the finalized
    # app.pages package), pending a future decision on how the two
    # notification stacks should be reconciled.
    notification_manager = NotificationManager(
        factory=NotificationFactory(template_renderer=DefaultTemplateRenderer()),
        in_app_notifier=InAppNotifier(notification_repo=notification_repo),
        channels=(
            [EmailNotificationChannel(email_provider=smtp_provider)] if smtp_provider is not None else []
        ),
    )
    logger.info(
        "NotificationManager constructed (app.notifications stack). No consumer is "
        "currently wired to it; see this module's Conflict 2 notes."
    )

    base_container = session.AppContainer(
        request_service=request_service,
        approval_service=approval_service,
        workflow_definition_service=workflow_definition_service,
        notification_service=notification_service,
        dashboard_service=dashboard_service,
        analytics_provider=analytics_engine,
        reporting_provider=reporting_engine,
        auth_gateway=auth_gateway,
        # Placeholder only: every individual session replaces this field
        # via dataclasses.replace before use (Conflict 5).
        session_manager=SessionManager(InMemorySessionStore()),
        settings=settings,
        scheduler_stats=scheduler_stats,
    )

    return _GlobalResources(base_container=base_container, notification_manager=notification_manager)


def _shutdown_scheduler(coordinator: SchedulerCoordinator) -> None:
    """Gracefully stop the Scheduler on process exit.

    Registered via ``atexit`` at startup, since a vanilla Streamlit
    script exposes no first-class application-shutdown hook of its own;
    ``atexit`` is the portable, standard-library mechanism for running
    cleanup code when the Python process running Streamlit terminates.

    Args:
        coordinator: The running ``SchedulerCoordinator`` to stop.
    """
    try:
        coordinator.stop(wait=True)
        logger.info("Scheduler stopped cleanly on process shutdown.")
    except Exception as exc:  # noqa: BLE001 - shutdown must not raise past atexit
        logger.error("Scheduler failed to shut down cleanly: %s", exc, exc_info=exc)


def _ensure_session_container(resources: _GlobalResources) -> None:
    """Ensure the current Streamlit session has its own ``AppContainer``.

    Per Conflict 5, every field of ``resources.base_container`` except
    ``session_manager`` is safe to share across every concurrent
    session; only ``session_manager`` is given a fresh, session-local
    instance here.

    Args:
        resources: The process-wide global resource bundle.
    """
    if session.has_container():
        return
    session_container = dataclasses.replace(
        resources.base_container, session_manager=SessionManager(InMemorySessionStore())
    )
    session.set_container(session_container)
    logger.debug("Initialized a new per-session AppContainer.")


def main() -> None:
    """The application's entry point.

    Configures the Streamlit page, builds (or reuses) the process-wide
    resource bundle, ensures this browser session has its own container,
    and hands off to ``app.pages.navigation.render_app`` for the actual
    authentication gate, sidebar, and page dispatch.
    """
    st.set_page_config(page_title=APP_NAME, page_icon=_PAGE_ICON, layout="wide")

    resources = _build_global_resources()
    _ensure_session_container(resources)

    navigation.render_app()


if __name__ == "__main__":
    main()