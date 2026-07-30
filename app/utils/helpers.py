"""Small, general-purpose helper functions that do not warrant their own module.

Every function here is a pure, generic utility with no dependency on any
domain concept from ``app.models``, any persistence concern from
``app.database``, or any configuration value from ``app.config`` — the
kind of small helper that would otherwise be reimplemented ad hoc at
several call sites across the codebase (batching an iterable for the
Scheduler's batch processing, per WEDD Section 8.3; picking the first
non-``None`` value among several candidates; safely truncating a string
for a log message).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import Any, TypeVar

__all__ = ["chunked", "coalesce", "deep_get", "truncate_string", "first_or_default"]

T = TypeVar("T")


def chunked(items: Iterable[T], size: int) -> Iterator[list[T]]:
    """Split an iterable into consecutive chunks of at most ``size`` items.

    Useful for batch-processing a large result set (for example, the
    Scheduler's Escalation Check job iterating over a batch of overdue
    stages, per WEDD Section 8.3) without loading a chunking strategy's
    logic into the calling code itself.

    Args:
        items: The iterable to split. Consumed lazily, one chunk at a
            time.
        size: The maximum number of items per chunk. Must be positive.

    Yields:
        Successive lists of up to ``size`` items each, in original order.
        The final chunk may contain fewer than ``size`` items if the
        total count is not an exact multiple of ``size``.

    Raises:
        ValueError: If ``size`` is not positive.
    """
    if size <= 0:
        raise ValueError(f"size must be positive, got {size}.")
    chunk: list[T] = []
    for item in items:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def coalesce(*values: T | None) -> T | None:
    """Return the first non-``None`` value among the given arguments.

    Args:
        *values: The candidate values, evaluated in order.

    Returns:
        The first value that is not ``None``, or ``None`` if every
        argument was ``None`` (including if no arguments were given at
        all).
    """
    for value in values:
        if value is not None:
            return value
    return None


def deep_get(source: dict[str, Any], path: Sequence[str], default: Any = None) -> Any:
    """Safely retrieve a nested value from a dict by a sequence of keys.

    Useful when reading an optional, nested field from a loosely
    structured payload (for example, a workflow definition's JSON
    document, DSD Section 5.2) without a chain of ``.get(...)`` calls
    that must each separately guard against an intermediate value being
    absent or not itself a dict.

    Args:
        source: The dict to read from.
        path: The sequence of keys to traverse, in order.
        default: The value to return if any key in ``path`` is missing,
            or if traversal encounters a non-dict value before ``path``
            is exhausted.

    Returns:
        The value found at the end of ``path``, or ``default``.
    """
    current: Any = source
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def truncate_string(value: str, *, max_length: int, suffix: str = "...") -> str:
    """Truncate a string to a maximum length, appending a suffix if truncated.

    Useful for safely including a potentially long, user-supplied value
    (a comment body, a decision note) in a log message without letting a
    single value dominate the log line.

    Args:
        value: The string to truncate.
        max_length: The maximum total length of the returned string,
            including ``suffix``. Must be at least as long as ``suffix``.
        suffix: The marker appended when truncation occurs. Defaults to
            ``"..."``.

    Returns:
        ``value`` unchanged if its length is already at most
        ``max_length``; otherwise a truncated prefix of ``value`` with
        ``suffix`` appended, such that the total length equals
        ``max_length``.

    Raises:
        ValueError: If ``max_length`` is shorter than ``suffix``.
    """
    if max_length < len(suffix):
        raise ValueError(
            f"max_length ({max_length}) must be at least as long as suffix ({len(suffix)})."
        )
    if len(value) <= max_length:
        return value
    return value[: max_length - len(suffix)] + suffix


def first_or_default(items: Iterable[T], default: T | None = None) -> T | None:
    """Return the first item of an iterable, or a default if it is empty.

    Args:
        items: The iterable to inspect.
        default: The value to return if ``items`` yields no elements.

    Returns:
        The first item, or ``default``.
    """
    for item in items:
        return item
    return default
