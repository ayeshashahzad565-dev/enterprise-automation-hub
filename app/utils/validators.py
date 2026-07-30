"""Generic, reusable field-level validation utilities.

Every function in this module validates the *shape* of a single value —
a UUID string, a string length, an ISO-8601 timestamp, an email address —
against a rule already fixed by the architecture documents (principally
API-ADD Section 22, Validation Rules). These are deliberately generic,
reusable primitives, not a re-implementation of any specific Pydantic
model's field constraints already declared in ``app.models`` — those
models remain the authoritative, single point of validation for a given
domain entity's shape; this module exists for the cases where a value
needs the same validation *before* it ever reaches a Pydantic model (for
example, validating a raw path parameter at the boundary of a future API
layer, per API-ADD Section 22's rule that a malformed UUID path parameter
returns ``400``, not ``404``, because it fails before a resource lookup
is even attempted).

Every function here either returns the validated, parsed value or raises
``app.utils.exceptions.InputValidationError`` — none returns a bare
boolean silently swallowing the reason for failure, since a caller
handling a validation failure needs to know *why* it failed to construct
a useful error response.
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from app.utils.datetime_utils import parse_iso8601
from app.utils.exceptions import InputValidationError

__all__ = [
    "validate_uuid",
    "is_valid_uuid",
    "validate_string_length",
    "validate_non_empty_string",
    "validate_email",
    "validate_iso8601_datetime",
    "validate_positive_integer",
    "validate_positive_number",
]

#: A deliberately permissive but structurally sound email pattern:
#: one or more non-whitespace, non-'@' characters, an '@', one or more
#: non-whitespace, non-'@' characters, a '.', and a final segment. This
#: validates shape only (per API-ADD Section 19.1.1: "email must be
#: syntactically valid") — it never asserts deliverability, which is
#: Supabase Auth's own concern, not this utility's.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_uuid(value: str, *, field_name: str = "id") -> UUID:
    """Validate that a string is a well-formed UUID.

    Corresponds to API-ADD Section 22's rule: "a path parameter that
    fails to parse as a UUID returns 400 (malformed request), not 404,
    since the request never reached the point of a resource lookup."

    Args:
        value: The candidate UUID string.
        field_name: The name of the field being validated, used to
            produce a precise error message.

    Returns:
        The parsed ``UUID``.

    Raises:
        InputValidationError: If ``value`` is not a well-formed UUID.
    """
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise InputValidationError(field_name, f"'{value}' is not a valid UUID.") from exc


def is_valid_uuid(value: str) -> bool:
    """Return whether a string is a well-formed UUID, without raising.

    A non-raising convenience wrapper around ``validate_uuid``, useful in
    contexts (such as a boolean filter condition) where the caller only
    needs a yes/no answer and does not need the parsed value or a
    detailed failure reason.

    Args:
        value: The candidate UUID string.

    Returns:
        ``True`` if ``value`` is a well-formed UUID, ``False`` otherwise.
    """
    try:
        validate_uuid(value)
    except InputValidationError:
        return False
    return True


def validate_string_length(
    value: str,
    *,
    field_name: str,
    min_length: int = 0,
    max_length: int,
) -> str:
    """Validate that a string's length (after stripping whitespace) falls
    within a required range.

    Matches the explicit, per-field maximum lengths fixed throughout the
    API Design Document (for example, ``title``: 1-200 characters,
    ``description``: up to 5,000 characters, per API-ADD Section 22).

    Args:
        value: The candidate string.
        field_name: The name of the field being validated.
        min_length: The minimum acceptable length, inclusive. Defaults to
            ``0`` (no minimum).
        max_length: The maximum acceptable length, inclusive.

    Returns:
        The stripped, validated string.

    Raises:
        InputValidationError: If the stripped string's length is outside
            ``[min_length, max_length]``.
    """
    stripped = value.strip()
    if len(stripped) < min_length:
        raise InputValidationError(
            field_name,
            f"must be at least {min_length} character(s), got {len(stripped)}.",
        )
    if len(stripped) > max_length:
        raise InputValidationError(
            field_name,
            f"must be at most {max_length} character(s), got {len(stripped)}.",
        )
    return stripped


def validate_non_empty_string(value: str, *, field_name: str) -> str:
    """Validate that a string is non-empty after stripping whitespace.

    A convenience specialization of ``validate_string_length`` with
    ``min_length=1`` and an effectively unbounded ``max_length``, for the
    common case of a required field with no specific upper bound to
    enforce at this layer.

    Args:
        value: The candidate string.
        field_name: The name of the field being validated.

    Returns:
        The stripped, validated string.

    Raises:
        InputValidationError: If the stripped string is empty.
    """
    return validate_string_length(
        value, field_name=field_name, min_length=1, max_length=len(value.strip()) or 1
    )


def validate_email(value: str, *, field_name: str = "email") -> str:
    """Validate that a string is a syntactically valid email address.

    Matches API-ADD Section 19.1.1's requirement that ``email`` "must be
    a syntactically valid email address" — no deliverability check is
    performed, per that same section's note that this is Supabase Auth's
    concern.

    Args:
        value: The candidate email address.
        field_name: The name of the field being validated.

    Returns:
        The stripped, validated email address.

    Raises:
        InputValidationError: If ``value`` does not match a syntactically
            valid email shape.
    """
    stripped = value.strip()
    if not _EMAIL_PATTERN.match(stripped):
        raise InputValidationError(
            field_name, f"'{value}' is not a syntactically valid email address."
        )
    return stripped


def validate_iso8601_datetime(value: str, *, field_name: str = "value") -> datetime:
    """Validate that a string is a timezone-aware ISO-8601 datetime.

    Corresponds to API-ADD Section 22's rule: "a naive (offset-less)
    timestamp is rejected with 422 rather than assumed to be UTC."

    Args:
        value: The candidate ISO-8601 datetime string.
        field_name: The name of the field being validated.

    Returns:
        The parsed, timezone-aware ``datetime``.

    Raises:
        InputValidationError: If ``value`` cannot be parsed as an
            ISO-8601 datetime, or parses successfully but has no UTC
            offset.
    """
    try:
        parsed = parse_iso8601(value)
    except ValueError as exc:
        raise InputValidationError(
            field_name, f"'{value}' is not a valid ISO-8601 datetime."
        ) from exc
    if parsed.tzinfo is None:
        raise InputValidationError(
            field_name,
            f"'{value}' has no UTC offset; naive timestamps are not accepted.",
        )
    return parsed


def validate_positive_integer(value: int, *, field_name: str) -> int:
    """Validate that an integer is strictly positive.

    Matches the shape of several DSD Section 4.1 check constraints
    mirrored at the application boundary (e.g. ``stage_order > 0``,
    ``version > 0``, ``size_bytes > 0``).

    Args:
        value: The candidate integer.
        field_name: The name of the field being validated.

    Returns:
        ``value``, unchanged.

    Raises:
        InputValidationError: If ``value`` is not strictly greater than
            zero.
    """
    if value <= 0:
        raise InputValidationError(field_name, f"must be a positive integer, got {value}.")
    return value


def validate_positive_number(value: float, *, field_name: str) -> float:
    """Validate that a number is strictly positive.

    Used for fields such as a workflow stage's ``escalation_hours`` (WEDD
    Section 3.7), which is a duration and therefore meaningless at zero
    or below.

    Args:
        value: The candidate number.
        field_name: The name of the field being validated.

    Returns:
        ``value``, unchanged.

    Raises:
        InputValidationError: If ``value`` is not strictly greater than
            zero.
    """
    if value <= 0:
        raise InputValidationError(field_name, f"must be a positive number, got {value}.")
    return value
