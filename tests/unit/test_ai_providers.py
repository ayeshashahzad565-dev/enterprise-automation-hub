"""Unit tests for ``app.ai.providers`` (``OpenAiProvider``, ``AnthropicProvider``).

Every HTTP call is intercepted via ``httpx.MockTransport`` — no real network
access occurs. Retry-exhaustion tests patch ``app.utils.retry.time.sleep`` to
a no-op so they run instantly despite the providers' real backoff policy.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.ai.exceptions import AiConfigurationError, AiProviderError
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.openai_provider import OpenAiProvider

pytestmark = pytest.mark.unit


def _openai_response(text: str = "Hello from OpenAI.") -> dict:
    return {"choices": [{"message": {"content": text}}]}


def _anthropic_response(text: str = "Hello from Anthropic.") -> dict:
    return {"content": [{"text": text}]}


def _transport_returning(status_code: int, body: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    return httpx.MockTransport(handler)


def _counting_transport(status_code: int, body: dict) -> tuple[httpx.MockTransport, list[int]]:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status_code, json=body)

    return httpx.MockTransport(handler), calls


class TestOpenAiProvider:
    def test_blank_api_key_raises_configuration_error(self) -> None:
        with pytest.raises(AiConfigurationError):
            OpenAiProvider(api_key="   ", model="gpt-test", timeout_seconds=5.0)

    def test_blank_model_raises_configuration_error(self) -> None:
        with pytest.raises(AiConfigurationError):
            OpenAiProvider(api_key="sk-test", model="  ", timeout_seconds=5.0)

    def test_successful_completion_returns_parsed_text(self) -> None:
        transport = _transport_returning(200, _openai_response("The summary."))
        provider = OpenAiProvider(
            api_key="sk-test", model="gpt-test", timeout_seconds=5.0, transport=transport
        )

        completion = provider.complete(system_prompt="sys", user_prompt="user")

        assert completion.text == "The summary."
        assert completion.provider_name == "openai"
        assert completion.model == "gpt-test"

    def test_unparsable_response_raises_provider_error(self) -> None:
        transport = _transport_returning(200, {"unexpected": "shape"})
        provider = OpenAiProvider(
            api_key="sk-test", model="gpt-test", timeout_seconds=5.0, transport=transport
        )

        with pytest.raises(AiProviderError):
            provider.complete(system_prompt="sys", user_prompt="user")

    def test_non_retryable_status_fails_without_retry(self) -> None:
        transport, calls = _counting_transport(401, {"error": "unauthorized"})
        provider = OpenAiProvider(
            api_key="sk-test", model="gpt-test", timeout_seconds=5.0, transport=transport
        )

        with pytest.raises(AiProviderError):
            provider.complete(system_prompt="sys", user_prompt="user")
        assert len(calls) == 1

    def test_retryable_status_exhausts_retries_then_raises(self) -> None:
        transport, calls = _counting_transport(503, {"error": "unavailable"})
        provider = OpenAiProvider(
            api_key="sk-test", model="gpt-test", timeout_seconds=5.0, transport=transport
        )

        with patch("app.utils.retry.time.sleep"), pytest.raises(AiProviderError):
            provider.complete(system_prompt="sys", user_prompt="user")
        assert len(calls) == 3  # default retry policy: 3 total attempts


class TestAnthropicProvider:
    def test_blank_api_key_raises_configuration_error(self) -> None:
        with pytest.raises(AiConfigurationError):
            AnthropicProvider(api_key=" ", model="claude-test", timeout_seconds=5.0)

    def test_blank_model_raises_configuration_error(self) -> None:
        with pytest.raises(AiConfigurationError):
            AnthropicProvider(api_key="sk-ant-test", model="", timeout_seconds=5.0)

    def test_successful_completion_returns_parsed_text(self) -> None:
        transport = _transport_returning(200, _anthropic_response("The summary."))
        provider = AnthropicProvider(
            api_key="sk-ant-test", model="claude-test", timeout_seconds=5.0, transport=transport
        )

        completion = provider.complete(system_prompt="sys", user_prompt="user")

        assert completion.text == "The summary."
        assert completion.provider_name == "anthropic"
        assert completion.model == "claude-test"

    def test_unparsable_response_raises_provider_error(self) -> None:
        transport = _transport_returning(200, {"unexpected": "shape"})
        provider = AnthropicProvider(
            api_key="sk-ant-test", model="claude-test", timeout_seconds=5.0, transport=transport
        )

        with pytest.raises(AiProviderError):
            provider.complete(system_prompt="sys", user_prompt="user")

    def test_non_retryable_status_fails_without_retry(self) -> None:
        transport, calls = _counting_transport(401, {"error": "unauthorized"})
        provider = AnthropicProvider(
            api_key="sk-ant-test", model="claude-test", timeout_seconds=5.0, transport=transport
        )

        with pytest.raises(AiProviderError):
            provider.complete(system_prompt="sys", user_prompt="user")
        assert len(calls) == 1

    def test_retryable_status_exhausts_retries_then_raises(self) -> None:
        transport, calls = _counting_transport(503, {"error": "unavailable"})
        provider = AnthropicProvider(
            api_key="sk-ant-test", model="claude-test", timeout_seconds=5.0, transport=transport
        )

        with patch("app.utils.retry.time.sleep"), pytest.raises(AiProviderError):
            provider.complete(system_prompt="sys", user_prompt="user")
        assert len(calls) == 3
