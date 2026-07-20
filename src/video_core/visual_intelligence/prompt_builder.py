from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from video_core.domain.visual_metadata import (
    Environment,
    Era,
    Mood,
    NarrativeRole,
    VisualMetadata,
    VisualStyle,
)
from video_core.visual_intelligence.prompt_package import PromptPackage
from video_core.visual_intelligence.profiles import (
    ANCIENT_DOCUMENTARY,
    HISTORICAL_DOCUMENTARY,
    MODERN_DOCUMENTARY,
    SYMBOLIC_DOCUMENTARY,
    TRANSITIONAL_DOCUMENTARY,
)

logger = logging.getLogger(__name__)


@dataclass
class PromptDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = []
        for item in self.added:
            lines.append(f"+ {item}")
        for item in self.removed:
            lines.append(f"- {item}")
        for item in self.changed:
            lines.append(f"~ {item}")
        return "\n".join(lines)


def merge_negative_prompts(*parts: str | None) -> str | None:
    """Merge multiple negative prompt fragments, deduplicating by lowercase term."""
    terms: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        for term in part.split(","):
            term = term.strip()
            if term and term.lower() not in seen:
                seen.add(term.lower())
                terms.append(term)
    return ", ".join(terms) if terms else None


class PromptBuilder:
    """Assemble provider-ready image prompts from scene description and VisualMetadata.

    The Prompt Builder is the only component responsible for prompt assembly.
    It consumes structured VisualMetadata and produces a PromptPackage.

    Backward compatibility:
        If VisualMetadata is absent or not populated, the builder returns a
        PromptPackage wrapping the original prompt with no modifications.
    """

    _ERA_PROFILES: dict[Era, Any] = {
        Era.ANCIENT: ANCIENT_DOCUMENTARY,
        Era.HISTORICAL: HISTORICAL_DOCUMENTARY,
        Era.MODERN: MODERN_DOCUMENTARY,
        Era.SYMBOLIC: SYMBOLIC_DOCUMENTARY,
        Era.TRANSITIONAL: TRANSITIONAL_DOCUMENTARY,
    }

    _ENVIRONMENT_ENHANCEMENTS: dict[Environment, str] = {
        Environment.FOREST: "dense forest, ancient trees, dappled sunlight through canopy, moss-covered ground",
        Environment.TEMPLE: "stone temple complex, carved columns, sacred atmosphere, oil lamps, incense smoke",
        Environment.ASHRAM: "simple ashram, meditation halls, peaceful surroundings, natural setting, rustic simplicity",
        Environment.KINGDOM: "ancient kingdom, palace architecture, royal court, stone fortifications, grand halls",
        Environment.BATTLEFIELD: "vast battlefield, dramatic sky, dust, historical warfare landscape, tension",
        Environment.CITY: "urban environment, cityscape, contemporary architecture, bustling streets",
        Environment.OFFICE: "modern office, professional workspace, contemporary interior, clean design",
        Environment.HOME: "domestic interior, personal space, everyday setting, lived-in comfort",
        Environment.MOUNTAIN: "mountain landscape, dramatic peaks, natural grandeur, vast horizon",
        Environment.RIVER: "riverbank, flowing water, natural landscape, serene water",
        Environment.ABSTRACT: "abstract visual space, non-representational forms, conceptual shapes",
        Environment.COSMIC: "cosmic scale, celestial, vast universe, stars and nebulae, infinite depth",
    }

    _MOOD_ENHANCEMENTS: dict[Mood, str] = {
        Mood.PEACEFUL: "warm golden light, soft shadows, tranquil atmosphere, still water, gentle breeze",
        Mood.MYSTERIOUS: "fog and moonlight, deep shadows, atmospheric haze, hidden details, low key lighting",
        Mood.REVERENT: "sacred atmosphere, temple glow, respectful composition, divine light, hushed mood",
        Mood.REFLECTIVE: "soft evening light, contemplative mood, quiet space, thoughtful atmosphere",
        Mood.HOPEFUL: "first light breaking through clouds, warm sunrise, open sky, uplifting composition",
        Mood.FEARFUL: "stormy contrast, dark shadows, dramatic tension, ominous atmosphere, cold tones",
        Mood.CURIOUS: "exploratory framing, intriguing details, discovery mood, engaging composition",
        Mood.LONELY: "isolated figure, vast empty space, desaturated colors, melancholic atmosphere",
        Mood.DETERMINED: "strong composition, purposeful stance, dramatic lighting, resolute mood",
    }

    _ROLE_ENHANCEMENTS: dict[NarrativeRole, str] = {
        NarrativeRole.STORY: "documentary realism, authentic moment, narrative flow, cinematic storytelling",
        NarrativeRole.ANALOGY: "concept blended with reality, visual metaphor, comparative framing, dual meaning",
        NarrativeRole.METAPHOR: "symbolic imagery, abstract representation, conceptual visual, layered meaning",
        NarrativeRole.EXPLANATION: "educational clarity, clear focal point, instructional composition, accessible visual",
        NarrativeRole.ESTABLISHING: "wide cinematic composition, establishing shot, scene-setting vista, environmental context",
        NarrativeRole.CTA: "clean composition, open space for overlay, direct address framing, clear focal area",
    }

    _VISUAL_STYLE_LABELS: dict[VisualStyle, str] = {
        VisualStyle.DOCUMENTARY: "documentary style, realistic, authentic, observational",
        VisualStyle.CINEMATIC: "cinematic style, dramatic, filmic, epic composition",
        VisualStyle.REALISTIC: "photorealistic, hyperrealistic, lifelike, true to life",
        VisualStyle.DREAMLIKE: "dreamlike, soft focus, ethereal, surreal beauty",
        VisualStyle.PAINTING: "painterly style, artistic, brushstroke texture, fine art",
        VisualStyle.ANIME: "anime style, animated, stylized, vibrant",
        VisualStyle.WATERCOLOR: "watercolor style, soft washes, translucent, delicate",
    }

    def build_from_scene(self, scene: dict) -> PromptPackage:
        """Build a PromptPackage from a scene dict.

        Reads ``visual_metadata`` from the scene dict if present and populated.
        Falls back to the original prompt if metadata is absent or empty.
        """
        raw_metadata = scene.get("visual_metadata", {})
        visual_metadata: VisualMetadata | None = None
        if raw_metadata and isinstance(raw_metadata, dict):
            try:
                visual_metadata = VisualMetadata.model_validate(raw_metadata)
            except Exception:
                visual_metadata = None
        return self.build(scene, visual_metadata)

    def build(
        self,
        scene: dict,
        visual_metadata: VisualMetadata | None = None,
    ) -> PromptPackage:
        """Build a PromptPackage from a scene dict and optional VisualMetadata.

        If visual_metadata is None or not populated, returns a fallback package
        that preserves the original prompt unchanged.
        """
        description = scene.get("visual_prompt", "")
        metadata_snapshot = visual_metadata.to_prompt_snapshot() if visual_metadata else {}

        if not visual_metadata or not visual_metadata.is_populated:
            return PromptPackage(
                final_prompt=description,
                negative_prompt=None,
                visual_profile="",
                prompt_fingerprint=self._fingerprint(description, metadata_snapshot),
                metadata_snapshot=metadata_snapshot,
                assembly_report=self._empty_report(description, metadata_snapshot),
            )

        era = visual_metadata.era
        profile = self._ERA_PROFILES.get(era, ANCIENT_DOCUMENTARY)

        positive_parts = [description] if description else []
        positive_parts.extend(profile.positive_fragments)

        if profile.lighting:
            positive_parts.append(profile.lighting)
        if profile.architecture:
            positive_parts.append(profile.architecture)
        if profile.materials:
            positive_parts.append(profile.materials)
        if profile.atmosphere:
            positive_parts.append(profile.atmosphere)
        if profile.camera:
            positive_parts.append(profile.camera)
        if profile.color_palette:
            positive_parts.append(profile.color_palette)

        if visual_metadata.environment and visual_metadata.environment in self._ENVIRONMENT_ENHANCEMENTS:
            positive_parts.append(self._ENVIRONMENT_ENHANCEMENTS[visual_metadata.environment])

        if visual_metadata.narrative_role and visual_metadata.narrative_role in self._ROLE_ENHANCEMENTS:
            positive_parts.append(self._ROLE_ENHANCEMENTS[visual_metadata.narrative_role])

        if visual_metadata.mood and visual_metadata.mood in self._MOOD_ENHANCEMENTS:
            positive_parts.append(self._MOOD_ENHANCEMENTS[visual_metadata.mood])

        if visual_metadata.visual_style and visual_metadata.visual_style in self._VISUAL_STYLE_LABELS:
            positive_parts.append(self._VISUAL_STYLE_LABELS[visual_metadata.visual_style])

        final_prompt = ", ".join(part for part in positive_parts if part)

        negative_parts = list(profile.negative_fragments)
        if era == Era.ANCIENT and not visual_metadata.allow_modern_objects:
            negative_parts.extend(
                [
                    "modern objects",
                    "contemporary elements",
                    "anachronistic technology",
                    "modern infrastructure",
                ]
            )
        elif era == Era.HISTORICAL and not visual_metadata.allow_modern_objects:
            negative_parts.extend(
                [
                    "anachronistic elements",
                    "modern technology",
                    "inaccurate period details",
                ]
            )
        elif era == Era.MODERN:
            negative_parts.extend(
                [
                    "ancient styling",
                    "historical costumes",
                    "outdated technology",
                ]
            )

        negative_prompt = ", ".join(negative_parts) if negative_parts else None

        fingerprint = self._fingerprint(final_prompt, metadata_snapshot)
        assembly_report = self._build_report(
            description=description,
            profile=profile,
            era=era,
            environment=visual_metadata.environment,
            narrative_role=visual_metadata.narrative_role,
            mood=visual_metadata.mood,
            visual_style=visual_metadata.visual_style,
            allow_modern_objects=visual_metadata.allow_modern_objects,
            positive_parts=positive_parts,
            negative_parts=negative_parts,
            final_prompt=final_prompt,
            negative_prompt=negative_prompt,
        )

        return PromptPackage(
            final_prompt=final_prompt,
            negative_prompt=negative_prompt,
            visual_profile=profile.name,
            prompt_fingerprint=fingerprint,
            metadata_snapshot=metadata_snapshot,
            assembly_report=assembly_report,
        )

    def diff(
        self,
        before: PromptPackage,
        after: PromptPackage,
    ) -> PromptDiff:
        """Compute a structured diff between two PromptPackages.

        Used when remediation regenerates an image to show what changed.
        """
        before_words = set(before.final_prompt.lower().replace(",", " ").split())
        after_words = set(after.final_prompt.lower().replace(",", " ").split())
        return PromptDiff(
            added=sorted(after_words - before_words),
            removed=sorted(before_words - after_words),
            changed=sorted(
                {
                    w
                    for w in before_words & after_words
                    if before.final_prompt.lower().count(w) != after.final_prompt.lower().count(w)
                }
            ),
        )

    def _fingerprint(self, prompt: str, metadata: dict) -> str:
        payload = f"{prompt}|{json.dumps(metadata, sort_keys=True)}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _empty_report(self, description: str, metadata: dict) -> dict:
        return {
            "scene_description": description,
            "visual_metadata": metadata,
            "applied_profile": "",
            "positive_constraints": [],
            "negative_constraints": [],
            "environment_enhancements": [],
            "mood_enhancements": [],
            "narrative_role_enhancements": [],
            "prompt_statistics": {
                "word_count": len(description.split()),
                "char_count": len(description),
            },
            "final_prompt": description,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _build_report(
        self,
        description: str,
        profile: Any,
        era: Era | None,
        environment: Environment | None,
        narrative_role: NarrativeRole | None,
        mood: Mood | None,
        visual_style: VisualStyle | None,
        allow_modern_objects: bool,
        positive_parts: list[str],
        negative_parts: list[str],
        final_prompt: str,
        negative_prompt: str | None,
    ) -> dict:
        return {
            "scene_description": description,
            "visual_metadata": {
                "era": era.value if era else None,
                "narrative_role": narrative_role.value if narrative_role else None,
                "environment": environment.value if environment else None,
                "mood": mood.value if mood else None,
                "visual_style": visual_style.value if visual_style else None,
                "allow_modern_objects": allow_modern_objects,
            },
            "applied_profile": profile.name,
            "positive_constraints": profile.positive_fragments,
            "negative_constraints": profile.negative_fragments,
            "environment_enhancements": (
                [self._ENVIRONMENT_ENHANCEMENTS[environment]] if environment in self._ENVIRONMENT_ENHANCEMENTS else []
            ),
            "mood_enhancements": [self._MOOD_ENHANCEMENTS[mood]] if mood in self._MOOD_ENHANCEMENTS else [],
            "narrative_role_enhancements": (
                [self._ROLE_ENHANCEMENTS[narrative_role]] if narrative_role in self._ROLE_ENHANCEMENTS else []
            ),
            "prompt_statistics": {
                "word_count": len(final_prompt.split()),
                "char_count": len(final_prompt),
                "positive_fragment_count": len(positive_parts),
                "negative_fragment_count": len(negative_parts),
            },
            "final_prompt": final_prompt,
            "negative_prompt": negative_prompt,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
