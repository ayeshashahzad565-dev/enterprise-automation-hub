"""Custom exception hierarchy for the app.analytics package.

Mirroring the pattern established in every finalized package, every
exception this package can raise is defined here, exactly once.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class AnalyticsError(Exception):
    """Base class for every exception raised by the app.analytics package.

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


class MetricCalculationError(AnalyticsError):
    """Raised when a single metric cannot be computed — most commonly
    because the underlying repository query it depends on failed.
    """


class AggregationError(AnalyticsError):
    """Raised when grouping or bucketing a dataset (by department, by
    request type, by time period, etc.) cannot be completed.
    """


class ReportingError(AnalyticsError):
    """Raised when a structured report DTO cannot be assembled, most
    commonly because a metric or aggregation it depends on failed.
    """


class InvalidTimeRangeError(AnalyticsError):
    """Raised when a caller-supplied date range is internally inconsistent.

    Attributes:
        created_after: The supplied lower bound.
        created_before: The supplied upper bound.
    """

    def __init__(self, created_after: datetime, created_before: datetime) -> None:
        super().__init__(
            f"created_after ({created_after.isoformat()}) must not be later than "
            f"created_before ({created_before.isoformat()})."
        )
        self.created_after = created_after
        self.created_before = created_before


def validate_date_range(created_after: datetime | None, created_before: datetime | None) -> None:
    """Validate that a caller-supplied date range is internally consistent.

    Shared by every engine in this package that accepts an optional
    ``created_after``/``created_before`` pair (``AnalyticsEngine``,
    ``OperationalAnalyticsEngine``), so this one rule is expressed exactly
    once rather than re-derived per engine.

    Args:
        created_after: The lower bound, if provided.
        created_before: The upper bound, if provided.

    Raises:
        InvalidTimeRangeError: If both bounds are provided and
            ``created_after`` is later than ``created_before``.
    """
    if created_after is not None and created_before is not None and created_after > created_before:
        raise InvalidTimeRangeError(created_after, created_before)
