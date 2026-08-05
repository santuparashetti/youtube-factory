"""OpenAI-compatible LLM provider — works with LiteLLM proxies, OpenRouter, etc."""

from __future__ import annotations

from typing import Optional

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
            timeout=120.0,
        )

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        json_mode: bool = False,
        json_schema: dict | None = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        model = model or self._settings.anthropic_model
        logger.info(
            "Generating response via OpenAI-compatible proxy — model: {} json_mode={}",
            model,
            json_mode,
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Reasoning models (DeepSeek, etc.) consume tokens for thinking/reasoning
        # before producing visible output. 8192 is too tight — they burn through
        # it on reasoning alone and return empty content. 65536 gives most models
        # ~32K+ tokens for actual output after reasoning. Callers generating
        # open-ended long text (e.g. recomposer) can override with max_tokens.
        effective_max_tokens = max_tokens or 65536

        request_params: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
        }

        if json_mode:
            if json_schema:
                # Strict structured output — not all OpenAI-compatible endpoints
                # (e.g. DeepSeek V3 via OpenRouter) support this. Callers that need
                # a guaranteed fallback should catch and retry with json_schema=None.
                request_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "scene_retry_response",
                        "strict": True,
                        "schema": json_schema,
                    },
                }
            else:
                # Loose JSON mode — guarantees syntactically valid JSON, not schema.
                request_params["response_format"] = {"type": "json_object"}

        try:
            response = self._client.chat.completions.create(**request_params)
        except Exception as e:
            # The OpenAI SDK raises before we can inspect the raw HTTP response,
            # but the exception message usually contains the status code and body.
            logger.error(
                "Provider API call failed — model={} error={}: {}",
                model,
                type(e).__name__,
                str(e)[:500],
            )
            raise

        if not response.choices:
            logger.error(
                "LLM returned no choices — model={} usage={}",
                model,
                response.usage,
            )
            raise RuntimeError(f"LLM returned no choices for model={model!r}")

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
