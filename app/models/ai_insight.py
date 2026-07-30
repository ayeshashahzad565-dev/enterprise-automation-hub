"""Domain model for AI-generated insight content.

Corresponds to the output of every ``app.services.ai_insight_service.AiInsightService``
method — not a persisted row (AI output is cached, never written to a
table; see that service's module docstring), so this model extends
``EAHBaseModel`` directly rather than ``IdentifiedModel``/``TimestampedModel``.
"""

from __future__ import annotations

from app.models.base import EAHBaseModel, UTCDatetime

__all__ = ["AiInsight"]


class AiInsight(EAHBaseModel):
    """A single piece of AI-generated (or gracefully-degraded) insight text.

    Attributes:
        text: The generated content — either the AI provider's response,
            or, when unavailable, a deterministic non-AI fallback built
            from the same underlying data (see ``AiInsightService``).
        generated_by: A short identifier of the provider and model that
            produced ``text`` (e.g. ``"openai:gpt-4o-mini"``), or ``None``
            when ``is_fallback`` is ``True`` — fallback content is never
            attributed to a model that did not generate it.
        is_fallback: Whether ``text`` is the deterministic non-AI fallback
            (no provider configured, or the provider call failed) rather
            than genuine AI output. The Presentation Layer is expected to
            render this distinction visibly rather than presenting
            fallback content as if it were AI-generated.
        cached: Whether ``text`` was served from cache rather than
            computed for this call.
        generated_at: When this insight was produced (cache population
            time for a cache hit, not the time of the current call).
    """

    text: str
    generated_by: str | None = None
    is_fallback: bool
    cached: bool
    generated_at: UTCDatetime
