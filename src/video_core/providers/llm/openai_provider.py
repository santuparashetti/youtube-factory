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

        # Global defaults from settings (0 = use hardcoded fallback).
        settings_temp = getattr(self._settings, "llm_temperature", 0.0)
        settings_max_tokens = getattr(self._settings, "llm_max_output_tokens", 0)

        effective_temp = settings_temp if settings_temp > 0 else temperature
        # Reasoning models (DeepSeek, etc.) consume tokens for thinking/reasoning
        # before producing visible output. 65536 gives most models ~32K+ tokens
        # for actual output after reasoning.
        effective_max_tokens = max_tokens or settings_max_tokens or 65536

        request_params: dict = {
            "model": model,
            "messages": messages,
            "temperature": effective_temp,
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

        # openrouter_provider = getattr(self._settings, "openrouter_provider", "")
        # if openrouter_provider:
        #     provider_order = [
        #         p.strip() for p in openrouter_provider.split(",") if p.strip()
        #     ]
        #     allow_fallbacks = getattr(
        #         self._settings, "openrouter_allow_fallbacks", True
        #     )
        #     request_params["extra_body"] = {
        #         "provider": {
        #             "order": provider_order,
        #             "allow_fallbacks": allow_fallbacks,
        #         },
        #     }
        openrouter_provider = getattr(self._settings, "openrouter_provider", None)
        if (
            openrouter_provider
            and model.startswith("openai/")
        ):
            provider_order = [
                p.strip()
                for p in openrouter_provider.split(",")
                if p.strip()
            ]

            allow_fallbacks = getattr(
                self._settings,
                "openrouter_allow_fallbacks",
                True,
            )

            request_params["extra_body"] = {
                "provider": {
                    "order": provider_order,
                    "allow_fallbacks": allow_fallbacks,
                }
            }

        import json as _json
        import time as _time

        _max_retries = getattr(self._settings, "llm_max_retries", 3)
        response = None
        for _attempt in range(1, _max_retries + 1):
            try:
                response = self._client.chat.completions.create(**request_params)
            except _json.JSONDecodeError as e:
                logger.warning(
                    "Provider returned non-JSON response (attempt {}/{}) — model={} error={}",
                    _attempt, _max_retries, model, str(e)[:200],
                )
                if _attempt < _max_retries:
                    _time.sleep(2 ** _attempt)
                    continue
                raise RuntimeError(
                    f"Provider returned non-JSON response after {_max_retries} retries "
                    f"(model={model!r}). The API may be temporarily unavailable."
                ) from e
            except Exception as e:
                from openai import RateLimitError as _RateLimitError
                if isinstance(e, _RateLimitError) and _attempt < _max_retries:
                    delay = 5.0 * (2 ** (_attempt - 1))  # 5s, 10s, 20s …
                    logger.warning(
                        "RateLimitError (attempt {}/{}) — model={} retrying in {:.0f}s",
                        _attempt, _max_retries, model, delay,
                    )
                    _time.sleep(delay)
                    continue
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

            if not content:
                logger.warning(
                    "Provider returned empty content "
                    "(attempt {}/{}) — model={} finish_reason={} completion_tokens={}",
                    _attempt, _max_retries, model,
                    finish_reason,
                    response.usage.completion_tokens if response.usage else "?",
                )
                if _attempt < _max_retries:
                    _time.sleep(2 ** _attempt)
                    continue

            break

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
            cost_usd=float(getattr(usage, "cost", 0.0) or 0.0),
        )
