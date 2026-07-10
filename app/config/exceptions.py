"""Custom exception hierarchy for the app.config package.

Every exception raised anywhere in ``app.config`` — whether during
environment detection, settings loading, or path resolution — is defined
here. This mirrors the same pattern already established in
``app.database.exceptions`` and ``app.models.exceptions``: a package-owned,
precise exception vocabulary that calling code can catch specifically,
rather than a generic ``ValueError`` or ``KeyError`` it would need to
inspect further to understand.
"""

from __future__ import annotations


class ConfigurationError(Exception):
    """Base class for every exception raised by the app.config package.

    Attributes:
        message: A human-readable description of the configuration
            failure. Safe to include in startup logs; never includes the
            *value* of a secret-bearing environment variable, only its
            *name* (see ``app.config.security.redact_secret`` for the
            corresponding redaction helper used elsewhere in this
            package).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{self.__class__.__name__}(message={self.message!r})"


class MissingEnvironmentVariableError(ConfigurationError):
    """Raised when a required environment variable is absent or empty.

    Attributes:
        variable_name: The name of the missing environment variable.
    """

    def __init__(self, variable_name: str) -> None:
        message = (
            f"Required environment variable '{variable_name}' is not set. "
            "Copy .env.example to .env and populate it, per the Deployment "
            "Guide's Environment Variables reference."
        )
        super().__init__(message)
        self.variable_name = variable_name


class InvalidConfigurationValueError(ConfigurationError):
    """Raised when an environment variable is present but cannot be parsed
    into its expected type, or fails a validation rule once parsed.

    Attributes:
        variable_name: The name of the offending environment variable.
        reason: A short description of why the value is invalid.
    """

    def __init__(self, variable_name: str, reason: str) -> None:
        message = f"Invalid value for environment variable '{variable_name}': {reason}"
        super().__init__(message)
        self.variable_name = variable_name
        self.reason = reason


class EnvironmentDetectionError(ConfigurationError):
    """Raised when the running environment cannot be determined, or the
    value supplied does not match a recognized ``Environment`` member.

    Attributes:
        raw_value: The unrecognized value that was supplied, if any.
    """

    def __init__(self, raw_value: str | None) -> None:
        message = (
            f"Unable to determine the running environment from value "
            f"{raw_value!r}. Expected one of: development, testing, "
            "staging, production."
        )
        super().__init__(message)
        self.raw_value = raw_value


class LoggingConfigurationError(ConfigurationError):
    """Raised when logging cannot be configured as requested — for
    example, an unrecognized log level name.
    """