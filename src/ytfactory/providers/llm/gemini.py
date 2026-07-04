import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ytfactory.config.settings import Settings
from ytfactory.domain.llm import LLMResponse
from ytfactory.providers.llm.base import LLMProvider

_RETRYABLE = (RuntimeError, httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectError)


class GeminiQuotaError(Exception):
    """Raised when the Gemini API daily quota is exhausted (HTTP 429). Not retried."""


class GeminiProvider(LLMProvider):
    """Google Gemini implementation."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = genai.Client(api_key=settings.gemini_api_key)

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
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

        logger.info("Generating response using Gemini")

        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_prompt,
        )

        logger.info(
            "Using Gemini model: {}",
            self._settings.gemini_text_model,
        )

        try:
            response = self._client.models.generate_content(
                model=self._settings.gemini_text_model,
                contents=prompt,
                config=config,
            )
        except genai_errors.ClientError as exc:
            if getattr(exc, "code", None) == 429:
                # Daily quota exhausted — retrying won't help; surface immediately
                raise GeminiQuotaError(
                    f"Gemini daily quota exhausted ({exc}). "
                    "Upgrade to a paid tier or wait until tomorrow."
                ) from exc
            raise RuntimeError(f"Gemini API error: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(
                "Gemini request failed. "
                "The service may be temporarily unavailable."
            ) from exc

        usage = getattr(response, "usage_metadata", None)

        return LLMResponse(
            text=response.text or "",
            model=self._settings.gemini_text_model,
            prompt_tokens=getattr(usage, "prompt_token_count", 0),
            completion_tokens=getattr(usage, "candidates_token_count", 0),
            total_tokens=getattr(usage, "total_token_count", 0),
            finish_reason=str(response.candidates[0].finish_reason)
            if response.candidates
            else None,
        )