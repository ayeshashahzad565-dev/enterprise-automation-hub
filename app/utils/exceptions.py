"""Custom exception hierarchy for the app.utils package.

Mirroring the same pattern already established in ``app.database.exceptions``,
``app.models.exceptions``, and ``app.config.exceptions``, every exception a
utility function in this package can raise is defined here, exactly once.
No other module in ``app.utils`` defines its own exception type or raises a
bare ``ValueError``/``TypeError`` for a condition this hierarchy already
covers.
"""

from __future__ import annotations

from typing import Any


class UtilityError(Exception):
    """Base class for every exception raised by the app.utils package.

    Attributes:
        message: A human-readable description of the failure.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{self.__class__.__name__}(message={self.message!r})"


class InputValidationError(UtilityError):
    """Raised when a value fails a generic, reusable validation rule
    (UUID format, string length, ISO-8601 strictness, email shape, etc.),
    as opposed to a domain-specific rule owned by ``app.models``.

    Attributes:
        field_name: The name of the field or value that failed
            validation, included for precise, attributable error
            messages.
        reason: A short description of why validation failed.
    """

    def __init__(self, field_name: str, reason: str) -> None:
        message = f"Validation failed for '{field_name}': {reason}"
        super().__init__(message)
        self.field_name = field_name
        self.reason = reason


class SerializationError(UtilityError):
    """Raised when a Pydantic model cannot be serialized to a dict or JSON
    string.

    In practice this should only ever occur for a genuinely malformed
    model instance (for example, one constructed via
    ``model_construct`` bypassing validation), since a normally
    validated model is always serializable by design.
    """


class DeserializationError(UtilityError):
    """Raised when raw data cannot be deserialized into a target Pydantic
    model.

    Attributes:
        model_name: The name of the target model class.
        details: The structured validation error details produced by
            Pydantic, preserved here so a caller can inspect exactly
            which fields failed without needing to catch Pydantic's own
            exception type directly.
    """

    def __init__(self, model_name: str, reason: str, *, details: Any = None) -> None:
        message = f"Failed to deserialize data into '{model_name}': {reason}"
        super().__init__(message)
        self.model_name = model_name
        self.details = details


class RetryExhaustedError(UtilityError):
    """Raised when a retried operation still fails after its configured
    maximum number of attempts.

    Attributes:
        attempts: The total number of attempts made before giving up.
        last_exception: The exception raised by the final, unsuccessful
            attempt.
    """

    def __init__(self, attempts: int, last_exception: BaseException) -> None:
        message = (
            f"Operation failed after {attempts} attempt(s); "
            f"last error: {last_exception!r}"
        )
        super().__init__(message)
        self.attempts = attempts
        self.last_exception = last_exception
        self.__cause__ = last_exception


class PaginationParameterError(UtilityError):
    """Raised when a page number or page size cannot form a valid,
    bounded pagination request, per API-ADD Section 12's rule that an
    out-of-range value is rejected outright, never silently clamped.
    """


class FileValidationError(UtilityError):
    """Raised when file metadata or content fails one of the upload
    hardening checks specified in API-ADD Section 23 (content-type
    allow-list, size limit, sanitized filename requirements).
    """