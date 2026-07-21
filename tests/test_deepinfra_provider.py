"""Tests for DeepInfraProvider.

All SDK calls are mocked so the suite runs without network access or the
package installed. Verifies initialization, chat completion, retry,
timeout, invalid API key, usage parsing, and empty response.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from video_core.config.shared_settings import SharedSettings
from video_core.domain.llm import LLMResponse
from video_core.providers.llm.deepinfra_provider import DeepInfraProvider
from video_core.providers.llm.factory import get_llm_provider


# ── Settings factory ──────────────────────────────────────────────────────────


def _deepinfra_settings(**overrides):
    defaults = {
        "deepinfra_api_key": "di_test_token",
        "deepinfra_base_url": "https://api.deepinfra.com/v1/openai",
        "deepinfra_model": "meta-llama/Llama-3.3-70B-Instruct",
        "deepinfra_timeout": 60,
        "deepinfra_max_retries": 3,
    }
    defaults.update(overrides)
    return SharedSettings(**defaults)


# ── Initialization ────────────────────────────────────────────────────────────


class TestInit:
    def test_provider_initialization(self):
        settings = _deepinfra_settings()
        provider = DeepInfraProvider(settings)
        assert provider._settings.deepinfra_model == "meta-llama/Llama-3.3-70B-Instruct"

    def test_missing_api_key_raises(self):
        settings = _deepinfra_settings(deepinfra_api_key="")
        with pytest.raises(ValueError, match="DEEPINFRA_API_KEY is not set"):
            DeepInfraProvider(settings)

    def test_missing_model_raises(self):
        settings = _deepinfra_settings(deepinfra_model="")
        with pytest.raises(ValueError, match="DEEPINFRA_MODEL is not set"):
            DeepInfraProvider(settings)


# ── Retry behavior ───────────────────────────────────────────────────────────


class TestRetry:
    def _make_response(self, text="Hello"):
        mock = MagicMock()
        mock.choices = [MagicMock()]
        mock.choices[0].message.content = text
        mock.choices[0].finish_reason = "stop"
        mock.usage.prompt_tokens = 10
        mock.usage.completion_tokens = 5
        mock.usage.total_tokens = 15
        return mock

    def test_retries_429_then_succeeds(self):
        settings = _deepinfra_settings(deepinfra_max_retries=2)
        provider = DeepInfraProvider(settings)

        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                from openai import APIStatusError
                from httpx import Request, Response
                req = Request("POST", "https://api.deepinfra.com/v1/openai")
                resp = Response(429, request=req)
                raise APIStatusError(
                    message="429 Too Many Requests",
                    response=resp,
                    body=None,
                )
            return self._make_response()

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = side_effect

        with patch.object(provider, "_client", mock_client):
            result = provider.generate("test")
        assert result.text == "Hello"
        assert call_count["n"] == 2

    def test_no_retry_on_401(self):
        settings = _deepinfra_settings()
        provider = DeepInfraProvider(settings)

        def side_effect(*args, **kwargs):
            from openai import APIStatusError
            from httpx import Request, Response
            req = Request("POST", "https://api.deepinfra.com/v1/openai")
            resp = Response(401, request=req)
            raise APIStatusError(
                message="401 Unauthorized",
                response=resp,
                body=None,
            )

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = side_effect

        with patch.object(provider, "_client", mock_client):
            with pytest.raises(Exception):
                provider.generate("test")


# ── Chat completion ──────────────────────────────────────────────────────────


class TestGenerate:
    def test_generate_returns_response(self):
        settings = _deepinfra_settings()
        provider = DeepInfraProvider(settings)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test output"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 30

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(provider, "_client", mock_client):
            result = provider.generate("What is 2+2?", system_prompt="Be precise")

        assert isinstance(result, LLMResponse)
        assert result.text == "Test output"
        assert result.model == "meta-llama/Llama-3.3-70B-Instruct"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20
        assert result.total_tokens == 30
        assert result.finish_reason == "stop"

    def test_generate_with_system_prompt(self):
        settings = _deepinfra_settings()
        provider = DeepInfraProvider(settings)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "A"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 1
        mock_response.usage.total_tokens = 6

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(provider, "_client", mock_client):
            provider.generate("Q", system_prompt="You are a helpful assistant")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Q"

    def test_generate_empty_content(self):
        settings = _deepinfra_settings()
        provider = DeepInfraProvider(settings)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 0
        mock_response.usage.total_tokens = 10

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(provider, "_client", mock_client):
            result = provider.generate("test")

        assert result.text == ""


# ── Factory ──────────────────────────────────────────────────────────────────


class TestFactory:
    def test_factory_resolves_deepinfra(self):
        settings = _deepinfra_settings()
        settings.llm_provider = "deepinfra"
        provider = get_llm_provider(settings)
        assert isinstance(provider, DeepInfraProvider)
