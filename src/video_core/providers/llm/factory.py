from ytfactory.config.settings import Settings
from video_core.providers.llm.base import LLMProvider
from video_core.providers.llm.gemini import GeminiProvider


def get_llm_provider(
    settings: Settings,
) -> LLMProvider:
    """Return configured LLM provider."""

    match settings.llm_provider.lower():
        case "gemini":
            return GeminiProvider(settings)

        case "groq":
            from video_core.providers.llm.groq_provider import GroqProvider

            return GroqProvider(settings)

        case "ollama":
            from video_core.providers.llm.ollama import OllamaProvider

            return OllamaProvider(settings)

        case "anthropic":
            from video_core.providers.llm.openai_provider import OpenAICompatibleProvider

            return OpenAICompatibleProvider(settings)

        case _:
            raise ValueError(
                f"Unsupported LLM provider: {settings.llm_provider}. "
                "Valid options: gemini, groq, ollama, anthropic"
            )
