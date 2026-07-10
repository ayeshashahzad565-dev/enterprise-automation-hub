"""Protocols, abstract base classes, and shared value objects for app.notifications.

Per this package's design brief, four abstractions are defined here:

- ``TemplateRenderer`` (Protocol): renders a notification event and
  context into displayable content.
- ``EmailProvider`` (Protocol): the SMTP-level abstraction a concrete
  email implementation satisfies — deliberately the lowest-level
  interface in this package, with no knowledge of notification events,
  templates, or persistence.
- ``NotificationSender`` (Protocol): the generic, single-payload delivery
  capability every channel ultimately provides.
- ``NotificationChannel`` (ABC): a named, pluggable delivery channel that
  ``NotificationManager`` iterates over. Implemented as an ABC rather
  than a pure Protocol because concrete channels carry injected
  constructor state (an ``EmailProvider``, a repository, etc.) and share
  a small amount of common shape (a ``channel_name`` property) that is
  more naturally expressed as inheritance here.

This module also defines ``RenderedNotificationContent`` and
``ChannelDeliveryResult``, the small value objects passed between the
components above.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RenderedNotificationContent:
    """The output of rendering a notification template against a context.

    Attributes:
        title: The rendered, short summary line.
        message: The rendered, plain-text body.
        html_message: The rendered HTML body, for channels (email) that
            can display rich content. ``None`` for a template with no
            HTML variant.
    """

    title: str
    message: str
    html_message: str | None = None


@runtime_checkable
class TemplateRenderer(Protocol):
    """Structural interface for rendering a notification event's template."""

    def render(self, event: Any, context: Mapping[str, Any]) -> RenderedNotificationContent:
        """Render a notification event's template against a context.

        Args:
            event: The notification event to render a template for
                (an ``app.notifications.templates.NotificationEvent``
                member).
            context: The placeholder values to substitute into the
                template.

        Returns:
            The rendered content.

        Raises:
            TemplateRenderingError: If no template is registered for
                ``event``, or a required placeholder is missing from
                ``context``.
        """
        ...


@runtime_checkable
class EmailProvider(Protocol):
    """Structural interface for the SMTP-level email delivery capability.

    This is deliberately the lowest-level abstraction in this package: an
    implementation knows nothing about notification events, templates, or
    persistence — only how to send one email to one address.
    """

    def send_email(
        self,
        *,
        to_address: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
    ) -> None:
        """Send a single email, retrying transient failures internally.

        Args:
            to_address: The recipient's email address.
            subject: The email subject line.
            text_body: The plain-text email body.
            html_body: The HTML email body, if the message supports rich
                content. When provided, implementations are expected to
                send a multipart message offering both representations.

        Raises:
            EmailDeliveryError: If the email could not be delivered after
                every configured retry attempt was exhausted, or a
                non-retryable failure occurred.
        """
        ...


@dataclass(frozen=True, slots=True)
class ChannelDeliveryResult:
    """The outcome of one delivery channel's attempt to deliver a notification.

    Attributes:
        channel_name: The name of the channel that produced this result.
        success: Whether delivery succeeded.
        detail: A short, human-readable explanation, populated
            particularly when ``success`` is ``False``.
    """

    channel_name: str
    success: bool
    detail: str | None = None


@runtime_checkable
class NotificationSender(Protocol):
    """Structural interface for a generic, single-payload delivery capability.

    This is the minimal capability every delivery channel provides;
    ``NotificationChannel`` below builds on it with a name and a
    non-raising delivery contract suitable for ``NotificationManager`` to
    invoke uniformly across many channels without one channel's failure
    interrupting the others.
    """

    def send(self, payload: Any) -> bool:
        """Attempt to deliver a single notification payload.

        Args:
            payload: The notification payload to deliver (an
                ``app.notifications.notification_factory.NotificationPayload``).

        Returns:
            ``True`` if delivery succeeded, ``False`` otherwise.
        """
        ...


class NotificationChannel(ABC):
    """Abstract base class for a named, pluggable notification delivery channel.

    ``NotificationManager`` holds a collection of these and invokes each
    uniformly. A channel's ``deliver`` method never raises for an
    ordinary delivery failure — it reports failure via
    ``ChannelDeliveryResult`` instead, so that one channel's failure can
    never prevent ``NotificationManager`` from attempting the remaining
    channels.
    """

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """A short, stable identifier for this channel (e.g. ``"email"``)."""
        ...

    @abstractmethod
    def deliver(self, payload: Any) -> ChannelDeliveryResult:
        """Attempt to deliver a notification payload through this channel.

        Args:
            payload: The notification payload to deliver (an
                ``app.notifications.notification_factory.NotificationPayload``).

        Returns:
            A ``ChannelDeliveryResult`` describing the outcome. This
            method is expected never to raise for an ordinary delivery
            failure (network error, missing recipient address); such
            failures are captured in the returned result instead.
        """
        ...