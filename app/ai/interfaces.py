"""Protocols and value objects for ``app.ai``.

Per this package's design brief, ``AiProvider`` is deliberately the lowest-
level abstraction here: an implementation knows nothing about prompts built
for a specific feature, business data, or persistence — only how to turn one
system/user prompt pair into one completion. This mirrors
``app.notifications.interfaces.EmailProvider``'s own "lowest-level
abstraction in this package" design.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["AiCompletion", "AiProvider"]


@dataclass(frozen=True, slots=True)
class AiCompletion:
    """The result of a single successful ``AiProvider.complete`` call.

    Attributes:
        text: The model's generated text.
        provider_name: A short, stable identifier for the provider that
            produced this completion (e.g. ``"openai"``, ``"anthropic"``).
        model: The specific model identifier used.
    """

    text: str
    provider_name: str
    model: str


@runtime_checkable
class AiProvider(Protocol):
    """Structural interface for the raw text-completion capability.

    This is deliberately the lowest-level abstraction in this package: an
    implementation knows nothing about notification events, requests,
    workflows, or any other domain concept — only how to turn one
    system/user prompt pair into one completion.
    """

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int = 600,
        temperature: float = 0.2,
    ) -> AiCompletion:
        """Generate a single completion for the given prompt.

        Args:
            system_prompt: The system-level instruction framing the
                model's role and constraints for this call.
            user_prompt: The user-level content the model responds to.
            max_output_tokens: An upper bound on the generated response
                length, in provider-defined tokens.
            temperature: The sampling temperature. Callers use a low,
                fixed value (see ``AiInsightService``) since every use of
                this provider is a factual-summary task, not creative
                generation.

        Returns:
            The generated ``AiCompletion``.

        Raises:
            AiProviderError: If the call fails for any reason — invalid
                credentials, a rate limit, a network/timeout failure, or
                an unparsable response — after any internally-applied
                retry is exhausted.
        """
        ...
