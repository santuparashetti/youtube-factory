"""DeepInfra LLM provider — native OpenAI-compatible API."""

from __future__ import annotations

import time
from functools import partial

from openai import OpenAI

from loguru import logger
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from video_core.config.shared_settings import SharedSettings
from video_core.domain.llm import LLMResponse
from video_core.providers.llm.base import LLMProvider

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "response_status", None)
    if status is None:
        response = getattr(exc, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)
    return status in _RETRYABLE_STATUS


def _log_retry(rs: object, prov: str, mod: str, max_tries: int) -> None:
    outcome = getattr(rs, "outcome", None)
    exc = outcome.exception() if outcome is not None else None
    logger.warning(
        "DeepInfra LLM retry {attempt} of {max}: provider={provider} model={model} error={error}",
        attempt=getattr(rs, "attempt_number", "?"),
        max=max_tries,
        provider=prov,
        model=mod,
        error=exc,
    )


class DeepInfraProvider(LLMProvider):
    """DeepInfra cloud inference — OpenAI-compatible API."""

    def __init__(self, settings: SharedSettings):
        self._settings = settings
        if not settings.deepinfra_api_key:
            raise ValueError(
                "DEEPINFRA_API_KEY is not set. Add it to your .env file."
            )
        if not settings.deepinfra_model:
            raise ValueError(
                "DEEPINFRA_MODEL is not set. Add it to your .env file."
            )
        self._client = OpenAI(
            api_key=settings.deepinfra_api_key,
            base_url=settings.deepinfra_base_url,
            timeout=settings.deepinfra_timeout,
        )
        self._max_retries = settings.deepinfra_max_retries

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        model = self._settings.deepinfra_model
        logger.info(
            "Generating response via DeepInfra provider=deepinfra model={model}",
            model=model,
        )

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        retryer = Retrying(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            reraise=True,
            before_sleep=partial(
                _log_retry, prov="deepinfra", mod=model, max_tries=self._max_retries
            ),
        )

        def _call() -> LLMResponse:
            start = time.perf_counter()
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                )
            except Exception as exc:
                logger.error(
                    "DeepInfra LLM request failed: provider=deepinfra model={model} error={error}",
                    model=model,
                    error=exc,
                )
                raise

            latency = time.perf_counter() - start

            choice = response.choices[0]
            content = choice.message.content
            finish_reason = choice.finish_reason
            text = content or ""

            usage = response.usage
            prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
            total_tokens = getattr(usage, "total_tokens", 0) if usage else 0

            logger.info(
                "DeepInfra response received provider=deepinfra model={model} "
                "latency={latency:.2f}s prompt_tokens={prompt_tokens} "
                "completion_tokens={completion_tokens} total_tokens={total_tokens} "
                "finish_reason={finish_reason}",
                model=model,
                latency=latency,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                finish_reason=finish_reason,
            )

            if finish_reason not in ("stop", None) or not text:
                if not text:
                    logger.warning(
                        "DeepInfra LLM returned empty content: model={} finish_reason={} "
                        "completion_tokens={}",
                        model,
                        finish_reason,
                        completion_tokens,
                    )
                else:
                    logger.warning(
                        "DeepInfra LLM response finished unexpectedly: model={} finish_reason={} "
                        "completion_tokens={} response_length={}",
                        model,
                        finish_reason,
                        completion_tokens,
                        len(text),
                    )

            return LLMResponse(
                text=text,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                finish_reason=finish_reason,
            )

        return retryer(_call)
