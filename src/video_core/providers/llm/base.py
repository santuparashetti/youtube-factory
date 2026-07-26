from abc import ABC, abstractmethod

from video_core.domain.llm import LLMResponse


class LLMProvider(ABC):
    """Base interface for all LLM providers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        json_mode: bool = False,
        json_schema: dict | None = None,
    ) -> LLMResponse:
        """Generate text from an LLM.

        json_mode: request the provider guarantee syntactically valid JSON output
            (e.g. OpenAI-compatible `response_format={"type": "json_object"}`).
        json_schema: when set alongside json_mode, request strict schema-constrained
            output where the provider supports it. Providers that don't support
            schema-constrained output fall back to loose json_mode.
        """
        raise NotImplementedError
