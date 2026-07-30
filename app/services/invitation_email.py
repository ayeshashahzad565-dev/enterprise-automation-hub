"""The production ``InvitationEmailSender`` implementation.

Per Milestone 4 of the Enterprise User Onboarding architecture, this
module provides the concrete email delivery this codebase's two
notification stacks (``app.services.notification_service``,
``app.notifications``) were deliberately bypassed for — see
``InvitationService``'s module docstring, and the architecture's own
Notification Integration section, for why: both existing stacks assume a
recipient with an existing ``profiles`` row, which an invitee does not
have until *after* accepting.

This module is built directly around
``app.notifications.email_sender.EmailProvider`` — the lowest-level SMTP
abstraction the ``app.notifications`` package already exposes — so no
second SMTP implementation is introduced; ``SmtpInvitationEmailSender``
only adds invitation-specific link-building and copy on top of it.

Email content follows ``app.notifications.templates``'s established
in-Python ``str.format()`` convention. It does not reuse that module's
``TEMPLATE_REGISTRY``/``NotificationEvent`` directly: those are keyed to
a fixed, request-and-stage-shaped vocabulary
(assignment/approval/rejection/completion/reminder/escalation) that an
invitation event does not belong to, and forcing it in would mean
stretching an unrelated enum rather than reusing a genuine fit. The
*convention* (plain ``str.format`` placeholders, a generated minimal HTML
variant) is reused; the registry is not.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime

from app.config.constants import APP_NAME
from app.config.settings import InvitationSettings
from app.jobs.job_service import JobService
from app.jobs.task_types import TASK_SEND_INVITATION_EMAIL
from app.notifications.exceptions import EmailDeliveryError
from app.notifications.interfaces import EmailProvider

__all__ = ["SmtpInvitationEmailSender", "QueuedInvitationEmailSender"]

logger = logging.getLogger(__name__)

_SUBJECT_NEW_INVITATION = f"You're invited to {APP_NAME}"
_SUBJECT_RESENT_INVITATION = f"Your {APP_NAME} invitation link has been renewed"

_INTRO_NEW_INVITATION = (
    "You have been invited to join {app_name}. To activate your account, "
    "set a password using the link below."
)
_INTRO_RESENT_INVITATION = (
    "Your invitation to join {app_name} has been renewed with a new link. "
    "Any previous invitation link for this account no longer works. To "
    "activate your account, set a password using the link below."
)

_TEXT_BODY_TEMPLATE = (
    "Hello {full_name},\n\n"
    "{intro}\n\n"
    "{accept_url}\n\n"
    "This link expires on {expires_at}. If you were not expecting this "
    "invitation, no action is needed — you can safely ignore this email."
)

_HTML_BODY_TEMPLATE = (
    "<html><body>"
    "<p>Hello {full_name},</p>"
    "<p>{intro}</p>"
    '<p><a href="{accept_url}">Set your password and activate your account</a></p>'
    "<p>This link expires on {expires_at}. If you were not expecting this "
    "invitation, no action is needed — you can safely ignore this email.</p>"
    "</body></html>"
)


def _build_accept_url(*, app_base_url: str, accept_path: str, token: str) -> str:
    """Build an invitation-acceptance link.

    Args:
        app_base_url: The application's public frontend origin, with no
            trailing slash (``InvitationSettings.app_base_url`` is
            normalized this way at load time).
        accept_path: The frontend route path the link should point to.
        token: The raw (unhashed) invitation token. ``token_urlsafe``
            (this codebase's only invitation-token generator, see
            ``app.services.invitation_service.generate_invitation_token``)
            produces output already safe to embed directly in a query
            string, so no additional URL-encoding is performed here.

    Returns:
        The fully qualified acceptance URL.
    """
    path = accept_path if accept_path.startswith("/") else f"/{accept_path}"
    return f"{app_base_url}{path}?token={token}"


class SmtpInvitationEmailSender:
    """Sends invitation emails over SMTP, via an injected ``EmailProvider``.

    Satisfies ``app.services.invitation_service.InvitationEmailSender``
    structurally (a ``typing.Protocol``) — ``InvitationService`` depends
    only on that Protocol, never on this class.
    """

    def __init__(self, *, email_provider: EmailProvider, settings: InvitationSettings) -> None:
        """Initialize the sender with its injected collaborators.

        Args:
            email_provider: The low-level SMTP capability to send
                through — any object satisfying
                ``app.notifications.interfaces.EmailProvider`` (in
                production, ``app.notifications.email_sender.SmtpEmailProvider``;
                a fake in tests).
            settings: The invitation flow's configuration (accept-link
                base URL and path).
        """
        self._email_provider = email_provider
        self._settings = settings
        self._logger = logging.getLogger(f"{__name__}.SmtpInvitationEmailSender")

    def send_invitation(
        self,
        *,
        to_email: str,
        full_name: str,
        token: str,
        expires_at: datetime,
        is_resend: bool = False,
    ) -> bool:
        """Send a single invitation email.

        The raw ``token`` is embedded in the rendered acceptance link but
        is never included in any log message this method emits — only
        ``to_email``/``is_resend``/success-or-failure are logged, matching
        this milestone's "never log the raw token" requirement.

        Args:
            to_email: The invited person's email address.
            full_name: The invited person's display name.
            token: The raw (unhashed) invitation token.
            expires_at: The timestamp after which the link will no longer
                be accepted.
            is_resend: Whether this is a resend of an existing invitation
                (varies the subject/copy) rather than a brand-new one.

        Returns:
            ``True`` if the email was sent successfully, ``False`` if
            delivery failed. Never raises for an ordinary delivery
            failure — ``InvitationService`` treats this return value, not
            an exception, as the failure signal.
        """
        accept_url = _build_accept_url(
            app_base_url=self._settings.app_base_url,
            accept_path=self._settings.accept_path,
            token=token,
        )
        subject = _SUBJECT_RESENT_INVITATION if is_resend else _SUBJECT_NEW_INVITATION
        intro_template = _INTRO_RESENT_INVITATION if is_resend else _INTRO_NEW_INVITATION
        intro = intro_template.format(app_name=APP_NAME)
        expires_at_display = expires_at.isoformat()

        text_body = _TEXT_BODY_TEMPLATE.format(
            full_name=full_name, intro=intro, accept_url=accept_url, expires_at=expires_at_display
        )
        # full_name is admin-supplied free text; escaped before entering the
        # HTML variant so it can never inject markup into the rendered
        # email (the plain-text variant needs no such escaping — text_body
        # above uses the raw value).
        html_body = _HTML_BODY_TEMPLATE.format(
            full_name=html.escape(full_name),
            intro=intro,
            accept_url=accept_url,
            expires_at=expires_at_display,
        )

        try:
            self._email_provider.send_email(
                to_address=to_email, subject=subject, text_body=text_body, html_body=html_body
            )
        except EmailDeliveryError as exc:
            self._logger.warning(
                "Invitation email delivery failed for %s (is_resend=%s): %s",
                to_email,
                is_resend,
                exc,
                extra={"to_email": to_email, "is_resend": is_resend},
            )
            return False

        self._logger.info(
            "Invitation email sent to %s (is_resend=%s)",
            to_email,
            is_resend,
            extra={"to_email": to_email, "is_resend": is_resend},
        )
        return True


class QueuedInvitationEmailSender:
    """Enqueues an invitation email for asynchronous delivery, rather than
    sending it synchronously on the caller's (HTTP request) thread.

    Satisfies ``app.services.invitation_service.InvitationEmailSender``
    structurally, exactly like ``SmtpInvitationEmailSender`` — wired in by
    ``app.bootstrap`` instead of it when ``AppSettings.email_dispatch_mode
    == "queue"`` and Redis is configured, closing a gap that predates this
    class: invitation dispatch previously always ran synchronously
    regardless of ``EMAIL_DISPATCH_MODE``, unlike
    ``NotificationService``'s email leg.

    The actual send happens in a separate worker process
    (``app.jobs.handlers.handle_send_invitation_email``, which
    reconstructs a fresh ``SmtpInvitationEmailSender`` there) — this class
    only records the job's intent and returns immediately.

    The raw (unhashed) invitation ``token`` is embedded in the enqueued
    payload — briefly present in both the ``jobs`` table and Redis for
    the job's lifetime — mirroring the same "never log the raw token"
    discipline ``SmtpInvitationEmailSender`` already follows (this class's
    own ``send_invitation`` never logs ``token``, only the outcome).
    """

    def __init__(self, *, job_service: JobService) -> None:
        """Initialize the sender.

        Args:
            job_service: The shared job service to enqueue through.
        """
        self._job_service = job_service
        self._logger = logging.getLogger(f"{__name__}.QueuedInvitationEmailSender")

    def send_invitation(
        self,
        *,
        to_email: str,
        full_name: str,
        token: str,
        expires_at: datetime,
        is_resend: bool = False,
    ) -> bool:
        """Enqueue a single invitation email for delivery, returning immediately.

        Args:
            to_email: The invited person's email address.
            full_name: The invited person's display name.
            token: The raw (unhashed) invitation token.
            expires_at: The timestamp after which the link will no longer
                be accepted.
            is_resend: Whether this is a resend of an existing invitation.

        Returns:
            ``True`` if the job was successfully enqueued; ``False`` if
            enqueuing itself raised unexpectedly.
        """
        try:
            job = self._job_service.enqueue(
                task_type=TASK_SEND_INVITATION_EMAIL,
                queue_name="default",
                payload={
                    "to_email": to_email,
                    "full_name": full_name,
                    "token": token,
                    "expires_at": expires_at.isoformat(),
                    "is_resend": is_resend,
                },
            )
        except Exception:
            self._logger.exception("Failed to enqueue invitation email for %s", to_email)
            return False
        self._logger.info(
            "Enqueued invitation email job %s for %s (is_resend=%s)",
            job.id,
            to_email,
            is_resend,
            extra={"to_email": to_email, "is_resend": is_resend},
        )
        return True
