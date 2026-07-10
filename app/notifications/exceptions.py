"""Custom exception hierarchy for the app.notifications package.

Mirroring the pattern already established in every finalized package,
every exception this package can raise is defined here, exactly once.
Each branch corresponds to one of this package's four responsibilities:
template rendering, email delivery, in-app persistence, and
configuration.
"""

from __future__ import annotations

from typing import Any


class NotificationError(Exception):
    """Base class for every exception raised by the app.notifications package.

    Attributes:
        message: A human-readable description of the failure.
        details: A structured, machine-inspectable payload describing the
            failure.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{self.__class__.__name__}(message={self.message!r}, details={self.details!r})"


class TemplateRenderingError(NotificationError):
    """Raised when a notification template cannot be rendered.

    Attributes:
        event: The notification event the template was selected for, as
            a plain string (avoids a hard import dependency on
            ``NotificationEvent`` at the exception level).
        missing_field: The name of the placeholder that could not be
            resolved from the supplied context, if that was the cause.
    """

    def __init__(self, event: str, *, missing_field: str | None = None, reason: str | None = None) -> None:
        if missing_field is not None:
            message = f"Cannot render template for event '{event}': missing placeholder '{missing_field}'."
        else:
            message = f"Cannot render template for event '{event}': {reason or 'unknown error'}."
        super().__init__(message, details={"event": event, "missing_field": missing_field})
        self.event = event
        self.missing_field = missing_field


class EmailDeliveryError(NotificationError):
    """Raised when an email could not be delivered after all configured
    retry attempts were exhausted, or a non-retryable SMTP failure
    occurred (e.g. authentication failure).

    Attributes:
        to_address: The intended recipient address.
    """

    def __init__(self, to_address: str, reason: str) -> None:
        super().__init__(
            f"Failed to deliver email to '{to_address}': {reason}",
            details={"to_address": to_address},
        )
        self.to_address = to_address


class NotificationPersistenceError(NotificationError):
    """Raised when a notification record cannot be created through the
    Repository Layer.
    """


class NotificationConfigurationError(NotificationError):
    """Raised when a required delivery configuration (most commonly SMTP
    settings) is missing or invalid, independent of any specific
    notification being sent.
    """