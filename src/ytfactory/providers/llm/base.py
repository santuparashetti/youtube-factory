from abc import ABC, abstractmethod

from ytfactory.domain.llm import LLMResponse


class LLMProvider(ABC):
    """Base interface for all LLM providers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Generate text from an LLM."""
        raise NotImplementedError