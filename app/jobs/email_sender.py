"""A queue-backed ``EmailSender`` implementation.

Implements ``app.services.notification_service.EmailSender`` — the exact
protocol ``app.bootstrap``'s ``_EmailSenderAdapter`` already satisfies —
so plugging this in requires no change to ``NotificationService`` or
``ThreadPoolEmailDispatchExecutor`` at all: they only ever call
``.send()`` on whichever implementation was wired in.

``.send()`` here does not perform SMTP I/O itself; it enqueues a durable
job (``app.jobs.job_service.JobService``) and returns immediately.
Consistent with this Protocol's existing meaning elsewhere in this
codebase — "dispatch succeeded," not "delivery confirmed" — returning
``True`` here means "durably recorded and handed off for asynchronous
delivery," to be actually delivered by a separate ``app.jobs.worker``
process running with ``--role default`` (or ``all``).
"""

from __future__ import annotations

import logging

from app.jobs.job_service import JobService
from app.jobs.task_types import TASK_SEND_EMAIL

__all__ = ["RedisQueueEmailSender"]

logger = logging.getLogger(__name__)


class RedisQueueEmailSender:
    """Enqueues an email for asynchronous delivery by a separate worker process."""

    def __init__(self, *, job_service: JobService) -> None:
        """Initialize the sender.

        Args:
            job_service: The shared job service to enqueue through.
        """
        self._job_service = job_service

    def send(self, *, to_address: str, subject: str, body: str) -> bool:
        """Enqueue an email for delivery, returning immediately.

        Args:
            to_address: The recipient's email address.
            subject: The email subject line.
            body: The plain-text email body.

        Returns:
            ``True`` if the job was successfully enqueued; ``False`` if
            enqueuing itself raised (matching ``EmailSender``'s "dispatch
            failed" contract — the caller treats this exactly like a
            synchronous send failure). A Redis push failure specifically
            does *not* surface here — ``JobService.enqueue`` already
            treats that as recoverable (see its own docstring) and still
            returns a durably-created job, so this only returns ``False``
            on an unexpected failure to even record the job's intent.
        """
        try:
            job = self._job_service.enqueue(
                task_type=TASK_SEND_EMAIL,
                queue_name="default",
                payload={"to_address": to_address, "subject": subject, "body": body},
            )
        except Exception:
            logger.exception("Failed to enqueue email for %s", to_address)
            return False
        logger.debug("Enqueued email job %s for %s", job.id, to_address)
        return True
