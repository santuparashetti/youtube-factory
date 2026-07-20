"""Prompt Enricher — adds identity continuity hints to prompts."""

from __future__ import annotations

from typing import Any

from video_core.visual_intelligence.consistency.scene_memory import SceneMemory


class PromptEnricher:
    """Enrich prompts with identity continuity from SceneMemory."""

    def __init__(self, registry: Any | None = None, memory: SceneMemory | None = None) -> None:
        self._registry = registry
        self._memory = memory or SceneMemory()

    def enrich(
        self,
        prompt: str,
        scene_id: str,
        video_id: str,
        visual_metadata: dict[str, Any] | None = None,
    ) -> str:
        identity_hints: list[str] = []
        if visual_metadata:
            scene_identities = visual_metadata.get("identities", [])
            for identity_id in scene_identities:
                if self._memory:
                    history = self._memory.get_identity_history(identity_id)
                    if history:
                        identity_hints.append(
                            f"Consistent with prior appearance: {identity_id}"
                        )
                if self._registry:
                    identity = self._registry.get(identity_id)
                    if identity:
                        identity_hints.append(identity.to_prompt_fragment())
        if not identity_hints:
            return prompt
        return f"{prompt}\n\nContinuity: {'; '.join(identity_hints)}."
