"""Factory function for SubtitleEditorProvider instances."""

from __future__ import annotations

from .provider import SubtitleEditorProvider


def get_subtitle_editor_provider(settings) -> SubtitleEditorProvider:
    """Return the configured SubtitleEditorProvider.

    Reads settings.subtitle_editor_provider:
      "llm"  — wraps the configured LLM provider (default)
      "mock" — deterministic passthrough, no API calls (for tests)
    """
    name = getattr(settings, "subtitle_editor_provider", "llm")

    if name == "mock":
        from .providers.mock import MockSubtitleEditor

        return MockSubtitleEditor()

    if name == "llm":
        from .providers.llm_provider import LLMSubtitleEditor
        from ytfactory.providers.llm.factory import get_llm_provider

        return LLMSubtitleEditor(get_llm_provider(settings))

    raise ValueError(
        f"Unknown subtitle_editor_provider: {name!r}. Use 'llm' or 'mock'."
    )
