"""Custom exception hierarchy for the app.ai package.

Mirroring ``app.notifications.exceptions``' own shape: every exception this
package can raise is defined here, exactly once.
"""

from __future__ import annotations

from typing import Any


class AiError(Exception):
    """Base class for every exception raised by the app.ai package.

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


class AiConfigurationError(AiError):
    """Raised when a provider is constructed from missing or invalid
    configuration (an unset/blank API key or model), independent of any
    specific completion request.
    """


class AiProviderError(AiError):
    """Raised when a completion request fails for any reason — invalid
    credentials, a rate limit, a network/timeout failure, or an unparsable
    response — after any internally-applied retry is exhausted.

    One exception type is sufficient here: every caller of ``AiProvider``
    (in practice, only ``AiInsightService``) handles every failure mode
    identically — log a warning and fall back to non-AI content — so there
    is no behavioral distinction for a caller to make between an auth
    failure and a timeout.

    Attributes:
        provider_name: The provider that raised this error.
    """

    def __init__(self, provider_name: str, reason: str) -> None:
        super().__init__(
            f"AI provider '{provider_name}' request failed: {reason}",
            details={"provider_name": provider_name},
        )
        self.provider_name = provider_name
