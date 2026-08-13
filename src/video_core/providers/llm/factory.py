from __future__ import annotations

from video_core.config.shared_settings import SharedSettings
from video_core.providers.llm.base import LLMProvider
from video_core.providers.llm.gemini import GeminiProvider

_PROVIDER_MODEL_FIELD: dict[str, str] = {
    "anthropic": "anthropic_model",
    "gemini": "gemini_text_model",
    "groq": "groq_model",
    "ollama": "ollama_model",
    "deepinfra": "deepinfra_model",
}

_ROLE_SETTINGS_FIELD: dict[str, str] = {
    "script": "script_model",
    "scene_planner": "scene_planner_model",
    "research": "research_model",
    "title": "title_model",
    "subtitle": "subtitle_model",
    "ssml": "ssml_model",
}


def get_llm_provider(
    settings: SharedSettings,
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

        case "deepinfra":
            from video_core.providers.llm.deepinfra_provider import DeepInfraProvider

            return DeepInfraProvider(settings)

        case _:
            raise ValueError(
                f"Unsupported LLM provider: {settings.llm_provider}. "
                "Valid options: gemini, groq, ollama, anthropic, deepinfra"
            )


def get_llm_for_role(
    settings: SharedSettings,
    role: str,
    *,
    model_override: str = "",
) -> LLMProvider:
    """Return an LLM provider configured for a specific pipeline role.

    Resolution order:
    1. ``model_override`` (explicit caller argument)
    2. Per-role settings field (e.g. ``SCRIPT_MODEL``)
    3. ``LLM_DEFAULT_MODEL`` (provider-agnostic default)
    4. Provider-specific model (e.g. ``ANTHROPIC_MODEL``)

    If the resolved model differs from the provider default, a shallow
    settings copy is created with the provider's model field overridden
    and a fresh provider is constructed from it.
    """
    model = model_override
    if not model:
        role_field = _ROLE_SETTINGS_FIELD.get(role, "")
        if role_field:
            model = getattr(settings, role_field, "") or ""

    if not model:
        model = settings.llm_default_model or ""

    if not model:
        return get_llm_provider(settings)

    provider_type = settings.llm_provider.lower()
    field = _PROVIDER_MODEL_FIELD.get(provider_type)
    if not field:
        return get_llm_provider(settings)

    current_model = getattr(settings, field, "")
    if model == current_model:
        return get_llm_provider(settings)

    return get_llm_provider(settings.model_copy(update={field: model}))
