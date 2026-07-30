"""Anthropic-backed ``AiProvider`` implementation.

Talks to the Anthropic Messages REST API directly via ``httpx`` — no
``anthropic`` SDK dependency is introduced.
"""

from __future__ import annotations

import logging

import httpx

from app.ai.exceptions import AiConfigurationError, AiProviderError
from app.ai.interfaces import AiCompletion
from app.utils.retry import RetryPolicy, retry_call

__all__ = ["AnthropicProvider"]

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
_ANTHROPIC_API_VERSION = "2023-06-01"

_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class _RetryableStatusError(Exception):
    """Internal signal that a response's status code warrants a retry."""


class AnthropicProvider:
    """An ``AiProvider`` implementation backed by the Anthropic Messages API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        base_url: str = _DEFAULT_BASE_URL,
        retry_policy: RetryPolicy | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Initialize the provider with injected configuration.

        Args:
            api_key: The Anthropic API key. Never hardcoded — sourced
                from ``app.config.settings.AiSettings.api_key``.
            model: The model identifier to request (e.g. an operator-
                configured ``AI_MODEL`` value).
            timeout_seconds: The request timeout applied to every call.
            base_url: The API base URL, overridable for testing.
            retry_policy: The retry policy governing transient-failure
                retries. Defaults to a policy scoped to network-level and
                ``_RETRYABLE_STATUS_CODES`` failures only.
            transport: An ``httpx`` transport override, for tests
                (``httpx.MockTransport``) — never set in production.

        Raises:
            AiConfigurationError: If ``api_key`` or ``model`` is blank.
        """
        if not api_key.strip():
            raise AiConfigurationError("Cannot construct an AnthropicProvider: api_key is blank.")
        if not model.strip():
            raise AiConfigurationError("Cannot construct an AnthropicProvider: model is blank.")

        self._model = model
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            headers={
                "x-api-key": api_key,
                "anthropic-version": _ANTHROPIC_API_VERSION,
                "Content-Type": "application/json",
            },
            transport=transport,
        )
        self._retry_policy = retry_policy or RetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.5,
            backoff_multiplier=2.0,
            max_delay_seconds=5.0,
            jitter=True,
            retryable_exceptions=(*_RETRYABLE_EXCEPTIONS, _RetryableStatusError),
        )
        self._logger = logging.getLogger(f"{__name__}.AnthropicProvider")

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int = 600,
        temperature: float = 0.2,
    ) -> AiCompletion:
        """Generate a single completion via the Anthropic Messages API.

        Raises:
            AiProviderError: If the call fails after any configured retry
                is exhausted, or the response cannot be parsed.
        """
        payload = {
            "model": self._model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": max_output_tokens,
            "temperature": temperature,
        }

        try:
            response = retry_call(
                lambda: self._post_once(payload), policy=self._retry_policy
            )
        except Exception as exc:  # noqa: BLE001 - translated into a typed error below
            self._logger.warning("Anthropic completion request failed: %s", exc, exc_info=exc)
            raise AiProviderError("anthropic", str(exc)) from exc

        try:
            body = response.json()
            text = body["content"][0]["text"]
        except (KeyError, IndexError, ValueError) as exc:
            raise AiProviderError("anthropic", f"unparsable response: {exc}") from exc

        return AiCompletion(text=text, provider_name="anthropic", model=self._model)

    def _post_once(self, payload: dict) -> httpx.Response:
        """Perform a single completion request attempt.

        Raises:
            _RetryableStatusError: If the response's status code is in
                ``_RETRYABLE_STATUS_CODES``.
            httpx.HTTPStatusError: If the response is a non-retryable
                error status.
        """
        response = self._client.post("/messages", json=payload)
        if response.status_code in _RETRYABLE_STATUS_CODES:
            raise _RetryableStatusError(f"HTTP {response.status_code}: {response.text[:200]}")
        response.raise_for_status()
        return response
