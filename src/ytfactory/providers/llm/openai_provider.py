"""OpenAI-compatible LLM provider — works with LiteLLM proxies, OpenRouter, etc."""

from __future__ import annotations

from loguru import logger
from openai import OpenAI

from ytfactory.config.settings import Settings
from ytfactory.domain.llm import LLMResponse
from ytfactory.providers.llm.base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    """Calls any OpenAI-compatible endpoint (LiteLLM proxy, OpenRouter, etc.)."""

    def __init__(self, settings: Settings):
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
        logger.info("Generating response via OpenAI-compatible proxy — model: {}", model)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=8192,
        )

        usage = response.usage
        return LLMResponse(
            text=response.choices[0].message.content or "",
            model=model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            finish_reason=response.choices[0].finish_reason,
        )
