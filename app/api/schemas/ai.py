"""HTTP schemas for the ``ai`` resource (AI-generated insights)."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from app.models.base import EAHBaseModel, UTCDatetime

__all__ = ["AiInsightOut", "AiChatTurnIn", "AskAssistantBody"]


class AiInsightOut(EAHBaseModel):
    """Wraps ``app.models.ai_insight.AiInsight``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    text: str
    generated_by: str | None
    is_fallback: bool
    cached: bool
    generated_at: UTCDatetime


class AiChatTurnIn(EAHBaseModel):
    """One prior turn in a conversation, supplied by the client.

    Per ``AiInsightService.ask_assistant``'s documented scope decision,
    conversation history is not persisted server-side — the client resends
    it on every call.
    """

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class AskAssistantBody(EAHBaseModel):
    """Body for ``POST /ai/assistant/ask``."""

    question: str = Field(min_length=1, max_length=1000)
    history: list[AiChatTurnIn] = Field(default_factory=list)
