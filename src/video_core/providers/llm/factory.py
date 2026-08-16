from __future__ import annotations

from typing import TYPE_CHECKING

from video_core.config.shared_settings import SharedSettings
from video_core.domain.llm import LLMResponse
from video_core.providers.llm.base import LLMProvider
from video_core.providers.llm.cost_tracker import CostTracker
from video_core.providers.llm.gemini import GeminiProvider

if TYPE_CHECKING:
    from video_core.providers.llm.tasks import LLMTask


class _TrackedProvider(LLMProvider):
    """Wraps any LLMProvider and records token/cost usage into CostTracker."""

    def __init__(self, inner: LLMProvider, task_label: str) -> None:
        self._inner = inner
        self._task_label = task_label

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        json_mode: bool = False,
        json_schema: dict | None = None,
    ) -> LLMResponse:
        resp = self._inner.generate(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            json_mode=json_mode,
            json_schema=json_schema,
        )
        CostTracker.record(
            task_label=self._task_label,
            model=resp.model,
            input_tokens=resp.prompt_tokens,
            output_tokens=resp.completion_tokens,
            cost_usd=resp.cost_usd,
        )
        return resp

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


def get_provider_label(settings: SharedSettings) -> str:
    """Return a 'provider/model' label for logging (e.g. 'anthropic/claude-haiku-4-5')."""
    provider = settings.llm_provider.lower()
    field = _PROVIDER_MODEL_FIELD.get(provider, "")
    model = getattr(settings, field, "") if field else ""
    return f"{provider}/{model}" if model else provider


def get_provider_label_for_role(settings: SharedSettings, role: str) -> str:
    """Like get_provider_label but resolves the model via the same chain as get_llm_for_role.

    Resolution order: role-specific field → llm_default_model → provider-specific field.
    This ensures the label matches the model actually used by get_llm_for_role.
    """
    provider = settings.llm_provider.lower()
    field = _PROVIDER_MODEL_FIELD.get(provider, "")

    model = ""
    role_field = _ROLE_SETTINGS_FIELD.get(role, "")
    if role_field:
        model = getattr(settings, role_field, "") or ""
    if not model:
        model = getattr(settings, "llm_default_model", "") or ""
    if not model and field:
        model = getattr(settings, field, "") or ""

    return f"{provider}/{model}" if model else provider


def get_llm_for_role(
    settings: SharedSettings,
    role: str,
    *,
    model_override: str = "",
    _track: bool = True,
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
        provider = get_llm_provider(settings)
        return _TrackedProvider(provider, role) if _track else provider

    provider_type = settings.llm_provider.lower()
    field = _PROVIDER_MODEL_FIELD.get(provider_type)
    if not field:
        provider = get_llm_provider(settings)
        return _TrackedProvider(provider, role) if _track else provider

    current_model = getattr(settings, field, "")
    if model == current_model:
        provider = get_llm_provider(settings)
        return _TrackedProvider(provider, role) if _track else provider

    provider = get_llm_provider(settings.model_copy(update={field: model}))
    return _TrackedProvider(provider, role) if _track else provider


def get_llm_for_task(settings: SharedSettings, task: "LLMTask") -> LLMProvider:
    """Return an LLM provider configured for a specific pipeline task.

    Resolution: YT_LLM_MODEL_<TASK> > LLM_DEFAULT_MODEL > provider model.
    If the resolved model differs from the current provider model, creates a
    shallow settings copy with the provider's model field updated.
    """
    model = settings.get_llm_model(task)
    task_label = task.value if hasattr(task, "value") else str(task)
    if not model:
        return _TrackedProvider(get_llm_provider(settings), task_label)
    provider_type = settings.llm_provider.lower()
    field = _PROVIDER_MODEL_FIELD.get(provider_type)
    if not field:
        return _TrackedProvider(get_llm_provider(settings), task_label)
    current_model = getattr(settings, field, "")
    if model == current_model:
        return _TrackedProvider(get_llm_provider(settings), task_label)
    return _TrackedProvider(
        get_llm_provider(settings.model_copy(update={field: model})),
        task_label,
    )
