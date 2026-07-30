"""``task_type`` string constants for the job system.

Split out from ``app.jobs.handlers`` (which imports every service class a
handler needs — ``ApprovalService``, ``NotificationService``,
``SmtpInvitationEmailSender``) so that a *producer* module needing only
the ``task_type`` string it enqueues under (``app.services.invitation_email``,
``app.jobs.email_sender``, ``app.scheduler.escalation_job``,
``app.scheduler.reminder_job``) never has to import that whole dependency
chain — several of those producers are themselves imported *by* modules
``app.jobs.handlers`` depends on, which would otherwise be a circular
import.
"""

from __future__ import annotations

__all__ = [
    "TASK_SEND_EMAIL",
    "TASK_SEND_INVITATION_EMAIL",
    "TASK_ESCALATE_STAGE",
    "TASK_SEND_REMINDER",
]

TASK_SEND_EMAIL = "send_email"
TASK_SEND_INVITATION_EMAIL = "send_invitation_email"
TASK_ESCALATE_STAGE = "escalate_stage"
TASK_SEND_REMINDER = "send_reminder"
