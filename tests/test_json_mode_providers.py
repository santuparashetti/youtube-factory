"""Tests for json_mode / json_schema wiring across LLM providers.

docs/script/task-2.2-retry-engine-reliability.md Phase 1 — structured output
via the response_format API parameter, not prompt-only JSON requests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from video_core.config.shared_settings import SharedSettings
from video_core.providers.llm.deepinfra_provider import DeepInfraProvider
from video_core.providers.llm.openai_provider import OpenAICompatibleProvider

SAMPLE_SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}}


def _mock_openai_response(text: str = "ok"):
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = text
    mock.choices[0].finish_reason = "stop"
    mock.usage.prompt_tokens = 1
    mock.usage.completion_tokens = 1
    mock.usage.total_tokens = 2
    return mock


class TestOpenAICompatibleProviderJsonMode:
    def _provider(self) -> OpenAICompatibleProvider:
        settings = SharedSettings(
            anthropic_base_url="https://example.test/v1",
            anthropic_api_key="key",
            anthropic_model="deepseek/deepseek-v3.2",
        )
        return OpenAICompatibleProvider(settings)

    def test_no_response_format_by_default(self):
        provider = self._provider()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response()
        with patch.object(provider, "_client", mock_client):
            provider.generate("hello")
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "response_format" not in kwargs

    def test_json_mode_sets_json_object_format(self):
        provider = self._provider()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response()
        with patch.object(provider, "_client", mock_client):
            provider.generate("hello", json_mode=True)
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}

    def test_json_schema_sets_strict_schema_format(self):
        provider = self._provider()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response()
        with patch.object(provider, "_client", mock_client):
            provider.generate("hello", json_mode=True, json_schema=SAMPLE_SCHEMA)
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert kwargs["response_format"]["type"] == "json_schema"
        assert kwargs["response_format"]["json_schema"]["schema"] == SAMPLE_SCHEMA
        assert kwargs["response_format"]["json_schema"]["strict"] is True

    def test_json_schema_ignored_without_json_mode(self):
        """json_schema alone (json_mode=False) must not silently enable JSON mode."""
        provider = self._provider()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response()
        with patch.object(provider, "_client", mock_client):
            provider.generate("hello", json_schema=SAMPLE_SCHEMA)
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "response_format" not in kwargs


class TestDeepInfraProviderJsonMode:
    def _provider(self) -> DeepInfraProvider:
        settings = SharedSettings(
            deepinfra_api_key="key",
            deepinfra_model="meta-llama/Llama-3.3-70B-Instruct",
        )
        return DeepInfraProvider(settings)

    def test_json_mode_sets_json_object_format(self):
        provider = self._provider()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response()
        with patch.object(provider, "_client", mock_client):
            provider.generate("hello", json_mode=True)
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}

    def test_no_response_format_by_default(self):
        provider = self._provider()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response()
        with patch.object(provider, "_client", mock_client):
            provider.generate("hello")
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "response_format" not in kwargs
