"""Security-related constants and helper functions.

Per the ADD's Security Architecture, the API Design Document's Security
Considerations (API-ADD Section 24), and the Deployment Guide's Security
Hardening section (DG Section 19), this module centralizes:

- Fixed security-relevant constants (the bearer authentication scheme
  name, the attachment content-type allow-list, size limits) that are
  referenced by configuration but never change per-environment.
- A small set of pure helper functions for handling sensitive
  configuration values safely — most importantly, redacting a secret so
  it can be referenced in a log message or error without ever printing
  its actual value, per DG Section 19.2's rule that no secret value is
  ever interpolated into a logged message.

This module performs no I/O, holds no actual secret values (it defines
only which *variable names* are considered sensitive, never a value), and
contains no business logic.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Authentication scheme (API-ADD Section 5.2)
# ---------------------------------------------------------------------------

AUTHORIZATION_HEADER_NAME: Final[str] = "Authorization"
BEARER_AUTH_SCHEME: Final[str] = "Bearer"

# ---------------------------------------------------------------------------
# File upload hardening (API-ADD Section 23, DG Section 19.6)
# ---------------------------------------------------------------------------

#: The content-type allow-list attachments are validated against before
#: upload. Matches API-ADD Section 23's file-handling discipline; kept as
#: a fixed security constant rather than an environment variable, since
#: this is a security boundary, not environment-specific tuning.
#: ``application/zip`` was added alongside this application's attachment
#: feature build-out, per that feature's explicit requirement to support
#: ZIP uploads — every other entry here predates that work.
ALLOWED_ATTACHMENT_CONTENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "text/plain",
        "text/csv",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
    }
)

#: Maximum accepted attachment size in bytes (25 MB), matching the
#: DSD Section 4.1 check constraint that ``size_bytes > 0`` combined with
#: the API-ADD's documented upper bound for a single upload.
MAX_ATTACHMENT_SIZE_BYTES: Final[int] = 25 * 1024 * 1024

#: The single Supabase Storage bucket every attachment is written to and
#: read from, per the Deployment Guide's "a single bucket for
#: attachments" provisioning note. Kept as a fixed constant, not an
#: environment variable, for the same reason as the constants above: this
#: names a fixed architectural boundary, not per-environment tuning — a
#: different deployment environment already gets an entirely separate
#: Supabase project (and therefore an entirely separate bucket namespace)
#: via its own ``SUPABASE_URL``/keys, so the bucket's own name never needs
#: to vary. This bucket must be created (and its access policy configured
#: to mirror the ``attachments`` table's RLS policies) as an operator
#: step before this application's attachment features are used, exactly
#: like a database migration — see ``docs/deployment.md``.
ATTACHMENTS_STORAGE_BUCKET: Final[str] = "attachments"

# ---------------------------------------------------------------------------
# Secret handling
# ---------------------------------------------------------------------------

#: Environment variable names whose values must never be logged,
#: printed, or otherwise surfaced outside the process that reads them, per
#: DG Section 9.2. Any variable name in this set is redacted by
#: ``redact_secret`` before appearing in any diagnostic output this
#: package produces.
SENSITIVE_ENV_VAR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_ANON_KEY",
        "DATABASE_URL",
        "SMTP_PASSWORD",
    }
)

#: The number of trailing characters of a secret value preserved by
#: ``redact_secret`` for operator troubleshooting (e.g. confirming which
#: of several rotated keys is currently loaded) without revealing enough
#: of the value to reconstruct or reuse it.
_REDACTION_VISIBLE_SUFFIX_LENGTH: Final[int] = 4
_REDACTION_MASK: Final[str] = "*" * 8


def is_sensitive_env_var(variable_name: str) -> bool:
    """Return whether an environment variable name is considered sensitive.

    Args:
        variable_name: The environment variable's name.

    Returns:
        ``True`` if this variable's value must be redacted before being
        logged or displayed, per ``SENSITIVE_ENV_VAR_NAMES``.
    """
    return variable_name in SENSITIVE_ENV_VAR_NAMES


def redact_secret(value: str | None) -> str:
    """Redact a secret value for safe inclusion in logs or error messages.

    Args:
        value: The raw secret value. May be ``None`` or empty, in which
            case a fixed placeholder is returned rather than an empty
            string, so that "not set" and "set but redacted" are never
            visually confusable in a log line.

    Returns:
        A masked string preserving only the last
        ``_REDACTION_VISIBLE_SUFFIX_LENGTH`` characters of ``value``
        (useful for an operator to confirm, e.g., which key rotation is
        active, without exposing enough of the value to reuse it), or
        ``"<not set>"`` if ``value`` was ``None`` or empty.
    """
    if not value:
        return "<not set>"
    if len(value) <= _REDACTION_VISIBLE_SUFFIX_LENGTH:
        return _REDACTION_MASK
    return f"{_REDACTION_MASK}{value[-_REDACTION_VISIBLE_SUFFIX_LENGTH:]}"


def redact_mapping_for_logging(values: dict[str, str]) -> dict[str, str]:
    """Redact every sensitive value in a mapping of environment variable
    name to value, leaving non-sensitive values untouched.

    Args:
        values: A mapping of environment variable name to its raw value.

    Returns:
        A new dict with the same keys; values whose key is in
        ``SENSITIVE_ENV_VAR_NAMES`` are replaced with the result of
        ``redact_secret``, and every other value is passed through
        unchanged.
    """
    return {
        name: redact_secret(value) if is_sensitive_env_var(name) else value
        for name, value in values.items()
    }
