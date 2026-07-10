"""Notification delivery coordination.

Per this package's design brief, ``NotificationManager`` accepts
notification requests from Application Services and dispatches them
through one or more delivery channels — it contains no SMTP
implementation details itself, delegating all channel-specific delivery
to injected ``NotificationChannel`` implementations, and no persistence
implementation details, delegating those to an injected
``InAppNotifier``.

``NotificationManager`` does not decide *when* a notification should
occur — per this package's stated scope, that orchestration belongs to
``app.services``. It supports exactly the six events named in this
package's design brief: assignment, approval, rejection, completion,
reminder, and escalation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import UUID

from app.notifications.exceptions import NotificationPersistenceError
from app.notifications.in_app_notifier import InAppNotifier
from app.notifications.interfaces import ChannelDeliveryResult, NotificationChannel
from app.notifications.notification_factory import NotificationFactory, NotificationPayload
from app.notifications.templates import NotificationEvent

__all__ = ["DeliveryReport", "NotificationManager"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    """The outcome of dispatching a single notification across every configured channel.

    Attributes:
        notification_id: The id of the persisted ``notifications`` row.
        payload: The payload that was dispatched.
        channel_results: The outcome of every additional (beyond in-app
            persistence, which is mandatory and represented by
            ``notification_id`` alone) delivery channel attempted.
    """

    notification_id: UUID
    payload: NotificationPayload
    channel_results: tuple[ChannelDeliveryResult, ...]

    @property
    def all_channels_succeeded(self) -> bool:
        """Whether every additional delivery channel succeeded.

        Returns:
            ``True`` if ``channel_results`` is empty or every entry in it
            reports success. In-app persistence itself is not included
            in this check, since a failure there raises
            ``NotificationPersistenceError`` rather than producing a
            ``DeliveryReport`` at all.
        """
        return all(result.success for result in self.channel_results)


class NotificationManager:
    """Coordinates notification payload construction, persistence, and delivery.

    In-app persistence (via the injected ``InAppNotifier``) is mandatory
    and always attempted first — without a persisted row, there is
    nothing for a read/unread status or an audit-adjacent record to
    reference, so a persistence failure propagates as
    ``NotificationPersistenceError`` rather than being treated as just
    another channel outcome. Every additional channel (most commonly
    email) is attempted afterward, independently, and its failure is
    captured in the returned ``DeliveryReport`` rather than raised —
    matching the architecture's principle that email delivery is a
    best-effort side effect of an already-durable fact.
    """

    def __init__(
        self,
        *,
        factory: NotificationFactory,
        in_app_notifier: InAppNotifier,
        channels: Sequence[NotificationChannel] = (),
    ) -> None:
        """Initialize the manager with its injected collaborators.

        Args:
            factory: Builds notification payloads from events and
                context.
            in_app_notifier: Persists every notification; mandatory.
            channels: Additional delivery channels to attempt after
                persistence (for example, a single
                ``EmailNotificationChannel``). May be empty, in which
                case notifications are persisted in-app only.
        """
        self._factory = factory
        self._in_app_notifier = in_app_notifier
        self._channels = tuple(channels)
        self._logger = logging.getLogger(f"{__name__}.NotificationManager")

    def notify_assignment(
        self,
        *,
        recipient_id: UUID,
        request_id: UUID,
        request_title: str,
        stage_name: str,
        recipient_email: str | None = None,
    ) -> DeliveryReport:
        """Dispatch an assignment notification.

        Args:
            recipient_id: The user newly assigned to a stage.
            request_id: The related request.
            request_title: The request's title, for template rendering.
            stage_name: The stage's name, for template rendering.
            recipient_email: The recipient's email address, if known.

        Returns:
            A ``DeliveryReport`` describing the outcome.
        """
        return self._dispatch(
            NotificationEvent.ASSIGNMENT,
            recipient_id=recipient_id,
            request_id=request_id,
            context={"request_title": request_title, "stage_name": stage_name},
            recipient_email=recipient_email,
        )

    def notify_approval(
        self,
        *,
        recipient_id: UUID,
        request_id: UUID,
        request_title: str,
        stage_name: str,
        decider_name: str,
        recipient_email: str | None = None,
    ) -> DeliveryReport:
        """Dispatch an approval-decision notification.

        Args:
            recipient_id: The requester to notify.
            request_id: The related request.
            request_title: The request's title.
            stage_name: The approved stage's name.
            decider_name: The display name of the approver who decided
                it.
            recipient_email: The recipient's email address, if known.

        Returns:
            A ``DeliveryReport`` describing the outcome.
        """
        return self._dispatch(
            NotificationEvent.APPROVAL,
            recipient_id=recipient_id,
            request_id=request_id,
            context={
                "request_title": request_title,
                "stage_name": stage_name,
                "decider_name": decider_name,
            },
            recipient_email=recipient_email,
        )

    def notify_rejection(
        self,
        *,
        recipient_id: UUID,
        request_id: UUID,
        request_title: str,
        stage_name: str,
        decider_name: str,
        decision_note: str,
        recipient_email: str | None = None,
    ) -> DeliveryReport:
        """Dispatch a rejection-decision notification.

        Args:
            recipient_id: The requester to notify.
            request_id: The related request.
            request_title: The request's title.
            stage_name: The rejected stage's name.
            decider_name: The display name of the approver who rejected
                it.
            decision_note: The stated reason for rejection.
            recipient_email: The recipient's email address, if known.

        Returns:
            A ``DeliveryReport`` describing the outcome.
        """
        return self._dispatch(
            NotificationEvent.REJECTION,
            recipient_id=recipient_id,
            request_id=request_id,
            context={
                "request_title": request_title,
                "stage_name": stage_name,
                "decider_name": decider_name,
                "decision_note": decision_note,
            },
            recipient_email=recipient_email,
        )

    def notify_completion(
        self,
        *,
        recipient_id: UUID,
        request_id: UUID,
        request_title: str,
        recipient_email: str | None = None,
    ) -> DeliveryReport:
        """Dispatch a completion notification.

        Args:
            recipient_id: The requester to notify.
            request_id: The related request.
            request_title: The request's title.
            recipient_email: The recipient's email address, if known.

        Returns:
            A ``DeliveryReport`` describing the outcome.
        """
        return self._dispatch(
            NotificationEvent.COMPLETION,
            recipient_id=recipient_id,
            request_id=request_id,
            context={"request_title": request_title},
            recipient_email=recipient_email,
        )

    def notify_reminder(
        self,
        *,
        recipient_id: UUID,
        request_id: UUID,
        request_title: str,
        stage_name: str,
        created_at: str,
        recipient_email: str | None = None,
    ) -> DeliveryReport:
        """Dispatch a reminder notification.

        Invoked by the Scheduler's Reminder Dispatch job (via
        ``app.services``) for stages nearing, but not yet past, their
        escalation threshold.

        Args:
            recipient_id: The current assignee.
            request_id: The related request.
            request_title: The request's title.
            stage_name: The stage's name.
            created_at: A human-readable rendering of the stage's
                creation timestamp, for template display.
            recipient_email: The recipient's email address, if known.

        Returns:
            A ``DeliveryReport`` describing the outcome.
        """
        return self._dispatch(
            NotificationEvent.REMINDER,
            recipient_id=recipient_id,
            request_id=request_id,
            context={
                "request_title": request_title,
                "stage_name": stage_name,
                "created_at": created_at,
            },
            recipient_email=recipient_email,
        )

    def notify_escalation(
        self,
        *,
        recipient_id: UUID,
        request_id: UUID,
        request_title: str,
        stage_name: str,
        recipient_email: str | None = None,
    ) -> DeliveryReport:
        """Dispatch an escalation notification.

        Args:
            recipient_id: The newly (re)assigned user.
            request_id: The related request.
            request_title: The request's title.
            stage_name: The escalated stage's name.
            recipient_email: The recipient's email address, if known.

        Returns:
            A ``DeliveryReport`` describing the outcome.
        """
        return self._dispatch(
            NotificationEvent.ESCALATION,
            recipient_id=recipient_id,
            request_id=request_id,
            context={"request_title": request_title, "stage_name": stage_name},
            recipient_email=recipient_email,
        )

    def _dispatch(
        self,
        event: NotificationEvent,
        *,
        recipient_id: UUID,
        request_id: UUID | None,
        context: Mapping[str, Any],
        recipient_email: str | None,
    ) -> DeliveryReport:
        """Shared implementation for every ``notify_*`` method.

        Args:
            event: The notification event being dispatched.
            recipient_id: The notification's recipient.
            request_id: The related request, if any.
            context: The placeholder values for template rendering.
            recipient_email: The recipient's email address, if known.

        Returns:
            A ``DeliveryReport`` describing the outcome.

        Raises:
            TemplateRenderingError: If the event's template cannot be
                rendered against ``context``.
            NotificationPersistenceError: If the notification cannot be
                persisted in-app.
        """
        payload = self._factory.build(
            event,
            recipient_id=recipient_id,
            request_id=request_id,
            context=context,
            recipient_email=recipient_email,
        )

        record = self._in_app_notifier.create(payload)

        channel_results: list[ChannelDeliveryResult] = []
        for channel in self._channels:
            try:
                result = channel.deliver(payload)
            except Exception as exc:  # noqa: BLE001 - a channel must never break dispatch for the rest
                self._logger.error(
                    "Channel '%s' raised unexpectedly during delivery of notification %s: %s",
                    channel.channel_name,
                    record.id,
                    exc,
                    exc_info=exc,
                    extra={"channel": channel.channel_name, "notification_id": str(record.id)},
                )
                result = ChannelDeliveryResult(
                    channel_name=channel.channel_name, success=False, detail=str(exc)
                )
            channel_results.append(result)

            if result.channel_name == "email" and result.success:
                try:
                    self._in_app_notifier.mark_email_sent(record.id)
                except NotificationPersistenceError as exc:
                    self._logger.warning(
                        "Email delivered for notification %s but failed to record "
                        "email_sent: %s",
                        record.id,
                        exc,
                        extra={"notification_id": str(record.id)},
                    )

        self._logger.info(
            "Dispatched notification %s (event=%s) across %d additional channel(s)",
            record.id,
            event.value,
            len(channel_results),
            extra={"notification_id": str(record.id), "event": event.value},
        )

        return DeliveryReport(
            notification_id=record.id, payload=payload, channel_results=tuple(channel_results)
        )