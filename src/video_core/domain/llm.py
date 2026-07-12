from dataclasses import dataclass


@dataclass(slots=True)
class LLMResponse:
    """Normalized response returned by any LLM provider."""

    text: str

    model: str

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    finish_reason: str | None = None
