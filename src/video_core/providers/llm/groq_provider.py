"""Groq LLM provider — free cloud inference, 14 400 req/day on free tier."""

from __future__ import annotations

import requests
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from video_core.config.shared_settings import SharedSettings
from video_core.domain.llm import LLMResponse

from .base import LLMProvider

_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(LLMProvider):
    """
    Groq cloud inference — OpenAI-compatible API, free tier.
    Get a free API key at https://console.groq.com/
    Default model: llama-3.3-70b-versatile (best free option, 128k context).
    """

    def __init__(self, settings: SharedSettings):
        self._model = settings.groq_model
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            }
        )

    @retry(
        retry=retry_if_exception_type(
            (requests.HTTPError, requests.ConnectionError, requests.Timeout)
        ),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=5, max=30),
        reraise=True,
    )
    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        logger.info("Generating response via Groq — model: {}", self._model)

        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self._session.post(
            _API_URL,
            json={
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
            },
            timeout=120,
        )

        if response.status_code == 429:
            retry_after = int(response.headers.get("retry-after", 30))
            logger.warning(
                "Groq TPM rate limit — waiting {}s before retry "
                "(tip: set GROQ_MODEL=llama-3.1-8b-instant for 22× higher limit)",
                retry_after,
            )
            import time

            for remaining in range(retry_after, 0, -10):
                logger.info("Rate limit cooldown — {}s remaining...", remaining)
                time.sleep(min(10, remaining))
            response = self._session.post(
                _API_URL,
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": temperature,
                },
                timeout=120,
            )

        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return LLMResponse(
            text=choice["message"]["content"] or "",
            model=self._model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            finish_reason=choice.get("finish_reason"),
        )
