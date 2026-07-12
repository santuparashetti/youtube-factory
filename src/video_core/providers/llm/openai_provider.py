"""OpenAI-compatible LLM provider — works with LiteLLM proxies, OpenRouter, etc."""

from __future__ import annotations

from loguru import logger
from openai import OpenAI

from video_core.config.shared_settings import SharedSettings
from video_core.domain.llm import LLMResponse
from video_core.providers.llm.base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    """Calls any OpenAI-compatible endpoint (LiteLLM proxy, OpenRouter, etc.)."""

    def __init__(self, settings: SharedSettings):
        self._settings = settings
        self._client = OpenAI(
            base_url=settings.anthropic_base_url,
            api_key=settings.anthropic_api_key,
        )

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        model = self._settings.anthropic_model
        logger.info(
            "Generating response via OpenAI-compatible proxy — model: {}", model
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Reasoning models (DeepSeek, etc.) consume tokens for thinking/reasoning
        # before producing visible output. 8192 is too tight — they burn through
        # it on reasoning alone and return empty content. Bumped to 65536 which
        # gives most models ~32K+ tokens for actual output after reasoning.
        max_tokens = 65536

        response = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        choice = response.choices[0]
        content = choice.message.content
        finish_reason = choice.finish_reason

        text = content or ""

        # Log warnings for truncated / filtered / empty responses
        if finish_reason not in ("stop", None) or not text:
            if not text:
                logger.warning(
                    "LLM returned empty content: model={} finish_reason={} "
                    "completion_tokens={} — try increasing max_tokens or using a "
                    "model with higher output limits",
                    model,
                    finish_reason,
                    response.usage.completion_tokens if response.usage else "?",
                )
            elif finish_reason not in ("stop", None):
                logger.warning(
                    "LLM response finished unexpectedly: model={} finish_reason={} "
                    "completion_tokens={} response_length={}",
                    model,
                    finish_reason,
                    response.usage.completion_tokens if response.usage else "?",
                    len(text),
                )

        usage = response.usage
        return LLMResponse(
            text=text,
            model=model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            finish_reason=finish_reason,
        )
