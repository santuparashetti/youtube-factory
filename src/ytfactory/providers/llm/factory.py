from ytfactory.config.settings import Settings
from ytfactory.providers.llm.base import LLMProvider
from ytfactory.providers.llm.gemini import GeminiProvider


def get_llm_provider(
    settings: Settings,
) -> LLMProvider:
    """Return configured LLM provider."""

    match settings.llm_provider.lower():
        case "gemini":
            return GeminiProvider(settings)

        case _:
            raise ValueError(
                f"Unsupported LLM provider: {settings.llm_provider}"
            )