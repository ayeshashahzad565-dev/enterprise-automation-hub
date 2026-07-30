"""Domain models for analytics aggregation results.

Per the ADD's Component Breakdown, ``AnalyticsService`` queries
aggregated data and prepares it for visualization with Plotly; the models
here are the validated, structured shapes that aggregation produces,
independent of any chart-rendering concern. These models mirror the shape
of the read-only aggregate results returned by
``app.database.repositories.analytics_repository.AnalyticsRepository``,
expressed here as their own independent Domain Layer representations
rather than importing the persistence layer's dataclasses directly — per
the ADD, the Domain Layer has no dependency on the Repository Layer; the
mapping between the two is the Application Layer's responsibility.
"""

from __future__ import annotations

from pydantic import Field

from app.models.base import EAHBaseModel
from app.models.enums import RequestStatus

__all__ = ["StatusBreakdown", "VolumeByKey", "ApprovalThroughput"]


class StatusBreakdown(EAHBaseModel):
    """A count of requests grouped by lifecycle status.

    Attributes:
        counts: A mapping from each ``RequestStatus`` present in the
            queried population to its count. Statuses with zero matching
            requests are omitted rather than included with a zero count.
        total: The total number of requests counted across all statuses.
    """

    counts: dict[RequestStatus, int]
    total: int = Field(ge=0)


class VolumeByKey(EAHBaseModel):
    """A count of requests grouped by an arbitrary string key (request
    type or department).

    Attributes:
        counts: A mapping from each distinct key value present in the
            queried population to its count.
        total: The total number of requests counted across all keys.
    """

    counts: dict[str, int]
    total: int = Field(ge=0)


class ApprovalThroughput(EAHBaseModel):
    """Aggregate approval-latency and completion-rate figures for a
    population of decided stages/requests.

    Attributes:
        average_decision_seconds: The average number of seconds between a
            stage's creation and its decision, across every decided stage
            considered, or ``None`` if no decided stage was found in the
            queried population.
        completed_count: The number of requests that reached
            ``RequestStatus.COMPLETED``.
        rejected_count: The number of requests that reached
            ``RequestStatus.REJECTED``.
        completion_rate: ``completed_count / (completed_count +
            rejected_count)``, or ``None`` if neither occurred in the
            queried population.
    """

    average_decision_seconds: float | None = Field(default=None, ge=0)
    completed_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    completion_rate: float | None = Field(default=None, ge=0, le=1)
