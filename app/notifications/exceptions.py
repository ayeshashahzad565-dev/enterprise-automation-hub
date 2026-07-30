"""Custom exception hierarchy for the app.notifications package.

Mirroring the pattern already established in every finalized package,
every exception this package can raise is defined here, exactly once.
``EmailDeliveryError`` and ``NotificationConfigurationError`` are the two
failure modes ``app.notifications.email_sender.SmtpEmailProvider`` itself
raises; ``NotificationError`` is also registered directly as a defensive
FastAPI exception handler (``app.api.exception_handlers``).
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


class NotificationConfigurationError(NotificationError):
    """Raised when a required delivery configuration (most commonly SMTP
    settings) is missing or invalid, independent of any specific
    notification being sent.
    """
