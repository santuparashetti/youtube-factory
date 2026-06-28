from google import genai
from google.genai import types
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from ytfactory.config.settings import Settings
from ytfactory.domain.llm import LLMResponse
from ytfactory.providers.llm.base import LLMProvider


class GeminiProvider(LLMProvider):
    """Google Gemini implementation."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = genai.Client(api_key=settings.gemini_api_key)

    @retry(
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

        logger.info("Generating response using Gemini")

        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_prompt,
        )

        response = self._client.models.generate_content(
            model=self._settings.gemini_model,
            contents=prompt,
            config=config,
        )

        usage = getattr(response, "usage_metadata", None)

        return LLMResponse(
            text=response.text or "",
            model=self._settings.gemini_model,
            prompt_tokens=getattr(usage, "prompt_token_count", 0),
            completion_tokens=getattr(usage, "candidates_token_count", 0),
            total_tokens=getattr(usage, "total_token_count", 0),
            finish_reason=str(response.candidates[0].finish_reason)
            if response.candidates
            else None,
        )