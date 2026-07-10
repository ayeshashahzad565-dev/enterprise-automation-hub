"""Timezone-aware datetime utilities.

Per API-ADD Section 8, every timestamp in the system is ISO-8601, UTC,
with an explicit offset — never a naive (timezone-unaware) value silently
assumed to be in some particular timezone. This module centralizes the
handful of pure datetime operations every other layer of the application
needs (formatting, parsing, comparison, and simple arithmetic such as
computing an escalation threshold, per WEDD Section 8.2), so that the
"always timezone-aware, always UTC" discipline is enforced in one place
rather than re-derived at every call site.

This module performs no I/O and holds no state; every function is a pure
transformation of its input.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

__all__ = [
    "utc_now",
    "ensure_timezone_aware",
    "to_utc",
    "format_iso8601",
    "parse_iso8601",
    "add_hours",
    "is_past",
    "seconds_between",
]


def utc_now() -> datetime:
    """Return the current instant as a timezone-aware UTC datetime.

    This is the sole recommended way to obtain "now" anywhere in the
    codebase, rather than calling ``datetime.now()`` directly, since the
    latter returns a naive datetime unless a timezone is explicitly
    supplied every time.

    Returns:
        The current UTC datetime, with ``tzinfo`` set.
    """
    return datetime.now(timezone.utc)


def ensure_timezone_aware(value: datetime) -> datetime:
    """Guarantee a datetime carries timezone information.

    A naive datetime (one with ``tzinfo is None``) is assumed to already
    represent UTC and is given that timezone explicitly, rather than
    being silently reinterpreted as local time. A datetime that already
    carries timezone information is returned unchanged.

    Args:
        value: The datetime to normalize.

    Returns:
        A timezone-aware datetime, equal to ``value`` if it was already
        aware, or ``value`` with UTC attached if it was naive.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def to_utc(value: datetime) -> datetime:
    """Convert a datetime to UTC, treating a naive input as already UTC.

    Args:
        value: The datetime to convert.

    Returns:
        The equivalent datetime with ``tzinfo`` set to UTC.
    """
    return ensure_timezone_aware(value).astimezone(timezone.utc)


def format_iso8601(value: datetime) -> str:
    """Format a datetime as an ISO-8601 string in UTC with a 'Z' suffix.

    Matches the timestamp convention fixed throughout the API Design
    Document (API-ADD Section 8) exactly, e.g. ``"2026-07-08T14:32:00Z"``.

    Args:
        value: The datetime to format.

    Returns:
        The ISO-8601, UTC, 'Z'-suffixed string representation.
    """
    return to_utc(value).isoformat().replace("+00:00", "Z")


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO-8601 datetime string.

    A trailing ``'Z'`` is treated as equivalent to ``'+00:00'``. This
    function does not itself reject a naive result (a string with no
    offset at all parses successfully into a naive datetime) — callers
    that must enforce API-ADD Section 22's "no naive timestamps" rule
    should use ``app.utils.validators.validate_iso8601_datetime``, which
    wraps this function and adds that check.

    Args:
        value: The ISO-8601 string to parse.

    Returns:
        The parsed datetime, timezone-aware if ``value`` included an
        offset, naive otherwise.

    Raises:
        ValueError: If ``value`` is not a valid ISO-8601 datetime string.
    """
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))


def add_hours(value: datetime, hours: float) -> datetime:
    """Return a new datetime offset from ``value`` by a number of hours.

    Used, for example, to compute a workflow stage's escalation threshold
    from its ``created_at`` plus the workflow definition's configured
    ``escalation_hours`` (WEDD Section 8.2).

    Args:
        value: The base datetime.
        hours: The number of hours to add. May be negative to compute an
            earlier datetime.

    Returns:
        ``value + timedelta(hours=hours)``, preserving whatever
        timezone-awareness ``value`` already had.
    """
    return value + timedelta(hours=hours)


def is_past(value: datetime, *, reference: datetime | None = None) -> bool:
    """Return whether a datetime is strictly earlier than a reference point.

    Args:
        value: The datetime to test.
        reference: The point in time to compare against. Defaults to
            ``utc_now()`` when not provided.

    Returns:
        ``True`` if ``value`` is earlier than ``reference``.
    """
    comparison_point = reference if reference is not None else utc_now()
    return ensure_timezone_aware(value) < ensure_timezone_aware(comparison_point)


def seconds_between(start: datetime, end: datetime) -> float:
    """Return the number of seconds elapsed between two datetimes.

    Args:
        start: The earlier datetime.
        end: The later datetime.

    Returns:
        ``(end - start).total_seconds()``, computed after normalizing
        both inputs to timezone-aware values so that comparing a naive
        and an aware datetime never raises.
    """
    return (ensure_timezone_aware(end) - ensure_timezone_aware(start)).total_seconds()