"""Bible-aware prompt builder mixin for ImagePromptEngineV4.

When a scene has a non-legacy bible_ext, this mixin intercepts build_prompt()
and constructs the image prompt from CharacterBible and EnvironmentBible data
rather than from the raw visual_prompt field.

Legacy scenes (no bible_ext) pass through to the existing build_prompt() unchanged.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import ValidationError as PydanticValidationError

from .character_bible import (
    CharacterBible,
    CharacterPresence,
    AnimalPresence,
    BibleTemporalMode,
)
from .environment_bible import EnvironmentBible
from .scene_bible_extension import SceneBibleExtension, parse_bible_ext
from .scene_validator import SceneBibleValidator, ValidationResult

logger = logging.getLogger(__name__)


# ── Exception ──────────────────────────────────────────────────────────────────


class PromptValidationError(Exception):
    """Raised when a Bible-enabled scene fails validation.

    Caught in the existing ImagePipeline prompt-generation error handler.
    Routes to the existing flagged-scene / needs-review remediation path.
    """

    def __init__(self, scene_id: str, errors: list[str]):
        self.scene_id = scene_id
        self.errors = errors
        super().__init__(
            f"Scene '{scene_id}' failed Bible validation:\n"
            + "\n".join(f"  • {e}" for e in errors)
        )


# ── Prompt section templates ────────────────────────────────────────────────────

_GLOBAL_STYLE = (
    "GLOBAL STYLE:\n"
    "Layer 1 — Environment: 100% photorealistic, cinematic depth of field, "
    "documentary-quality textures.\n"
    "Layer 2 — Characters: hand-painted 2D storybook illustration, clean ink "
    "outlines, restrained cel shading, painterly brush texture. "
    "NOT photorealistic."
)

_TEMPORAL_LOCK_TEXTS: dict[BibleTemporalMode, str] = {
    BibleTemporalMode.HISTORICAL_LITERAL: (
        "TEMPORAL_MODE: HISTORICAL_LITERAL\n"
        "TEMPORAL LOCK: This scene MUST remain entirely within the historical period.\n"
        "No modern objects, contemporary clothing, or post-period technology."
    ),
    BibleTemporalMode.HISTORICAL_SYMBOLIC: (
        "TEMPORAL_MODE: HISTORICAL_SYMBOLIC\n"
        "TEMPORAL LOCK: Historical setting with symbolic elements permitted.\n"
        "No contemporary objects, clothing, or architecture."
    ),
    BibleTemporalMode.CONTEMPORARY_LITERAL: (
        "TEMPORAL_MODE: CONTEMPORARY_LITERAL\n"
        "TEMPORAL LOCK: This scene MUST remain entirely contemporary.\n"
        "Do not introduce historical architecture, period clothing, or pre-modern objects."
    ),
    BibleTemporalMode.CONTEMPORARY_SYMBOLIC: (
        "TEMPORAL_MODE: CONTEMPORARY_SYMBOLIC\n"
        "TEMPORAL LOCK: This scene MUST remain entirely contemporary.\n"
        "Do not introduce ancient Greek architecture, clothing, sandals, tunics, "
        "columns, pottery, stone tools, or historical objects."
    ),
    BibleTemporalMode.TIMELESS_SYMBOLIC: (
        "TEMPORAL_MODE: TIMELESS_SYMBOLIC\n"
        "TEMPORAL LOCK: Timeless symbolic setting. "
        "No specific historical period or contemporary markers are enforced."
    ),
}


# ── Mixin ──────────────────────────────────────────────────────────────────────


class BiblePromptBuilderMixin:
    """Mixin for ImagePromptEngineV4.

    Usage in ImagePromptEngineV4:
        class ImagePromptEngineV4(BiblePromptBuilderMixin, ...existing bases...):
            def build_prompt(self, scene: dict, **kwargs) -> str:
                bible_prompt = self.try_bible_build(scene, **kwargs)
                if bible_prompt is not None:
                    return bible_prompt
                return scene.get("visual_prompt", "")  # legacy path
    """

    # ── Entry point ────────────────────────────────────────────────────────────

    def try_bible_build(
        self,
        scene: dict,
        environment_bible: Optional[EnvironmentBible] = None,
        **kwargs,
    ) -> Optional[str]:
        """Return a Bible-built prompt string if scene has a non-legacy bible_ext.

        Returns None to signal fallthrough to the legacy build_prompt() path.

        Validation failures raise PromptValidationError — the caller is responsible
        for routing it to the existing ScenePipeline error/remediation path.
        """
        raw = scene.get("bible_ext")
        if raw is None:
            return None

        # Strict parse — Pydantic ValidationError means malformed data
        try:
            ext = parse_bible_ext(raw)
        except PydanticValidationError as exc:
            scene_id = str(scene.get("scene_id", scene.get("index", "unknown")))
            raise PromptValidationError(
                scene_id=scene_id,
                errors=[f"bible_ext parse error: {exc}"],
            ) from exc

        if ext is None or ext.is_legacy():
            return None

        bible = CharacterBible.get_instance()
        env_bible = environment_bible or EnvironmentBible.get_instance()
        validator = SceneBibleValidator(bible, env_bible)
        scene_id = str(scene.get("scene_id", scene.get("index", "unknown")))
        result: ValidationResult = validator.validate(scene_id, ext)

        for warning in result.warnings:
            logger.warning(warning)

        if not result.passed:
            for error in result.errors:
                logger.error(error)
            raise PromptValidationError(scene_id=scene_id, errors=result.errors)

        return self._assemble(scene, ext, bible, env_bible)

    # ── Block builders ─────────────────────────────────────────────────────────

    def _build_global_lock(self, bible: CharacterBible) -> str:
        identity = bible.render_global_identity_lock()
        return f"{_GLOBAL_STYLE}\n\n{identity}"

    def _build_temporal(self, ext: SceneBibleExtension) -> str:
        if ext.temporal_mode is None:
            return ""
        return _TEMPORAL_LOCK_TEXTS.get(ext.temporal_mode, f"TEMPORAL_MODE: {ext.temporal_mode.value}")

    def _build_presence(self, ext: SceneBibleExtension) -> str:
        lines = []

        cp = ext.character_presence
        if cp is not None:
            lines.append(f"CHARACTER_PRESENCE: {cp.value}")
            if cp == CharacterPresence.NONE:
                lines.append("No named human characters in this scene.")
            elif cp == CharacterPresence.BACKGROUND:
                lines.append("Named characters appear small or partially obscured in the background.")
            elif cp == CharacterPresence.SYMBOLIC:
                lines.append("Named character implied by reflection, shadow, or silhouette only.")

        ap = ext.animal_presence
        if ap is not None:
            lines.append(f"ANIMAL_PRESENCE: {ap.value}")
            if ap == AnimalPresence.NONE:
                lines.append("No animals in this scene.")

        if ext.anonymous_humans_allowed and ext.anonymous_human_description:
            lines.append(
                f"ANONYMOUS_HUMANS_ALLOWED: true\n"
                f"ANONYMOUS_HUMAN_DESCRIPTION: {ext.anonymous_human_description}"
            )
        elif not ext.anonymous_humans_allowed and (cp == CharacterPresence.NONE or cp is None):
            lines.append("ANONYMOUS_HUMANS: No unnamed/background humans permitted.")

        return "\n".join(lines)

    def _build_characters(
        self,
        ext: SceneBibleExtension,
        bible: CharacterBible,
    ) -> str:
        if not ext.characters:
            return ""
        blocks = []
        for sc in ext.characters:
            try:
                entry = bible.get(sc.character_id)
            except KeyError:
                continue
            lines = [entry.render_identity_block()]
            lines.append(f"ACTION: {sc.action}")
            if sc.emotion:
                lines.append(f"EMOTION: {sc.emotion}")
            pose = sc.pose_override or entry.pose_rule
            if pose:
                lines.append(f"POSE: {pose.strip()}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def _build_forbidden(
        self,
        ext: SceneBibleExtension,
        bible: CharacterBible,
    ) -> str:
        all_ids = set(bible.all_ids())
        allowed = set(ext.allowed_character_ids)
        explicit_forbidden = set(ext.forbidden_character_ids)
        forbidden = (all_ids - allowed) | explicit_forbidden

        if not forbidden:
            return ""
        forbidden_lines = " ".join(f"No {fid}." for fid in sorted(forbidden))
        return (
            "FORBIDDEN_CHARACTERS:\n"
            + forbidden_lines
            + " No additional humans beyond those listed above."
        )

    def _build_scene_body(
        self,
        scene: dict,
        ext: SceneBibleExtension,
        env_bible: Optional[EnvironmentBible] = None,
    ) -> str:
        lines = []

        # ENVIRONMENT — from EnvironmentBible if environment_id set, else from scene
        if ext.environment_id and env_bible is not None and env_bible.has(ext.environment_id):
            entry = env_bible.get(ext.environment_id)
            env_text = entry.description.strip()
            detail = scene.get("environment_detail", "")
            if detail:
                env_text = f"{env_text} {detail}"
            lines.append(f"ENVIRONMENT: {env_text}")
        else:
            env = scene.get("environment", "")
            if env:
                lines.append(f"ENVIRONMENT: {env}")

        # COMPOSITION, CAMERA, LIGHTING from existing scene fields
        composition = scene.get("composition", "")
        if composition:
            lines.append(f"COMPOSITION: {composition}")

        camera = scene.get("camera", "") or scene.get("shot_type", "")
        if camera:
            lines.append(f"CAMERA: {camera}")

        lighting = scene.get("lighting", "")
        if lighting:
            lines.append(f"LIGHTING: {lighting}")

        return "\n".join(lines)

    def _build_continuity(self, scene: dict) -> str:
        """Build CONTINUITY block from existing SceneMemory / ContinuityValidator output."""
        continuity = scene.get("continuity_context", "") or scene.get("continuity_ref", "")
        if not continuity:
            return ""
        return f"CONTINUITY:\n{continuity}"

    def _build_negative(
        self,
        scene: dict,
        forbidden_block: str,
    ) -> str:
        lines = [
            "NEGATIVE:",
            "No text, no watermark, no subtitle, no logo.",
            "No photorealistic characters, no realistic human photos, no realistic animals.",
            "No deformed hands, no extra fingers, no mutated or fused limbs.",
        ]
        if forbidden_block:
            lines.append(forbidden_block)
        extra = scene.get("negative_extra", "")
        if extra:
            lines.append(extra)
        return "\n".join(lines)

    def _assemble(
        self,
        scene: dict,
        ext: SceneBibleExtension,
        bible: CharacterBible,
        env_bible: Optional[EnvironmentBible] = None,
    ) -> str:
        """Join all blocks in canonical order."""
        global_lock = self._build_global_lock(bible)
        temporal = self._build_temporal(ext)
        presence = self._build_presence(ext)
        characters = self._build_characters(ext, bible)
        forbidden = self._build_forbidden(ext, bible)
        scene_body = self._build_scene_body(scene, ext, env_bible)
        continuity = self._build_continuity(scene)
        negative = self._build_negative(scene, forbidden)

        blocks = [
            global_lock,
            temporal,
            presence,
            characters,
            scene_body,
            continuity,
            negative,
        ]
        return "\n\n".join(b for b in blocks if b.strip())
