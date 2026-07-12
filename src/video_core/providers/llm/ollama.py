"""Ollama LLM provider — local inference, no API key, no limits."""

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


class OllamaProvider(LLMProvider):
    """
    Local inference via Ollama.  Completely free, no API key, no rate limits.

    Install: https://ollama.com/download
    Pull a model first:
        ollama pull llama3.2        # 2GB, fast on CPU
        ollama pull llama3.1:8b     # 5GB, higher quality
        ollama pull mistral         # 4GB, great for structured output

    Set in .env:
        LLM_PROVIDER=ollama
        OLLAMA_MODEL=llama3.2       # or llama3.1:8b, mistral, qwen2.5, etc.
        OLLAMA_BASE_URL=http://localhost:11434   # default
    """

    def __init__(self, settings: SharedSettings):
        self._model = settings.ollama_model
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._session = requests.Session()

    @retry(
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        logger.info("Generating response via Ollama — model: {}", self._model)

        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self._session.post(
                f"{self._base_url}/v1/chat/completions",
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": False,
                },
                timeout=300,  # local inference can be slow on CPU
            )
            response.raise_for_status()
        except requests.ConnectionError as exc:
            raise requests.ConnectionError(
                f"Cannot reach Ollama at {self._base_url}. "
                "Is Ollama running?  Start it with: ollama serve"
            ) from exc

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
