"""Task handlers dispatched by ``app.jobs.worker`` (and, when Redis is
not configured, invoked directly and synchronously by
``app.jobs.job_service.SynchronousJobDispatcher`` — see that class's
docstring for why the same handler functions serve both paths).

Every handler takes a plain JSON-decoded ``payload`` dict (the exact
shape its producer enqueued) plus whatever already-constructed
collaborators it needs, and returns ``True``/``False`` for success/
ordinary, expected failure. A handler may also raise for an unexpected
failure (e.g. a genuine database error) — the caller (``app.jobs.worker``
or ``SynchronousJobDispatcher``) treats a raised exception exactly like a
``False`` return: an ordinary failure to be retried, not a crash.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from app.config.settings import InvitationSettings, SmtpSettings
from app.jobs.task_types import (
    TASK_ESCALATE_STAGE,
    TASK_SEND_EMAIL,
    TASK_SEND_INVITATION_EMAIL,
    TASK_SEND_REMINDER,
)
from app.notifications.email_sender import SmtpEmailProvider
from app.notifications.exceptions import EmailDeliveryError
from app.services.approval_service import ApprovalService
from app.services.exceptions import ConcurrencyError
from app.services.invitation_email import SmtpInvitationEmailSender
from app.services.notification_service import NotificationService

__all__ = [
    "TASK_SEND_EMAIL",
    "TASK_SEND_INVITATION_EMAIL",
    "TASK_ESCALATE_STAGE",
    "TASK_SEND_REMINDER",
    "handle_send_email",
    "handle_send_invitation_email",
    "handle_escalate_stage",
    "handle_send_reminder",
    "TASK_HANDLERS",
]

logger = logging.getLogger(__name__)


def handle_send_email(payload: dict[str, Any], *, smtp_settings: SmtpSettings) -> bool:
    """Deliver a single queued email via SMTP.

    Args:
        payload: ``{"to_address": str, "subject": str, "body": str}``.
        smtp_settings: This process's own loaded SMTP configuration.

    Returns:
        ``True`` if the SMTP send succeeded, ``False`` otherwise.
    """
    if not smtp_settings.is_enabled:
        logger.warning("Dropping queued email: SMTP is not configured for this environment.")
        return False

    provider = SmtpEmailProvider(settings=smtp_settings)
    try:
        provider.send_email(
            to_address=payload["to_address"],
            subject=payload["subject"],
            text_body=payload["body"],
        )
    except EmailDeliveryError as exc:
        logger.warning("Queued email delivery failed: %s", exc)
        return False
    return True


def handle_send_invitation_email(
    payload: dict[str, Any],
    *,
    smtp_settings: SmtpSettings,
    invitation_settings: InvitationSettings,
) -> bool:
    """Deliver a single queued invitation email via SMTP.

    Per the Enterprise User Onboarding token-handling rule this codebase
    already follows (``app.services.invitation_email``'s "never log the
    raw token" requirement), this function never logs ``payload``
    wholesale — only the outcome, mirroring ``handle_send_email``.

    Args:
        payload: ``{"to_email": str, "full_name": str, "token": str,
            "expires_at": str (ISO-8601), "is_resend": bool}``, exactly
            as enqueued by
            ``app.services.invitation_email.QueuedInvitationEmailSender``.
        smtp_settings: This process's own loaded SMTP configuration.
        invitation_settings: This process's own loaded invitation
            configuration (accept-link base URL and path).

    Returns:
        ``True`` if the send succeeded, ``False`` otherwise.
    """
    if not smtp_settings.is_enabled:
        logger.warning(
            "Dropping queued invitation email: SMTP is not configured for this environment."
        )
        return False

    sender = SmtpInvitationEmailSender(
        email_provider=SmtpEmailProvider(settings=smtp_settings), settings=invitation_settings
    )
    return sender.send_invitation(
        to_email=payload["to_email"],
        full_name=payload["full_name"],
        token=payload["token"],
        expires_at=datetime.fromisoformat(payload["expires_at"]),
        is_resend=payload.get("is_resend", False),
    )


def handle_escalate_stage(payload: dict[str, Any], *, approval_service: ApprovalService) -> bool:
    """Execute a single stage escalation.

    Args:
        payload: ``{"stage_id": str}``.
        approval_service: This process's own constructed
            ``ApprovalService``.

    Returns:
        ``True`` on success, or if the escalation could not be applied
        because a human already decided the stage concurrently — per
        ``EscalationJob``'s existing documented contract, this is
        expected, desired behavior under normal operation, not a
        retryable failure or a dead-letter candidate.
    """
    stage_id = UUID(payload["stage_id"])
    try:
        approval_service.escalate_stage(stage_id)
    except ConcurrencyError:
        logger.debug(
            "Escalation for stage %s did not apply (a human likely decided it concurrently).",
            stage_id,
            extra={"stage_id": str(stage_id)},
        )
    return True


def handle_send_reminder(payload: dict[str, Any], *, notification_service: NotificationService) -> bool:
    """Dispatch a single reminder notification.

    Args:
        payload: ``{"recipient_id": str, "request_id": str, "message": str}``.
        notification_service: This process's own constructed
            ``NotificationService``.

    Returns:
        ``True`` on success.
    """
    notification_service.notify_reminder(
        recipient_id=UUID(payload["recipient_id"]),
        request_id=UUID(payload["request_id"]),
        message=payload["message"],
    )
    return True


#: Maps a ``task_type`` string to the collaborator-keyword-argument names
#: its handler needs, beyond ``payload`` — used by both
#: ``app.jobs.worker`` (which has every collaborator available) and
#: ``app.jobs.job_service.SynchronousJobDispatcher`` (which only binds
#: the subset it is constructed with; see that class's docstring for why
#: only ``escalate_stage``/``send_reminder`` are ever actually routed
#: through it in practice).
TASK_HANDLERS: dict[str, Callable[..., bool]] = {
    TASK_SEND_EMAIL: handle_send_email,
    TASK_SEND_INVITATION_EMAIL: handle_send_invitation_email,
    TASK_ESCALATE_STAGE: handle_escalate_stage,
    TASK_SEND_REMINDER: handle_send_reminder,
}
