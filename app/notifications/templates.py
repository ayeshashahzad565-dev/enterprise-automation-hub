"""Centralized notification templates, keyed by notification event.

Per this package's design brief, templates support six events —
assignment, approval, rejection, completion, reminder, and escalation —
each with a title and plain-text message template supporting placeholder
substitution, plus a generated HTML variant for channels (email) that can
render rich content.

Placeholder substitution uses Python's built-in ``str.format`` mini-
language (``{placeholder_name}``); a template's required placeholders are
declared alongside it so that a missing value is reported precisely (via
``TemplateRenderingError``) rather than surfacing as an opaque
``KeyError`` from deep inside string formatting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from app.models.enums import NotificationType
from app.notifications.exceptions import TemplateRenderingError
from app.notifications.interfaces import RenderedNotificationContent

__all__ = [
    "NotificationEvent",
    "EVENT_TO_NOTIFICATION_TYPE",
    "NotificationTemplate",
    "TEMPLATE_REGISTRY",
    "DefaultTemplateRenderer",
]

logger = logging.getLogger(__name__)


class NotificationEvent(str, Enum):
    """The six notification-generating events this package renders templates for.

    This is a finer-grained vocabulary than
    ``app.models.enums.NotificationType``: both ``APPROVAL`` and
    ``REJECTION`` here persist as ``NotificationType.DECISION`` (per DSD
    Section 1.5's fixed enum), but they need distinct templates, since an
    approval and a rejection say very different things to a requester.
    ``EVENT_TO_NOTIFICATION_TYPE`` below is the authoritative mapping
    between the two vocabularies.
    """

    ASSIGNMENT = "assignment"
    APPROVAL = "approval"
    REJECTION = "rejection"
    COMPLETION = "completion"
    REMINDER = "reminder"
    ESCALATION = "escalation"


#: The mapping from this package's rendering-level event vocabulary to
#: the DSD-fixed persistence-level ``NotificationType`` enum (DSD Section
#: 1.5, WEDD Section 15.1).
EVENT_TO_NOTIFICATION_TYPE: dict[NotificationEvent, NotificationType] = {
    NotificationEvent.ASSIGNMENT: NotificationType.ASSIGNMENT,
    NotificationEvent.APPROVAL: NotificationType.DECISION,
    NotificationEvent.REJECTION: NotificationType.DECISION,
    NotificationEvent.COMPLETION: NotificationType.COMPLETION,
    NotificationEvent.REMINDER: NotificationType.REMINDER,
    NotificationEvent.ESCALATION: NotificationType.ESCALATION,
}


@dataclass(frozen=True, slots=True)
class NotificationTemplate:
    """A single event's title and message templates.

    Attributes:
        title_template: The ``str.format``-style title template.
        message_template: The ``str.format``-style plain-text message
            template.
        required_placeholders: The set of placeholder names that must be
            present in a context supplied to render this template.
    """

    title_template: str
    message_template: str
    required_placeholders: frozenset[str]


#: The fixed registry of templates for every supported event. Every
#: template's ``required_placeholders`` is exactly the set of names its
#: own ``title_template``/``message_template`` reference — kept in sync
#: manually here since no external templating engine (e.g. Jinja2) is
#: part of the fixed technology stack to derive this automatically.
TEMPLATE_REGISTRY: dict[NotificationEvent, NotificationTemplate] = {
    NotificationEvent.ASSIGNMENT: NotificationTemplate(
        title_template="New assignment: {request_title}",
        message_template=(
            "You have been assigned to review the stage '{stage_name}' "
            "for request '{request_title}'."
        ),
        required_placeholders=frozenset({"request_title", "stage_name"}),
    ),
    NotificationEvent.APPROVAL: NotificationTemplate(
        title_template="Approved: {request_title}",
        message_template=(
            "The stage '{stage_name}' on your request '{request_title}' "
            "was approved by {decider_name}."
        ),
        required_placeholders=frozenset({"request_title", "stage_name", "decider_name"}),
    ),
    NotificationEvent.REJECTION: NotificationTemplate(
        title_template="Rejected: {request_title}",
        message_template=(
            "Your request '{request_title}' was rejected at the '{stage_name}' "
            "stage by {decider_name}. Reason: {decision_note}"
        ),
        required_placeholders=frozenset(
            {"request_title", "stage_name", "decider_name", "decision_note"}
        ),
    ),
    NotificationEvent.COMPLETION: NotificationTemplate(
        title_template="Completed: {request_title}",
        message_template="Your request '{request_title}' has been completed.",
        required_placeholders=frozenset({"request_title"}),
    ),
    NotificationEvent.REMINDER: NotificationTemplate(
        title_template="Reminder: {request_title} awaiting your review",
        message_template=(
            "The stage '{stage_name}' on request '{request_title}' has been "
            "awaiting your decision since {created_at}. Please review it when "
            "you have a moment."
        ),
        required_placeholders=frozenset({"request_title", "stage_name", "created_at"}),
    ),
    NotificationEvent.ESCALATION: NotificationTemplate(
        title_template="Escalated: {request_title}",
        message_template=(
            "The stage '{stage_name}' on request '{request_title}' was overdue "
            "and has been escalated to you for review."
        ),
        required_placeholders=frozenset({"request_title", "stage_name"}),
    ),
}


class DefaultTemplateRenderer:
    """The default ``TemplateRenderer`` implementation, backed by ``TEMPLATE_REGISTRY``.

    Renders plain-text title and message via ``str.format``, and
    generates a minimal HTML variant by wrapping the rendered title and
    message in basic markup — no external templating engine is
    introduced, consistent with the fixed technology stack.
    """

    def __init__(self, registry: Mapping[NotificationEvent, NotificationTemplate] | None = None) -> None:
        """Initialize the renderer with a template registry.

        Args:
            registry: The event-to-template mapping to render from.
                Defaults to the module-level ``TEMPLATE_REGISTRY``.
        """
        self._registry = registry if registry is not None else TEMPLATE_REGISTRY

    def render(
        self, event: NotificationEvent, context: Mapping[str, Any]
    ) -> RenderedNotificationContent:
        """Render an event's template against a context.

        Args:
            event: The notification event to render.
            context: The placeholder values to substitute.

        Returns:
            The rendered plain-text and HTML content.

        Raises:
            TemplateRenderingError: If no template is registered for
                ``event``, or a required placeholder is missing from
                ``context``.
        """
        template = self._registry.get(event)
        if template is None:
            raise TemplateRenderingError(event.value, reason="no template is registered for this event")

        missing = template.required_placeholders - context.keys()
        if missing:
            raise TemplateRenderingError(event.value, missing_field=sorted(missing)[0])

        try:
            title = template.title_template.format(**context)
            message = template.message_template.format(**context)
        except (KeyError, IndexError, ValueError) as exc:
            raise TemplateRenderingError(event.value, reason=str(exc)) from exc

        html_message = (
            f"<html><body><h2>{title}</h2><p>{message}</p></body></html>"
        )

        logger.debug(
            "Rendered template for event=%s", event.value, extra={"event": event.value}
        )
        return RenderedNotificationContent(title=title, message=message, html_message=html_message)