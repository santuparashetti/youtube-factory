"""Scene planner node — Python splits narrations, LLM adds visual prompts only."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace as dc_replace
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from video_core.providers.llm.base import LLMProvider
from video_core.providers.llm.factory import get_llm_for_role
from ytfactory.agents.prompts.branding import (
    CLOSING_VARIATIONS,
    SOFT_CTA,
    WELCOME_VARIATIONS,
)
from ytfactory.agents.prompts.scene_planner import (
    ENTITY_EXTRACTION_PROMPT,
    FAITHFULNESS_VALIDATION_PROMPT,
    build_llm_validation_prompt,
    build_pacing_prompt,
    build_scene_analysis_prompt,
    build_scene_analysis_section,
    build_visual_prompts_prompt,
)
from ytfactory.agents.state import VideoState
from ytfactory.branding.config import get_brand_config
from ytfactory.config.settings import Settings
from ytfactory.images.faithfulness_gate import evaluate_faithfulness_gate
from ytfactory.images.prompt_engine import ImagePromptEngineV4
from ytfactory.images.validators import (
    HUMAN_CLASSIFICATION_RULES,
    HumanClassification,
    ValidationError,
    ValidationResult,
    build_retry_prompt,
    compose_feedback,
    run_validators,
)
from ytfactory.scene_continuity import (
    ContinuityReport,
    SceneContinuityStatus,
    ContinuityValidator,
    StoryState,
    build_action_constraints_block,
    build_story_state,
    validate_prompt_against_state,
)
from ytfactory.scenes.models import (
    FaithfulnessStatus,
    StructuredImagePrompt,
    VisualBible,
)
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shared.pipeline_status import PipelineAbort
from ytfactory.story_bible.composer import compose_scene_context
from ytfactory.story_bible.generator import load_or_generate_story_bible
from ytfactory.story_bible.models import StoryBible
from ytfactory.story_bible.writer import write_story_bible
from ytfactory.emotion.policy import NarrativePhase, emotion_policy
from ytfactory.shared.script_utils import strip_script_heading
from ytfactory.storage.artifact_repository import ArtifactRepository
from ytfactory.storage.project_repository import ProjectRepository

# Closing phrases that should trigger an asset scene instead of AI image generation.
# Derived from branding module so detection tracks new variants from brand config.
_CLOSING_TRIGGERS: frozenset[str] = frozenset(
    phrase.lower().strip().rstrip(".") for phrase in CLOSING_VARIATIONS + [SOFT_CTA]
)

# Opening line category — prevents the disabled opening text from being accidentally
# collected into the closing_block category by _mark_asset_scenes().
_OPENING_TRIGGERS: frozenset[str] = frozenset(
    phrase.lower().strip().rstrip(".") for phrase in WELCOME_VARIATIONS if phrase
)

console = Console()

_TARGET_WORDS_PER_SCENE = 35  # ~16s scenes at 130 wpm → ~30-35 scenes per 9 min video

# Compressed hybrid style prefix injected when the LLM omits the style header.
# Kept under 40 words so it doesn't bloat short-scene prompts.
_HYBRID_COMPRESSED_PREFIX = (
    "HYBRID CINEMATIC STYLE: 100% photorealistic environment, hand-painted storybook "
    "illustrated characters with clean ink outlines and soft cel shading, composited "
    "with matching lighting and shadows."
)

# ── Kai enforcement guards ────────────────────────────────────────────────────
# Single source of truth for the compressed Kai spec injected into primary prompts.
KAI_COMPRESSED_SPEC = (
    "Lean young man, late 20s, short dark hair, light stubble, "
    "simple dark shirt, plain trousers, calm expression"
)

_KAI_MARKERS = [
    "dark hair",
    "simple dark shirt",
    "lean young man",
    "light stubble",
    "plain trousers",
]

# Markers that indicate character-staging text has leaked into environment_prompt.
# When character_staging is empty but environment_prompt matches any of these in its
# first 200 characters, the LLM placed character description in the wrong field.
_CHARACTER_ENV_CONTAMINATION_MARKERS: tuple[str, ...] = (
    "lean young man",
    "lean young woman",
    "lean young adult",
    "illustrated in hand-painted storybook style",
    "illustrated in hand-painted",
    "storybook style —",
    "shown in strict",
    "in his late 20s",
    "in her late 20s",
    "simple dark shirt",
    "plain trousers",
    "light stubble",
    "short dark hair",
)

# Marker that reliably separates a character spec from the environment description.
_CHAR_ENV_SEPARATOR = " — "


def _has_kai_markers(prompt: str) -> bool:
    p = prompt.lower()
    return any(m in p for m in _KAI_MARKERS)


# Pronouns use word-boundary matching (via _CHARACTER_STAGING_RE) to avoid
# false positives like "the " matching "he " or "there " matching "her ".
# Multi-word phrases and action verbs are matched as substrings (also via the RE).
_CHARACTER_STAGING_RE = re.compile(
    r"\b(?:he|his|him|she|her|seated|standing|sitting|walking|looking|facing|"
    r"kneeling|leaning|the man|the woman|a man|a woman|the figure|a figure|"
    r"a human figure|the young man|a person|someone|a single person|positioned)\b",
    re.IGNORECASE,
)


def _has_character_staging(prompt: str) -> bool:
    """True if the visual_prompt staging describes a visible human character."""
    return bool(_CHARACTER_STAGING_RE.search(prompt))


_ACTION_VERBS = [
    # Gerund forms (pre-V2 prompt style)
    "sitting",
    "seated",
    "standing",
    "walking",
    "looking",
    "facing",
    "leaning",
    "kneeling",
    "watching",
    "holding",
    "reaching",
    "turning",
    "positioned",
    "gazing",
    "staring",
    "moving",
    "stepping",
    # Simple present forms (V2 compiled_prompt style)
    "sits",
    "stands",
    "walks",
    "looks",
    "faces",
    "leans",
    "kneels",
    "watches",
    "holds",
    "reaches",
    "turns",
    "gazes",
    "stares",
    "moves",
    "steps",
    # Past tense forms
    "stood",
    "sat",
    "walked",
    "looked",
    "faced",
    "leaned",
    "knelt",
    "watched",
    "held",
    "reached",
    "turned",
    "gazed",
    "stared",
]


def _has_action_staging(prompt: str) -> bool:
    """True if the prompt contains an active character action verb."""
    p = prompt.lower()
    return any(v in p for v in _ACTION_VERBS)


# Camera angles where a standing character cannot logically be placed.
# "looking straight down" is a common false positive for _has_character_staging.
_AERIAL_INDICATORS = [
    "aerial",
    "drone shot",
    "bird's eye",
    "looking straight down",
    "top-down",
    "overhead shot",
    "straight down on",
]


def _is_aerial_shot(prompt: str) -> bool:
    """True if the prompt describes an overhead/aerial camera angle."""
    p = prompt.lower()
    return any(ind in p for ind in _AERIAL_INDICATORS)


def _has_story_specific_character(scene: dict, prompt: str) -> bool:
    """True if the scene already describes a named story protagonist in the prompt.

    When True, _enforce_primary_kai_spec should NOT prepend Kai's spec —
    the scene has its own specific character from the story (e.g. Traveler,
    Shivaji, Ali Baba) and injecting Kai would create a character mismatch.
    """
    analysis = scene.get("scene_analysis") or {}
    allowed = (
        analysis.get("allowed_characters", [])
        if isinstance(analysis, dict)
        else getattr(analysis, "allowed_characters", [])
    ) or []

    _KAI_NAMES = {"kai", "the anchor character", "anchor character"}
    story_characters = [c for c in allowed if c and c.lower().strip() not in _KAI_NAMES]
    if not story_characters:
        return False

    prompt_lower = prompt.lower()
    for char_name in story_characters:
        words = char_name.lower().split()
        for word in words:
            if len(word) > 3 and word in prompt_lower:
                return True
    return False


def _enforce_primary_kai_spec(scenes: list[dict]) -> list[dict]:
    """Enforce Kai character spec injection using character_presence as the authority.

    character_presence takes precedence when set:
    - KAI in character_presence → Kai may be injected (original role-based rules apply)
    - Non-Kai characters in character_presence but KAI absent → strip any stray Kai markers,
      set anchor_role='absent' so style footer knows no Kai is present
    - character_presence empty → backward-compat path: use anchor_role (old scene plans)

    For backward-compat primary scenes (no character_presence):
    - Aerial shots → reclassify absent
    - Kai markers + action → keep
    - Kai markers, no action → reclassify absent (atmospheric contradiction)
    - No Kai markers + story protagonist already present → keep (story character takes priority)
    - No Kai markers + generic character staging → prepend Kai spec
    - No Kai markers, no character staging → reclassify absent
    """
    for scene in scenes:
        char_presence = scene.get("character_presence") or []
        char_presence_upper = {c.upper() for c in char_presence}
        kai_in_presence = "KAI" in char_presence_upper
        has_non_kai_chars = bool(char_presence_upper - {"KAI"})
        prompt = scene.get("visual_prompt", "")

        # ── character_presence is authoritative when set (non-empty) ──────────
        if char_presence:
            if not kai_in_presence:
                # KAI explicitly absent — strip any stray Kai markers from the prompt
                for marker in [KAI_COMPRESSED_SPEC + " —", KAI_COMPRESSED_SPEC]:
                    prompt = prompt.replace(marker, "").strip()
                scene["visual_prompt"] = prompt
                # anchor_role: story characters are present but Kai is not
                # Use 'spectator' only if anchor_role was already 'primary' (old prompts);
                # otherwise 'absent' is the right label (no Kai perspective at all).
                if scene.get("anchor_role") == "primary":
                    scene["anchor_role"] = "absent"
                continue

            # KAI is in character_presence — apply the original injection rules
            # Aerial/overhead shots: Kai cannot be placed meaningfully
            if _is_aerial_shot(prompt):
                for marker in [KAI_COMPRESSED_SPEC + " —", KAI_COMPRESSED_SPEC]:
                    prompt = prompt.replace(marker, "").strip()
                scene["visual_prompt"] = prompt
                scene["anchor_role"] = "absent"
                # Remove KAI from character_presence since aerial can't support him
                scene["character_presence"] = [c for c in char_presence if c.upper() != "KAI"]
                continue

            scene["anchor_role"] = "primary"
            if _has_kai_markers(prompt):
                if _has_action_staging(prompt):
                    continue
                if scene.get("structured_prompt"):
                    continue
                # Spec present but no staging — remove Kai (spec without staging is a contradiction)
                for marker in [KAI_COMPRESSED_SPEC + " —", KAI_COMPRESSED_SPEC]:
                    prompt = prompt.replace(marker, "").strip()
                scene["visual_prompt"] = prompt
                scene["anchor_role"] = "absent"
                scene["character_presence"] = [c for c in char_presence if c.upper() != "KAI"]
            elif _has_character_staging(prompt):
                if not _has_story_specific_character(scene, prompt):
                    scene["visual_prompt"] = f"{KAI_COMPRESSED_SPEC} — {prompt}"
            else:
                scene["anchor_role"] = "absent"
                scene["character_presence"] = [c for c in char_presence if c.upper() != "KAI"]
            continue

        # ── character_presence is empty — backward compat: use anchor_role ────
        if scene.get("anchor_role") != "primary":
            continue

        # Aerial/overhead shots: Kai cannot be placed meaningfully — drop to absent.
        if _is_aerial_shot(prompt):
            for marker in [KAI_COMPRESSED_SPEC + " —", KAI_COMPRESSED_SPEC]:
                prompt = prompt.replace(marker, "").strip()
            scene["visual_prompt"] = prompt
            scene["anchor_role"] = "absent"
            continue

        if _has_kai_markers(prompt):
            if _has_action_staging(prompt):
                continue  # spec present AND character is acting — correct
            if scene.get("structured_prompt"):
                continue  # V2 generated Kai staging — trust it
            # Spec present but staging is atmospheric — reclassify to absent.
            for marker in [KAI_COMPRESSED_SPEC + " —", KAI_COMPRESSED_SPEC]:
                prompt = prompt.replace(marker, "").strip()
            scene["visual_prompt"] = prompt
            scene["anchor_role"] = "absent"
        elif _has_character_staging(prompt):
            # Guard: if the prompt already describes a story-specific character,
            # injecting Kai would contradict the story.
            if _has_story_specific_character(scene, prompt):
                pass  # leave prompt unchanged — story protagonist is already described
            else:
                scene["visual_prompt"] = f"{KAI_COMPRESSED_SPEC} — {prompt}"
        else:
            scene["anchor_role"] = "absent"
    return scenes


# Used in non-hybrid (pure documentary) mode — photorealistic characters.
_STYLE_FOOTER_HUMAN = (
    "Documentary-quality realism, highly detailed human face, realistic eyes, "
    "authentic skin texture, seamless integration with the environment, "
    "no text, no watermark, photorealistic."
)

# Used in hybrid mode — characters are illustrated, never photorealistic.
_STYLE_FOOTER_ILLUSTRATED = (
    "Illustrated character: clean ink outlines, soft cel shading, painterly storybook "
    "texture — NOT photorealistic. No text, no watermark, no subtitle, no logo."
)

_STYLE_FOOTER_SYMBOLIC = "No text, no watermark, photorealistic."

# Two or more of these in a prompt means a footer is already present (partial or full).
_FOOTER_INDICATORS = [
    "photorealistic",
    "documentary-quality realism",
    "no text, no watermark",
    "highly detailed human face",
    "ink outlines",
    "cel shading",
]


def _has_footer(prompt: str) -> bool:
    """True if the prompt already contains at least two footer indicator phrases."""
    p = prompt.lower()
    return sum(1 for ind in _FOOTER_INDICATORS if ind in p) >= 2


def _strip_partial_footer(prompt: str) -> str:
    """Strip any partial footer indicator phrases to prevent doubling on re-append."""
    for indicator in [
        "documentary-quality realism",
        "no text, no watermark",
        "photorealistic",
        "ink outlines",
        "cel shading",
        "painterly storybook texture",
        "not photorealistic",
        "no subtitle",
        "no logo",
    ]:
        prompt = re.sub(
            rf"[,.]?\s*{re.escape(indicator)}[^.]*\.?",
            "",
            prompt,
            flags=re.IGNORECASE,
        ).strip(" ,.")
    return prompt


def _propagate_environment_anchors(scenes: list[dict]) -> list[dict]:
    """
    For scenes in the same scene_group, ensure the environment anchor from
    the first scene is referenced in all subsequent scenes.

    If a subsequent scene's visual_prompt already opens with "Continuous from
    scene [N]", it is left unchanged. Otherwise the anchor is prepended.
    """
    group_registry: dict[str, tuple[int, str]] = {}

    for scene in scenes:
        group_id = scene.get("scene_group_id")
        if not group_id:
            continue

        scene_id = scene.get("index") or scene.get("scene_id")
        env_anchor = scene.get("environment_anchor") or ""

        if group_id not in group_registry:
            group_registry[group_id] = (scene_id, env_anchor)
        else:
            first_id, anchor = group_registry[group_id]
            prompt = scene.get("visual_prompt", "")
            continuity_prefix = f"Continuous from scene {first_id}"

            if not prompt.startswith(continuity_prefix):
                anchor_clause = f"{anchor} " if anchor else ""
                scene["visual_prompt"] = f"{continuity_prefix}. {anchor_clause}{prompt}"

    return scenes


def _enforce_style_footer(scenes: list[dict], hybrid: bool = False) -> list[dict]:
    """Ensure every visual_prompt ends with the correct style/quality footer.

    Character presence detection priority:
    1. character_presence non-empty → characters are present → illustrated footer
    2. anchor_role in (primary, spectator) → characters present (backward compat) → illustrated footer
    3. Otherwise → symbolic/atmospheric → symbolic footer

    Partial footer phrases are stripped before the full footer is appended so
    phrases never appear twice.
    """
    for scene in scenes:
        char_presence = scene.get("character_presence") or []
        role = scene.get("anchor_role", "absent")
        has_characters = bool(char_presence) or role in ("primary", "spectator")
        prompt = scene.get("visual_prompt", "").rstrip()

        if has_characters:
            footer = _STYLE_FOOTER_ILLUSTRATED if hybrid else _STYLE_FOOTER_HUMAN
            char_marker = "ink outlines" if hybrid else "highly detailed human face"
        else:
            footer = _STYLE_FOOTER_SYMBOLIC
            char_marker = None

        has_full_footer = _has_footer(prompt)
        needs_upgrade = char_marker is not None and char_marker not in prompt.lower()

        if has_full_footer and not needs_upgrade:
            continue  # already complete and correct

        stripped = _strip_partial_footer(prompt)
        scene["visual_prompt"] = f"{stripped} {footer}"

    return scenes




def _enforce_era_consistency(scenes: list[dict]) -> list[dict]:
    """Harmonize era metadata to the dominant era across all generated scenes.

    Prevents visual whiplash from mixing ANCIENT/HISTORICAL/MODERN styles
    in a single video.  TRANSITIONAL scenes are intentional bridges and are
    never overridden.  SYMBOLIC scenes are era-neutral and are left alone.
    """
    gen_scenes = [
        s for s in scenes if s.get("scene_type") not in ("asset", "brand_card")
    ]
    era_counts: dict[str, int] = {}
    for s in gen_scenes:
        vm = s.get("visual_metadata") or {}
        era = (vm.get("era") if isinstance(vm, dict) else getattr(vm, "era", "")) or ""
        if era:
            era_counts[era] = era_counts.get(era, 0) + 1

    if not era_counts:
        return scenes

    dominant_era = max(era_counts, key=era_counts.get)
    if dominant_era in ("SYMBOLIC", "TRANSITIONAL"):
        return scenes

    harmonized = 0
    for s in gen_scenes:
        vm = s.get("visual_metadata") or {}
        if not isinstance(vm, dict):
            continue
        era = vm.get("era", "")
        if era and era != dominant_era and era not in ("TRANSITIONAL", "SYMBOLIC"):
            old_era = era
            vm["era"] = dominant_era
            s["visual_metadata"] = vm
            harmonized += 1
            logger.info(
                "Era consistency: scene {} harmonized {} → {}",
                s.get("index"),
                old_era,
                dominant_era,
            )

    if harmonized > 0:
        logger.info(
            "Era consistency: harmonized {}/{} scenes to dominant era '{}'",
            harmonized,
            len(gen_scenes),
            dominant_era,
        )
    return scenes


# Environment keyword mapping for metadata sync from V2 prompts.
_ENVIRONMENT_KEYWORDS: dict[str, list[str]] = {
    "FOREST": ["forest", "woods", "trees", "grove", "jungle", "woodland", "canopy"],
    "TEMPLE": [
        "temple",
        "shrine",
        "cathedral",
        "church",
        "mosque",
        "chapel",
        "sanctuary",
    ],
    "ASHRAM": ["ashram", "monastery", "hermitage", "retreat", "meditation hall"],
    "KINGDOM": [
        "palace",
        "throne",
        "castle",
        "court",
        "kingdom",
        "fortress",
        "citadel",
    ],
    "BATTLEFIELD": ["battlefield", "battle", "combat", "army", "siege", "warzone"],
    "CITY": [
        "city",
        "street",
        "urban",
        "downtown",
        "skyline",
        "skyscraper",
        "alley",
        "boulevard",
    ],
    "OFFICE": [
        "office",
        "desk",
        "boardroom",
        "corporate",
        "cubicle",
        "conference room",
    ],
    "HOME": [
        "home",
        "house",
        "apartment",
        "kitchen",
        "bedroom",
        "living room",
        "domestic",
        "cottage",
        "hearth",
    ],
    "MOUNTAIN": [
        "mountain",
        "cliff",
        "peak",
        "summit",
        "hill",
        "ridge",
        "highland",
        "alpine",
    ],
    "RIVER": [
        "river",
        "stream",
        "lake",
        "pond",
        "water",
        "shore",
        "bank",
        "ghat",
        "riverbank",
    ],
    "ABSTRACT": ["abstract", "void", "emptiness", "geometric", "surreal"],
    "COSMIC": ["cosmos", "universe", "stars", "galaxy", "celestial", "space", "nebula"],
}


def _sync_metadata_from_v2(scenes: list[dict]) -> list[dict]:
    """Re-derive visual_metadata.environment from the V2 structured prompt.

    After V2, the compiled_prompt may describe a completely different
    environment than the Phase 1 metadata classified.  This pass uses
    keyword matching on environment_prompt to realign the metadata.
    """
    synced = 0
    for scene in scenes:
        sp = scene.get("structured_prompt")
        if not sp:
            continue
        env_prompt = (
            sp.get("environment_prompt", "")
            if isinstance(sp, dict)
            else getattr(sp, "environment_prompt", "")
        ).lower()
        if not env_prompt:
            continue

        vm = scene.get("visual_metadata") or {}
        if not isinstance(vm, dict):
            continue

        best_match = None
        best_count = 0
        for env_type, keywords in _ENVIRONMENT_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in env_prompt)
            if count > best_count:
                best_count = count
                best_match = env_type

        if best_match and best_count >= 1 and vm.get("environment") != best_match:
            old_env = vm.get("environment", "—")
            vm["environment"] = best_match
            scene["visual_metadata"] = vm
            synced += 1
            logger.debug(
                "Metadata sync: scene {} environment {} → {}",
                scene.get("index"),
                old_env,
                best_match,
            )

    if synced > 0:
        logger.info(
            "Metadata sync: updated environment for {}/{} scenes from V2 prompts",
            synced,
            len(scenes),
        )
    return scenes


# ── Scene Planner V2 — Visual Bible + Structured Prompts ─────────────────────


def _load_prompt_file(filename: str) -> str:
    """Load a .md prompt file from src/ytfactory/prompts/."""
    prompt_dir = Path(__file__).parent.parent.parent / "prompts"
    return (prompt_dir / filename).read_text(encoding="utf-8")


def _stub_visual_bible() -> VisualBible:
    return VisualBible(
        dominant_metaphor="A lone figure in a vast world",
        anchor_environments=[
            "Interior space with natural light",
            "Outdoor landscape at golden hour",
        ],
        color_arc={
            "opening": "cool desaturated grey-blue",
            "build": "warming amber tones",
            "climax": "deep gold, shallow depth of field",
            "resolution": "cool blue with one warm accent",
        },
        visual_motifs=["threshold/doorway", "open hands"],
        shot_arc={
            "opening_scenes": "establishing wide",
            "build_scenes": "medium with depth",
            "climax_scene": "tight close-up",
            "resolution_scenes": "medium wide",
        },
    )


# ── Atma 7-Beat narrative constants ───────────────────────────────────────────

# Human-readable purpose for each Atma beat.  Used in prompts and beat metadata.
_BEAT_PURPOSES: dict[str, str] = {
    "DISRUPT": "Open with a provocative premise that hooks attention.",
    "CHALLENGE": "Deepen the conflict — push into tension and uncertainty.",
    "PROVE": "Build evidence and demonstration — show, don't tell.",
    "REVEAL": "The pivotal discovery that reframes everything seen so far.",
    "FRAME": "Contextualize the revelation — provide the conceptual framework.",
    "APPLY": "Bridge from insight to practical consequence — make it actionable.",
    "TRANSFORM": "Close with earned resolution — the world through the changed lens.",
}

# Emotional intensity (0–1) for each beat position — used when script-segments.json
# is absent and we derive intensity from the beat structure directly.
_BEAT_INTENSITIES: dict[str, float] = {
    "DISRUPT": 0.8,
    "CHALLENGE": 0.7,
    "PROVE": 0.6,
    "REVEAL": 0.9,
    "FRAME": 0.6,
    "APPLY": 0.5,
    "TRANSFORM": 0.7,
}


def _make_identity_context(script_identity: dict) -> str:
    """Format ScriptIdentity fields as a concise directive block.

    Used to seed VisualBible and StoryBible generation with the pre-approved
    narrative identity so those systems don't independently reinterpret the
    script. Returns empty string when script_identity is absent (legacy path).
    """
    lines: list[str] = []
    if script_identity.get("core_thesis"):
        lines.append(f"Core thesis: {script_identity['core_thesis'][:200]}")
    if script_identity.get("emotional_promise"):
        lines.append(f"Emotional promise: {script_identity['emotional_promise'][:120]}")
    if script_identity.get("central_conflict"):
        lines.append(f"Central conflict: {script_identity['central_conflict'][:120]}")
    if script_identity.get("important_visual_moments"):
        moments = "; ".join(script_identity["important_visual_moments"][:3])
        lines.append(f"Key visual moments: {moments[:200]}")
    if not lines:
        return ""
    return (
        "APPROVED SCRIPT IDENTITY — align visual choices with these facts; "
        "do not reinterpret:\n"
        + "\n".join(f"- {ln}" for ln in lines)
        + "\n\n"
    )


def _assign_beat_metadata(scenes: list[dict], beats: list[dict]) -> None:
    """Distribute Atma 7-beat structure across scenes and write beat metadata.

    Each generated-image scene receives:
      assigned_beat       — beat name (DISRUPT, CHALLENGE, …)
      beat_index          — 0-based index into beats list
      narrative_purpose   — short description of the beat's role
      is_hook             — True for the opening DISRUPT beat
      resolves_story      — True for the closing TRANSFORM beat

    Also back-fills ``emotional_intensity`` when the scene has no value yet
    (i.e. script-segments.json was absent and _attach_emotional_metadata was
    a no-op for this project).

    When beats is empty the function is a no-op (legacy projects not affected).
    """
    if not beats:
        return
    generated = [
        s for s in scenes if s.get("scene_type", "generated_image") == "generated_image"
    ]
    n = len(generated)
    if n == 0:
        return
    num_beats = len(beats)
    for i, scene in enumerate(generated):
        beat_idx = min(int(i * num_beats / n), num_beats - 1)
        beat_dict = beats[beat_idx]
        beat_name = beat_dict.get("beat", "")
        scene["assigned_beat"] = beat_name
        scene["beat_index"] = beat_idx
        scene["narrative_purpose"] = _BEAT_PURPOSES.get(beat_name, "")
        scene["is_hook"] = beat_idx == 0
        scene["resolves_story"] = beat_idx == num_beats - 1
        if not scene.get("emotional_intensity"):
            scene["emotional_intensity"] = _BEAT_INTENSITIES.get(beat_name, 0.6)


def _make_scene_narrative_context(scene: dict, script_identity: dict) -> str:
    """Build a concise narrative context block for V2 structured prompt.

    Injects the scene's beat assignment and relevant ScriptIdentity fields into
    the per-scene LLM call so the cinematographer prompt aligns with approved
    narrative intent rather than re-deriving it from the narration alone.
    Returns empty string when no Atma data is present (legacy path).
    """
    parts: list[str] = []
    beat = scene.get("assigned_beat", "")
    if beat:
        purpose = _BEAT_PURPOSES.get(beat, "")
        parts.append(
            f"Narrative beat: {beat}"
            + (f" — {purpose}" if purpose else "")
        )
    core_thesis = script_identity.get("core_thesis", "")
    if core_thesis:
        parts.append(f"Core thesis: {core_thesis[:150]}")
    emotional_promise = script_identity.get("emotional_promise", "")
    if emotional_promise:
        parts.append(f"Emotional promise: {emotional_promise[:100]}")
    if not parts:
        return ""
    return (
        "NARRATIVE CONTEXT (from approved Atma script — do not contradict):\n"
        + "\n".join(f"- {p}" for p in parts)
        + "\n"
    )


def _identity_hash(identity: dict) -> str:
    """Return a 16-char SHA-256 hex digest of the identity dict.

    Returns an empty string for an empty/absent identity so legacy projects
    (no script_identity) never invalidate their own caches.
    """
    if not identity:
        return ""
    payload = json.dumps(identity, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _generate_visual_bible(
    script_text: str,
    llm: LLMProvider,
    settings: Settings,
    script_identity_context: str = "",
) -> VisualBible:
    """Single LLM call to produce a VisualBible. Falls back to stub on failure."""
    if not settings.VISUAL_BIBLE_ENABLED:
        return _stub_visual_bible()

    prompt_text = _load_prompt_file("VISUAL_BIBLE_PROMPT.md")
    audience_profile = getattr(settings, "AUDIENCE_PROFILE", "western_english")
    audience_note = ""
    if audience_profile == "western_english":
        audience_note = (
            "\n\nAUDIENCE DIRECTIVE: Target viewer is English-speaking (US/UK/AU/CA). "
            "Anchor environments must feel internationally relevant — European medieval, "
            "Mediterranean, or universally rustic aesthetic. Do NOT default to Indian "
            "architecture (sandstone palaces, elephant carvings, temple ghats) even if "
            "the story originates from Indian philosophy. Rivers, forests, and natural "
            "environments should be culturally neutral.\n"
        )
    identity_block = f"\n{script_identity_context}" if script_identity_context else ""
    full_prompt = f"{prompt_text}{audience_note}{identity_block}\n\nSCRIPT:\n{script_text}"
    try:
        response = llm.generate(full_prompt, temperature=0.4)
        raw = response.text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        data = json.loads(raw)
        return VisualBible(**data)
    except Exception as e:
        logger.warning("VisualBible generation failed: {} — using stub", e)
        return _stub_visual_bible()


def _get_arc_phase(scene_index: int, total_scenes: int) -> str:
    """Map scene position to emotional arc phase."""
    ratio = scene_index / max(total_scenes - 1, 1)
    if ratio < 0.10:
        return "hook"
    elif ratio < 0.20:
        return "opening"
    elif ratio < 0.65:
        return "build"
    elif ratio < 0.80:
        return "climax"
    else:
        return "resolution"


def _arc_to_shot_key(arc_phase: str) -> str:
    mapping = {
        "hook": "opening_scenes",
        "opening": "opening_scenes",
        "build": "build_scenes",
        "climax": "climax_scene",
        "resolution": "resolution_scenes",
    }
    return mapping.get(arc_phase, "build_scenes")


_CAMERA_ANGLE_BY_PHASE = {
    "hook": (
        "low_angle or dramatic close-up — maximum visual impact from the first frame; "
        "grab the viewer's attention with a striking composition that rewards the click"
    ),
    "opening": (
        "eye_level or high_angle — frame characters small against large environments, "
        "emphasise isolation and the scale of the constructed world around them"
    ),
    "build": (
        "eye_level or low_angle — character begins to have presence and agency; "
        "low_angle when a moment of realisation or authority is depicted"
    ),
    "climax": (
        "low_angle or eye_level — maximum character agency; "
        "low_angle for the peak moment of clarity or choice"
    ),
    "resolution": (
        "high_angle easing to eye_level — earned distance; "
        "the world is the same but the character's relationship to it has changed"
    ),
}


def _build_structured_prompt(
    scene: dict,
    visual_bible: VisualBible,
    scene_index: int,
    total_scenes: int,
    llm: LLMProvider,
    settings: Settings,
    prev_scene: dict | None = None,
    story_bible: StoryBible | None = None,
    story_context: str = "",
    narrative_context: str = "",
) -> StructuredImagePrompt:
    """LLM call per scene to produce a StructuredImagePrompt."""
    arc_phase = _get_arc_phase(scene_index, total_scenes)

    style_directive = (
        _load_prompt_file("CINEMATIC_HYBRID_STYLE.md")
        if settings.HYBRID_STYLE_ENABLED
        else ""
    )
    anchor_role = scene.get("anchor_role", "absent")
    pose_rules = (
        _load_prompt_file("KAI_POSE_RULES.md")
        if (anchor_role != "absent" and settings.KAI_POSE_DISCIPLINE_ENABLED)
        else ""
    )
    kai_profile = _load_prompt_file("KAI_PROFILE.md") if anchor_role != "absent" else ""

    audience_profile = getattr(settings, "AUDIENCE_PROFILE", "western_english")
    if audience_profile == "western_english":
        audience_block = (
            "AUDIENCE & VISUAL CHARACTER RULE (strict — apply to every scene):\n"
            "Target viewer: English-speaking (US, UK, AU, CA).\n"
            "1. Characters default to European or Western appearance — clothing, setting, props.\n"
            "   Indian/South Asian ethnic markers (kurta, dhoti, bindi, tilak, charpai, clay pot\n"
            "   arranged in Indian style, Sanskrit scrolls) are FORBIDDEN as generic atmosphere.\n"
            "2. Use Indian/South Asian aesthetic ONLY when the narration explicitly names a specific\n"
            "   Indian person, historical event, or India-specific setting.\n"
            "3. For scholar/sage scenes: use a European academic or monastery aesthetic —\n"
            "   stone study, candlelit library, oak desk, leather-bound books — not a pandit's\n"
            "   home with Sanskrit texts.\n"
            "4. For village/cottage/humble-home scenes: use a Mediterranean, European countryside,\n"
            "   or universally rustic aesthetic — not specifically Indian village architecture.\n"
            "5. Environment and characters must share the same cultural register (no mixing).\n"
        )
    else:
        audience_block = ""

    # Era constraint — prevents modern environments for ancient/historical scenes
    era = (
        (scene.get("visual_metadata") or {}).get("era", "")
        if isinstance(scene.get("visual_metadata"), dict)
        else (getattr(scene.get("visual_metadata"), "era", "") or "")
    )
    _ERA_FORBIDDEN = {
        "ANCIENT": (
            "ERA CONSTRAINT — ANCIENT: Environment MUST pre-date recorded history.\n"
            "Allowed: primordial wilderness, cave interiors, stone-age settlements, open sky, rivers, forests, cliffs.\n"
            "FORBIDDEN: any building with cut stone walls, parchment scrolls, metals, writing, markets, temples,\n"
            "modern architecture, contemporary interiors, offices, electric lighting, or any post-neolithic technology.\n"
        ),
        "HISTORICAL": (
            "ERA CONSTRAINT — HISTORICAL (pre-industrial, medieval or earlier):\n"
            "Allowed: earthen cottages, stone halls, forest clearings, river banks, dirt roads, torch/candle lighting,\n"
            "handmade cloth, wooden furniture, clay/iron vessels.\n"
            "FORBIDDEN: modern architecture, contemporary interiors, corporate offices, glass buildings,\n"
            "electric lighting, current-era technology, modern clothing styles, paved roads, or anything\n"
            "that places the scene after ~1800 CE. This is an absolute hard rule — no exceptions.\n"
        ),
    }
    era_block = _ERA_FORBIDDEN.get(str(era).upper(), "")

    camera_angle_guidance = _CAMERA_ANGLE_BY_PHASE.get(arc_phase, "eye_level")

    bible_context = (
        f"VISUAL BIBLE (apply to this scene):\n"
        f"- Dominant metaphor: {visual_bible.dominant_metaphor}\n"
        f"- Anchor environments: {'; '.join(visual_bible.anchor_environments)}\n"
        f"- This scene's color phase ({arc_phase}): {visual_bible.color_arc.get(arc_phase, '')}\n"
        f"- Recommended shot type: {visual_bible.shot_arc.get(_arc_to_shot_key(arc_phase), '')}\n"
        f"- Recommended camera angle for {arc_phase} phase: {camera_angle_guidance}\n"
        f"- Visual motifs available: {', '.join(visual_bible.visual_motifs)}\n"
    )

    prev_context = ""
    if prev_scene and prev_scene.get("structured_prompt"):
        sp = prev_scene["structured_prompt"]
        prev_env = (
            sp.get("environment_prompt", "")
            if isinstance(sp, dict)
            else getattr(sp, "environment_prompt", "")
        )
        prev_lighting = (
            sp.get("lighting_match", "")
            if isinstance(sp, dict)
            else getattr(sp, "lighting_match", "")
        )[:80]
        prev_focal = (
            sp.get("focal_length", "")
            if isinstance(sp, dict)
            else getattr(sp, "focal_length", "")
        )[:40]
        prev_context = (
            f"PREVIOUS SCENE (scene {scene_index}):\n"
            f"- Environment: {prev_env[:120]}\n"
            f"- Shot type: {sp.get('shot_type', '') if isinstance(sp, dict) else getattr(sp, 'shot_type', '')}\n"
            f"- Color palette: {(sp.get('color_palette_phase', '') if isinstance(sp, dict) else getattr(sp, 'color_palette_phase', ''))[:80]}\n"
            f"- Lighting: {prev_lighting}\n"
            + (f"- Lens: {prev_focal}\n" if prev_focal else "")
            + "⚠ ENVIRONMENT VARIETY RULE (mandatory): This scene MUST use a visually DISTINCT "
            "environment from the scene above. Do NOT repeat the same location type, "
            "dominant setting element, or interior/exterior. If the narration requires the "
            "same physical space, change the framing radically — extreme close-up detail, "
            "a different room, opposite time of day, or a symbolic object within that space.\n"
            "⚠ LIGHTING CONTINUITY RULE: Transition naturally from the previous scene's lighting. "
            "If the previous scene was dawn, do not jump to night unless the narration explicitly "
            "indicates a time change. Natural progression: dawn → morning → midday → afternoon → "
            "golden hour → dusk → night.\n"
        )

    compiled_prompt_rules = (
        (
            "COMPILED_PROMPT ASSEMBLY RULES:\n"
            "1. First line: HYBRID CINEMATIC STYLE compressed directive (≤40 words). MANDATORY — never omit.\n"
            "   Do NOT embed detailed anatomy/lighting/negative-prompt boilerplate inside compiled_prompt —\n"
            "   those live in the style block above. Keep technical rendering words out of individual scenes.\n"
            "2. Shot type, camera angle, and focal_length (e.g. 'Medium shot, eye level, 50mm')\n"
            "3. environment_prompt verbatim — environment must be directly inspired by the scene narration\n"
            "   and respect the AUDIENCE rule above (Western/universal aesthetic unless narration says otherwise).\n"
            "   Do NOT default to an office interior unless narration explicitly describes one.\n"
            "4. If character_staging is not null: write 'Illustrated in hand-painted storybook style — '\n"
            "   then the staging description, then lighting_match. The rendering prefix is MANDATORY so the\n"
            "   image model knows these figures are NOT photorealistic.\n"
            "5. color_palette_phase\n"
            "6. continuity_ref (brief) — if same environment as a previous scene, describe HOW this scene\n"
            "   differs visually (framing, time-of-day, detail focus, mood) so each scene is unique.\n"
            "7. If Kai SPECTATOR scene: Kai must be tiny in the background (5-10% of frame),\n"
            "   partially obscured, no dramatic gestures. Describe him last, briefly.\n"
            "   If Kai PRIMARY scene with OTHER story characters also present: Kai is secondary\n"
            "   in visual scale — describe story characters first, Kai after, slightly smaller or\n"
            "   further back. Kai reacts to the scene, he does not dominate it.\n"
            "   If Kai PRIMARY scene ALONE (no other story characters): Kai is the visual subject.\n"
            "8. STORY BIBLE CLOTHING RULE (CRITICAL): When a LOCKED CHARACTER description exists,\n"
            "   you MUST reproduce their EXACT clothing items (tunic, trousers, boots, belt, cloak,\n"
            "   crown, etc.) in the character_staging. NEVER simplify to 'peasant garb' or 'robes'\n"
            "   when the bible specifies individual garments. NEVER drop footwear — if the bible\n"
            "   says 'worn leather boots', the character wears boots, not barefoot.\n"
            "9. SUPPORTING CHARACTER DISTINCTION: When multiple characters appear, each must be\n"
            "   visually distinguishable by clothing color, garment type, or accessories.\n"
            "   A minister/advisor must NOT look like a second king — use subdued colors (grey,\n"
            "   brown, dark blue), simpler garments, no crown, no royal insignia.\n"
            '10. End with: "16:9 aspect ratio. No text, no watermark, no subtitle, no logo."\n'
        )
        if settings.HYBRID_STYLE_ENABLED
        else (
            "COMPILED_PROMPT ASSEMBLY RULES:\n"
            "1. Shot type, camera angle, and focal_length (e.g. 'Wide shot, high angle, 24mm')\n"
            "2. environment_prompt verbatim — derive from the narration's central idea, not a generic default.\n"
            "3. If character_staging is not null: character_staging + lighting_match\n"
            "4. color_palette_phase\n"
            "5. continuity_ref (brief)\n"
            '6. End with: "16:9 aspect ratio. No text, no watermark, no subtitle, no logo."\n'
        )
    )

    # ── Story Bible context (locked character/location/world descriptions) ──
    story_bible_block = ""
    if story_bible and story_bible.characters:
        scene_analysis_data = scene.get("scene_analysis") or {}
        sb_chars = (
            scene_analysis_data.get("allowed_characters", [])
            if isinstance(scene_analysis_data, dict)
            else getattr(scene_analysis_data, "allowed_characters", [])
        ) or []
        sb_env = (
            scene_analysis_data.get("environment", "")
            if isinstance(scene_analysis_data, dict)
            else getattr(scene_analysis_data, "environment", "")
        ) or ""
        story_bible_block = compose_scene_context(
            bible=story_bible,
            scene_characters=sb_chars,
            scene_environment=sb_env,
            arc_phase=arc_phase,
        )

    # Story state context (dead characters, prop states) injected as a hard constraint
    story_context_block = ""
    if story_context:
        story_context_block = (
            "\n⚠ STORY STATE — IMMUTABLE CONSTRAINTS FROM NARRATIVE CONTINUITY:\n"
            + story_context
            + "\n"
            "Violation of these constraints (e.g. showing a dead character alive, "
            "showing a prop in a state that contradicts the narration) is a critical error.\n"
        )

    system_prompt = (
        "You are a cinematographer writing image generation prompts for a philosophical documentary.\n\n"
        + (f"{style_directive}\n\n" if style_directive else "")
        + (f"{pose_rules}\n\n" if pose_rules else "")
        + (f"{era_block}\n" if era_block else "")
        + (story_context_block if story_context_block else "")
        + f"{bible_context}\n\n"
        + (f"{story_bible_block}\n\n" if story_bible_block else "")
        + (
            f"{audience_block}\n"
            "⚠ AUDIENCE OVERRIDE: If ANY locked character clothing or location description\n"
            "above contradicts the AUDIENCE rule (e.g. dhoti, kurta, Indian palace), the\n"
            "AUDIENCE rule wins. Translate the character/location to the audience-appropriate\n"
            "cultural equivalent while preserving the narrative role and visual function.\n\n"
            if audience_block
            else ""
        )
        + (f"{prev_context}\n\n" if prev_context else "")
        + (f"{narrative_context}\n" if narrative_context else "")
        + f"SCENE POSITION: Scene {scene_index + 1} of {total_scenes}. Arc phase: {arc_phase}.\n\n"
        + "OUTPUT: Respond ONLY with a JSON object matching this schema exactly:\n"
        + "{\n"
        + (
            '  "shot_type": "<one of: establishing_wide|medium|close_up|insert|POV|over_shoulder|silhouette>",\n'
            if anchor_role in ("primary", "spectator")
            else '  "shot_type": "<one of: establishing_wide|medium|close_up|insert|POV|over_shoulder|silhouette|aerial>",\n'
        )
        + '  "camera_angle": "<one of: eye_level|low_angle|high_angle|dutch_tilt>",\n'
        + '  "environment_prompt": "<photorealistic environment description — no character details>",\n'
        + '  "character_staging": "<illustrated character description, or null if no character>",\n'
        + '  "lighting_match": "<one sentence: how character lighting matches environment>",\n'
        + '  "focal_length": "<lens — e.g. 24mm wide-angle, 35mm, 50mm standard, 85mm portrait, 135mm telephoto>",\n'
        + '  "color_palette_phase": "<arc phase + specific palette for this scene>",\n'
        + '  "continuity_ref": "<reference to prev/next scene environment and Kai clothing if applicable>",\n'
        + '  "compiled_prompt": "<full merged prompt for image generator — see assembly rules below>"\n'
        + "}\n\n"
        + "FOCAL LENGTH GUIDE (match to shot_type):\n"
        + "  establishing_wide / aerial → 24mm wide-angle (expansive, environmental scale)\n"
        + "  medium / over_shoulder → 50mm standard (natural perspective, no distortion)\n"
        + "  close_up / insert → 85mm portrait or 100mm macro (shallow DOF, subject isolation)\n"
        + "  POV → 35mm (natural human perspective)\n"
        + "  silhouette → 35mm or 50mm (clean silhouette edges)\n"
        + "  Vary focal length across consecutive scenes — avoid repeating the same lens.\n\n"
        + compiled_prompt_rules
        + "\nNo preamble. No markdown fences. Output only valid JSON."
    )

    # Fix 2: inject allowed_characters from scene_analysis
    scene_analysis = scene.get("scene_analysis") or {}
    if isinstance(scene_analysis, dict):
        allowed = scene_analysis.get("allowed_characters", []) or []
        forbidden = scene_analysis.get("forbidden_characters", []) or []
        required_env = scene_analysis.get("environment", "") or ""
    else:
        allowed = getattr(scene_analysis, "allowed_characters", []) or []
        forbidden = getattr(scene_analysis, "forbidden_characters", []) or []
        required_env = getattr(scene_analysis, "environment", "") or ""

    human_req = (
        scene_analysis.get("human_requirement", "forbidden")
        if isinstance(scene_analysis, dict)
        else getattr(scene_analysis, "human_requirement", "forbidden")
    )

    character_block = ""
    if allowed:
        character_block = (
            "\nIMMUTABLE CHARACTER CONSTRAINTS — follow exactly, no exceptions:\n"
            f"- Allowed characters: {', '.join(allowed)}\n"
            f"- Forbidden characters: {', '.join(forbidden) if forbidden else 'none'}\n"
            f"- Required environment: {required_env if required_env else 'as narrated'}\n"
            '- NEVER substitute "man", "woman", "person", "figure", or "people" for a named entity\n'
            "- Use the EXACT names from the allowed list in character_staging\n"
            '- If a character name feels generic (e.g. "villager"), use it verbatim — do not upgrade\n'
            '  to "man" or "woman"\n'
        )
    elif forbidden and human_req == "forbidden":
        # No allowed characters + forbidden list + confirmed forbidden = no-character scene.
        # Explicit instruction required — without it the LLM invents characters.
        character_block = (
            "\nIMMUTABLE CHARACTER CONSTRAINTS — follow exactly, no exceptions:\n"
            "- character_staging MUST be null. This scene has NO human characters.\n"
            f"- Do NOT depict: {', '.join(forbidden[:6])}{'…' if len(forbidden) > 6 else ''}\n"
            f"- Focus ONLY on the environment: {required_env if required_env else 'as narrated'}\n"
            "- Any human figure, silhouette, or implied presence is a critical violation.\n"
        )
    elif human_req in ("required", "optional", "permitted_symbolic"):
        character_block = (
            "\nCHARACTER GUIDANCE:\n"
            "- The narration describes human characters. Include them in character_staging.\n"
            "- Derive character appearance and action from the narration — do not invent.\n"
            "- If a LOCKED CHARACTER description exists in the Story Bible above, use it\n"
            "  VERBATIM for appearance and clothing. List every garment item individually\n"
            "  (tunic, trousers, belt, boots) — never abbreviate to 'peasant garb' or 'robes'.\n"
            f"- Forbidden characters: {', '.join(forbidden[:6]) if forbidden else 'none'}\n"
            f"- Required environment: {required_env if required_env else 'as narrated'}\n"
        )

    kai_placement_block = ""
    if anchor_role == "spectator":
        kai_placement_block = (
            "\nKAI SPATIAL PLACEMENT (CRITICAL — spectator scene):\n"
            "Kai must be INSIDE the same physical space as the main action, but SUBTLE.\n"
            "Kai is an ambient background figure — NOT a visible observer or witness.\n"
            "If the scene is indoors: Kai stands deep in the background, partially obscured "
            "by a pillar, wall, or shadow — barely noticeable.\n"
            "If the scene is outdoors: Kai stands at the very far edge of the frame, small "
            "in scale, blending into the crowd or environment.\n"
            "Kai must NEVER be in the foreground or midground. He should occupy at most "
            "5-10% of the frame. He should look like he happened to be there, not like he "
            "is watching the main event. No dramatic poses, no gestures, no raised arms.\n"
        )
    elif anchor_role == "primary" and human_req in (
        "required",
        "optional",
        "permitted_symbolic",
    ):
        kai_placement_block = (
            "\nKAI SPATIAL PLACEMENT (PRIMARY with story characters):\n"
            "Story characters are the VISUAL FOCUS. Describe them first, larger, in the\n"
            "foreground or midground. Kai is present and reactive but physically BEHIND or\n"
            "BESIDE the story characters — slightly smaller in frame, never blocking them.\n"
            "Kai occupies at most 15-20% of the frame when story characters are present.\n"
            "Describe Kai AFTER the story characters in the character_staging text.\n"
        )

    # Extract emotional beat for Kai posture selection
    _vm = scene.get("visual_metadata") or {}
    _emotional_beat = (
        _vm.get("mood") if isinstance(_vm, dict) else getattr(_vm, "mood", "")
    ) or ""
    _scene_analysis = scene.get("scene_analysis") or {}
    if not _emotional_beat and _scene_analysis:
        _emotional_beat = (
            _scene_analysis.get("emotional_beat")
            if isinstance(_scene_analysis, dict)
            else getattr(_scene_analysis, "emotional_beat", "")
        ) or ""
    _posture_variant = ("A", "B", "C")[scene.get("index", scene_index) % 3]
    kai_emotion_hint = (
        (
            f"\nSCENE EMOTIONAL BEAT: {_emotional_beat} — "
            f"use POSTURE VARIANT {_posture_variant} from the EMOTION-RESPONSIVE BODY LANGUAGE table above. "
            "Variant letters rotate A→B→C across scenes to prevent consecutive Kai scenes from sharing the same posture.\n"
        )
        if _emotional_beat and anchor_role != "absent"
        else ""
    )

    user_prompt = (
        f"SCENE NARRATION:\n{scene.get('narration', '')}\n\n"
        f"KAI ROLE IN THIS SCENE: {anchor_role}\n"
        + kai_emotion_hint
        + (kai_profile if anchor_role != "absent" else "")
        + kai_placement_block
        + character_block
    )

    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    try:
        response = llm.generate(full_prompt, temperature=0.5)
        raw = response.text.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        data = json.loads(raw)
        sp = StructuredImagePrompt(**data)
        # Guard: LLM sometimes omits the hybrid header for EXPLANATION/ANALOGY/CTA roles.
        # Inject it deterministically so no role ever slips through without it.
        if (
            settings.HYBRID_STYLE_ENABLED
            and not sp.compiled_prompt.lstrip().upper().startswith("HYBRID")
        ):
            data["compiled_prompt"] = (
                _HYBRID_COMPRESSED_PREFIX + " " + sp.compiled_prompt
            )
            sp = StructuredImagePrompt(**data)
        return sp
    except Exception as e:
        logger.warning(
            "StructuredImagePrompt build failed for scene {}: {} — using fallback",
            scene_index + 1,
            e,
        )
        fallback_prompt = scene.get(
            "visual_prompt",
            "cinematic environment. 16:9 aspect ratio. No text, no watermark, no subtitle, no logo.",
        )
        if (
            settings.HYBRID_STYLE_ENABLED
            and not fallback_prompt.lstrip().upper().startswith("HYBRID")
        ):
            fallback_prompt = _HYBRID_COMPRESSED_PREFIX + " " + fallback_prompt
        return StructuredImagePrompt(
            shot_type="medium",
            camera_angle="eye_level",
            environment_prompt=scene.get("visual_prompt", "cinematic environment"),
            character_staging=None,
            lighting_match="Natural cinematic lighting matching the environment.",
            focal_length="50mm standard",
            color_palette_phase=f"{arc_phase}: neutral tones",
            continuity_ref="",
            compiled_prompt=fallback_prompt,
        )


def _validate_visual_continuity(
    scenes: list[dict],
    visual_bible: VisualBible,
) -> list[str]:
    """Post-planning continuity check. Flag-and-log only — never blocks pipeline."""
    warnings: list[str] = []
    scene_count = len(scenes)

    # Check 1: Anchor environment reuse
    anchor_refs = 0
    for scene in scenes:
        if scene.get("structured_prompt"):
            env = (
                scene["structured_prompt"].get("environment_prompt", "").lower()
                if isinstance(scene["structured_prompt"], dict)
                else getattr(
                    scene["structured_prompt"], "environment_prompt", ""
                ).lower()
            )
            for anchor in visual_bible.anchor_environments:
                key_words = anchor.lower().split()[:4]
                if any(w in env for w in key_words):
                    anchor_refs += 1
                    break
    if anchor_refs < max(2, scene_count // 5):
        warnings.append(
            f"CONTINUITY: Anchor environments appear in only {anchor_refs}/{scene_count} scenes. "
            f"Target ≥{max(2, scene_count // 5)} for visual coherence."
        )

    # Check 2: Shot type variety
    shot_types = []
    for s in scenes:
        sp = s.get("structured_prompt")
        if sp:
            st = (
                sp.get("shot_type")
                if isinstance(sp, dict)
                else getattr(sp, "shot_type", None)
            )
            if st:
                shot_types.append(st)
    if shot_types:
        most_common = max(set(shot_types), key=shot_types.count)
        ratio = shot_types.count(most_common) / len(shot_types)
        if ratio > 0.60:
            warnings.append(
                f"CONTINUITY: '{most_common}' used in {shot_types.count(most_common)}/{len(shot_types)} scenes "
                f"({ratio:.0%}). Recommend diversifying shot types."
            )

    # Check 3: Climax scene has tight shot
    climax_index = int(scene_count * 0.70)
    climax_scene = scenes[climax_index] if climax_index < scene_count else None
    if climax_scene:
        sp = climax_scene.get("structured_prompt")
        if sp:
            st = (
                sp.get("shot_type")
                if isinstance(sp, dict)
                else getattr(sp, "shot_type", None)
            )
            if st and st not in ("close_up", "insert", "medium"):
                warnings.append(
                    f"CONTINUITY: Scene {climax_index + 1} (climax position) has shot_type "
                    f"'{st}'. Expected close_up or medium for emotional peak."
                )

    # Check 4: Kai front-facing overuse
    front_facing_count = 0
    for scene in scenes:
        sp = scene.get("structured_prompt")
        if sp and scene.get("anchor_role") == "primary":
            staging = (
                sp.get("character_staging")
                if isinstance(sp, dict)
                else getattr(sp, "character_staging", None)
            )
            if staging:
                staging_lower = staging.lower()
                if (
                    "facing forward" in staging_lower
                    or "front-facing" in staging_lower
                    or "looking directly" in staging_lower
                ):
                    front_facing_count += 1
    if front_facing_count > 1:
        warnings.append(
            f"CONTINUITY: Kai is front-facing in {front_facing_count} scenes. "
            f"Pose discipline allows maximum 1 (climax only)."
        )

    # Check 5: Camera angle variety
    camera_angles = []
    for s in scenes:
        sp = s.get("structured_prompt")
        if sp:
            ca = (
                sp.get("camera_angle")
                if isinstance(sp, dict)
                else getattr(sp, "camera_angle", None)
            )
            if ca:
                camera_angles.append(ca)
    if camera_angles:
        most_common_angle = max(set(camera_angles), key=camera_angles.count)
        angle_ratio = camera_angles.count(most_common_angle) / len(camera_angles)
        if angle_ratio > 0.75:
            warnings.append(
                f"CONTINUITY: camera_angle '{most_common_angle}' used in "
                f"{camera_angles.count(most_common_angle)}/{len(camera_angles)} scenes "
                f"({angle_ratio:.0%}). Add low_angle and high_angle variety per arc phase."
            )

    # Check 6: Consecutive environment duplicates
    _STOP_WORDS = {
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "at",
        "by",
        "with",
        "and",
        "or",
        "is",
        "are",
        "to",
        "from",
        "as",
        "that",
        "this",
        "it",
        "for",
        "its",
        "into",
        "over",
        "under",
        "through",
        "across",
        "between",
        "around",
    }
    env_keywords: list[set[str]] = []
    for scene in scenes:
        sp = scene.get("structured_prompt")
        if sp:
            env = (
                sp.get("environment_prompt", "")
                if isinstance(sp, dict)
                else getattr(sp, "environment_prompt", "")
            )
            words = {
                w
                for w in re.sub(r"[^\w\s]", " ", env.lower()).split()
                if w not in _STOP_WORDS and len(w) > 3
            }
            env_keywords.append(words)
        else:
            env_keywords.append(set())

    for i in range(1, len(env_keywords)):
        a, b = env_keywords[i - 1], env_keywords[i]
        if not a or not b:
            continue
        overlap = len(a & b) / min(len(a), len(b))
        if overlap >= 0.50:
            warnings.append(
                f"CONTINUITY: Scenes {i} and {i + 1} share {overlap:.0%} environment "
                f"keyword overlap — likely duplicate visuals. "
                f"Common words: {', '.join(sorted(a & b)[:6])}"
            )

    # Check 7: Focal length variety
    focal_lengths = []
    for s in scenes:
        sp = s.get("structured_prompt")
        if sp:
            fl = (
                sp.get("focal_length")
                if isinstance(sp, dict)
                else getattr(sp, "focal_length", None)
            )
            if fl:
                focal_lengths.append(fl.split()[0] if fl else "")  # e.g. "50mm"
    if focal_lengths:
        unique_lenses = set(focal_lengths)
        if len(unique_lenses) <= 2 and len(focal_lengths) >= 6:
            warnings.append(
                f"CONTINUITY: Only {len(unique_lenses)} unique focal lengths used across "
                f"{len(focal_lengths)} scenes ({', '.join(sorted(unique_lenses))}). "
                f"Vary lenses: 24mm for wides, 50mm for mediums, 85mm for close-ups."
            )

    for w in warnings:
        logger.warning(w)
    return warnings


@dataclass
class SceneEntities:
    """
    Who and what are literally present in this narration segment.
    Extracted before visual_prompt generation. Injected as a constraint.
    """

    characters: list[str] = field(default_factory=list)
    environment: list[str] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)
    human_classification: HumanClassification = HumanClassification.NO_HUMAN_ALLOWED
    human_names: list[str] = field(default_factory=list)
    human_description: str = ""
    scene_category: Literal[
        "animal_only",
        "human_named",
        "human_implied",
        "human_symbolic",
        "abstract",
        "brand_card",
    ] = "abstract"

    @property
    def has_human(self) -> bool:
        return self.human_classification in (
            HumanClassification.HUMAN_REQUIRED,
            HumanClassification.NAMED_PERSON_REQUIRED,
        )


def _get_cheap_llm(settings: Settings, purpose: str) -> LLMProvider:
    """Return an LLM provider configured for cheap/fast inference."""
    model_override = {
        "extraction": settings.entity_extraction_model,
        "validation": settings.faithfulness_validation_model,
        "llm_validation": settings.faithfulness_validator_model,
    }.get(purpose, "")

    return get_llm_for_role(settings, "validator", model_override=model_override)


def _parse_json_response(text: str) -> dict | None:
    """Parse a JSON object from LLM response text, handling code fences."""
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        raw = raw.strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _extract_scene_entities(narration: str, llm_client: LLMProvider) -> SceneEntities:
    """Extract entity constraints from a narration segment."""
    prompt = ENTITY_EXTRACTION_PROMPT.format(narration=narration)
    response = llm_client.generate(prompt, temperature=0.0)

    data = _parse_json_response(response.text)
    if not data:
        logger.warning(
            "Entity extraction returned invalid JSON; defaulting to abstract"
        )
        return SceneEntities(scene_category="abstract")

    raw_classification = data.get("human_classification", "").lower()
    classification_map = {
        "no_human_allowed": HumanClassification.NO_HUMAN_ALLOWED,
        "human_optional": HumanClassification.HUMAN_OPTIONAL,
        "human_required": HumanClassification.HUMAN_REQUIRED,
        "named_person_required": HumanClassification.NAMED_PERSON_REQUIRED,
        "human_symbolic": HumanClassification.HUMAN_SYMBOLIC,
    }
    human_classification = classification_map.get(
        raw_classification, HumanClassification.NO_HUMAN_ALLOWED
    )

    try:
        return SceneEntities(
            characters=data.get("characters", []) or [],
            environment=data.get("environment", []) or [],
            objects=data.get("objects", []) or [],
            human_classification=human_classification,
            human_names=data.get("human_names", []) or [],
            human_description=data.get("human_description", "") or "",
            scene_category=data.get("scene_category", "abstract") or "abstract",
        )
    except (TypeError, ValueError) as exc:
        logger.warning("Entity extraction malformed: {}; defaulting to abstract", exc)
        return SceneEntities(scene_category="abstract")


def _posthoc_correct_scene_analysis(
    analysis: dict, narration: str, scene_id: int
) -> dict:
    """Deterministic corrections applied immediately after LLM scene analysis.

    Fixes two classes of LLM misclassification that cause downstream failures:
    1. Analogy scenes classified as human_requirement=forbidden when the narration
       describes people through examples ("the person who has a house").
    2. Objects explicitly mentioned in the narration added to forbidden_objects.
    """
    corrected = dict(analysis)
    narration_lower = narration.lower()

    # 1. Upgrade human_requirement from forbidden → permitted_symbolic
    #    when the narration contains analogy/example patterns describing people.
    if corrected.get("human_requirement") == "forbidden":
        for phrase in _STRONG_HUMAN_PHRASES:
            if re.search(r"\b" + re.escape(phrase) + r"\b", narration_lower):
                logger.warning(
                    "posthoc scene {}: upgrading human_requirement "
                    "forbidden → permitted_symbolic (narration contains '{}')",
                    scene_id,
                    phrase,
                )
                corrected["human_requirement"] = "permitted_symbolic"
                break
        if corrected["human_requirement"] == "forbidden":
            for role in _STRONG_HUMAN_ROLES:
                if re.search(r"\b" + re.escape(role) + r"\b", narration_lower):
                    logger.warning(
                        "posthoc scene {}: upgrading human_requirement "
                        "forbidden → required (narration contains '{}')",
                        scene_id,
                        role,
                    )
                    corrected["human_requirement"] = "required"
                    break

    # 2. Remove forbidden_objects whose words appear in the narration.
    forbidden_objs = corrected.get("forbidden_objects") or []
    if forbidden_objs:
        cleaned: list[str] = []
        for obj in forbidden_objs:
            obj_words = obj.lower().split()
            mentioned = any(
                re.search(r"\b" + re.escape(w) + r"\b", narration_lower)
                for w in obj_words
                if len(w) > 2
            )
            if mentioned:
                logger.warning(
                    "posthoc scene {}: removing '{}' from forbidden_objects "
                    "(mentioned in narration)",
                    scene_id,
                    obj,
                )
            else:
                cleaned.append(obj)
        corrected["forbidden_objects"] = cleaned

    return corrected


def _analyze_scene(narration: str, scene_id: int, llm_client: LLMProvider) -> dict:
    """Analyze a single scene for story-first visual grounding."""
    prompt = build_scene_analysis_prompt(narration, scene_id)
    response = llm_client.generate(prompt, temperature=0.0)
    data = _parse_json_response(response.text)
    if not data:
        logger.warning("Scene analysis returned invalid JSON for scene {}", scene_id)
        return {"scene_id": scene_id}
    return data


def _build_entity_block(entities: SceneEntities) -> str:
    """Build the entity constraint section for the visual prompt template."""
    lines = [
        "ENTITY CONSTRAINTS — the following entities were extracted from this narration.",
        "You MUST include ONLY these characters. You MUST NOT add any human figure,",
        "person, man, woman, or body part unless human_classification allows it.",
        "",
        f"  scene_category: {entities.scene_category}",
        f"  human_classification: {entities.human_classification.value}",
    ]
    if entities.characters:
        lines.append(f"  characters_present: {', '.join(entities.characters)}")
    if entities.human_names:
        lines.append(f"  named_humans: {', '.join(entities.human_names)}")
    if entities.human_description:
        lines.append(f"  human_description: {entities.human_description}")
    if entities.environment:
        lines.append(f"  environment: {', '.join(entities.environment)}")
    if entities.objects:
        lines.append(f"  objects: {', '.join(entities.objects)}")
    lines.append("")
    lines.append("VIOLATION EXAMPLES (never do these):")
    lines.append(
        "  - Narration is about an eagle and chick → prompt adds 'a man watching from a cliff' ❌"
    )
    lines.append(
        "  - Narration is about Bhagiratha → prompt adds a generic man in grey linen ❌"
    )
    lines.append(
        "  - Narration is a rhetorical question → prompt shows a specific person ❌"
    )
    lines.append("")
    return "\n".join(lines)


def _build_entity_constraints_section(
    scenes: list[dict], entity_map: dict[int, SceneEntities]
) -> str:
    """Build per-scene entity constraints for the batch prompt."""
    if not entity_map:
        return ""
    lines = ["ENTITY CONSTRAINTS PER SCENE:", ""]
    for scene in scenes:
        idx = scene["index"]
        entities = entity_map.get(idx)
        if not entities:
            continue
        hc_rule = HUMAN_CLASSIFICATION_RULES.get(entities.human_classification, "")
        lines.append(f"Scene {idx}:")
        lines.append(
            f"  category={entities.scene_category}  human_classification={entities.human_classification.value}: {hc_rule}"
        )
        if entities.characters:
            lines.append(f"  characters={', '.join(entities.characters)}")
        if entities.human_names:
            lines.append(f"  named_humans={', '.join(entities.human_names)}")
        if entities.human_description:
            lines.append(f"  human_description={entities.human_description}")
    lines.append("")
    return "\n".join(lines)


def _validate_prompt_faithfulness(
    narration: str,
    entities: SceneEntities,
    visual_prompt: str,
    llm_client: LLMProvider,
) -> tuple[bool, str]:
    """Validate that a visual prompt respects entity constraints.

    Returns (passed: bool, violation_description: str).
    """
    prompt = FAITHFULNESS_VALIDATION_PROMPT.format(
        narration=narration,
        scene_category=entities.scene_category,
        human_classification=entities.human_classification.value,
        visual_prompt=visual_prompt,
    )
    response = llm_client.generate(prompt, temperature=0.0)
    data = _parse_json_response(response.text)
    if not data:
        logger.warning("Faithfulness validation returned invalid JSON")
        return True, ""

    passed = bool(data.get("pass", True))
    violation = data.get("violation", "")
    severity = data.get("severity", "none")
    return passed, violation if severity == "critical" else ""


# ── Task 2.6 Part 2 — LLM validation layer ────────────────────────────────────
# ENVIRONMENT_MISMATCH and HUMAN_CLASSIFICATION_VIOLATED require semantic
# understanding that keyword matching can't reliably provide. Only called when
# these are the ONLY remaining deterministic failures for a scene — never on
# scenes that already pass, never alongside structural failures like
# FORBIDDEN_CHARACTER (fix those via retry first).
LLM_VALIDATABLE_CHECKS: frozenset[str] = frozenset(
    {"ENVIRONMENT_MISMATCH", "HUMAN_CLASSIFICATION_VIOLATED"}
)


def _should_use_llm_validation(error_codes: list[str]) -> bool:
    """True only when every remaining error code is LLM-validatable."""
    return bool(error_codes) and set(error_codes).issubset(LLM_VALIDATABLE_CHECKS)


def _run_llm_validation(
    scene_analysis: dict,
    human_classification: HumanClassification,
    visual_prompt: str,
    llm_client: LLMProvider,
    settings: "Settings | None" = None,
) -> tuple[bool, str]:
    """Binary environment+human check via a cheap LLM call.

    Tries FAITHFULNESS_VALIDATOR_MODEL first, falls back to
    FAITHFULNESS_VALIDATOR_FALLBACK_MODEL on error or invalid JSON.
    Never blocks on total failure — treated as pass so a flaky model
    can't stall the retry loop.
    """
    prompt = build_llm_validation_prompt(
        scene_category=scene_analysis.get("scene_category", "abstract"),
        human_classification=human_classification.value,
        environment=scene_analysis.get("environment", ""),
        visual_prompt=visual_prompt,
    )
    models: list[str | None]
    if settings is not None:
        primary = getattr(settings, "faithfulness_validator_model", None)
        fallback = getattr(settings, "FAITHFULNESS_VALIDATOR_FALLBACK_MODEL", None)
        models = [m for m in [primary, fallback] if m]
    else:
        models = [None]

    for model in models:
        try:
            response = llm_client.generate(
                prompt, json_mode=True, temperature=0.0, model=model
            )
            data = _parse_json_response(response.text)
            if not data:
                logger.warning(
                    "LLM validation returned invalid JSON (model={}) — trying fallback",
                    model,
                )
                continue
            passed = bool(data.get("environment_ok", True)) and bool(
                data.get("human_ok", True)
            )
            return passed, data.get("reason", "")
        except Exception as exc:
            logger.warning(
                "LLM validation call failed (model={}): {} — trying fallback",
                model,
                exc,
            )

    logger.warning("LLM validation failed on all models — accepting prompt")
    return True, "llm_parse_failed: all models exhausted"


# ── Task 2.7 — Narrative-Visual Bridge ────────────────────────────────────────
# Root cause: the generation prompt receives style/entity/camera metadata but
# never an explicit answer to "what does this narration show?" — abstract
# scenes with no extracted characters drift to generic "spiritual documentary
# aesthetic object" imagery. This batch pass derives one concrete, literal
# visual_anchor per scene from its narration before any prompt is generated.

_ANCHOR_FEW_SHOT_EXAMPLES = """\
EXAMPLES (do not output these, they are guidance only):
- Narration: "parents smiling, children smile too" → "A mother kneeling to her child at dawn, both smiling"
- Narration: "if you use your hands you become a karma yogi" → "Skilled hands shaping clay on a potter's wheel"
- Narration: "cannot master the chapati, cannot fight the empire" → "Hands rolling chapati dough with precise, deliberate pressure"
- Narration: "eagle soared with absolute confidence after eight days" → "An eagle in full flight, wings spread against open sky, from below"
- Narration: "he took a simple flower, turned it into bread, built an empire" → "A marigold beside a freshly baked chapati on a woven plate"
- Narration: "even on a simple bed, if your spirit is alive, you feel like a king" → "Two beds side by side — one ornate and cold, one simple and warmly lit\""""


def _build_anchor_batch_prompt(scenes: list[dict]) -> str:
    """Build the batch visual-anchor prompt. Brand-card scenes are excluded —
    they use a fixed asset, not a generated image."""
    scene_lines = [
        f"Scene {scene['index']:03d}: {scene.get('narration', '').strip()}"
        for scene in scenes
        if scene.get("scene_type") != "brand_card"
    ]
    batch_text = "\n".join(scene_lines)

    return f"""\
For each scene below, write ONE sentence describing the single most important
visual element to show in the image. Be specific and literal. Name actual
subjects, actions, or objects from the narration.

Rules:
- Do NOT suggest generic spiritual objects (journal, candle, stone, sandal,
  empty chair, abstract light) unless they appear in the narration.
- DO anchor to a person, animal, action, or object named in the narration.
- If narration describes an emotion/philosophy with no literal subject,
  find the closest concrete metaphor the narration itself suggests.

{_ANCHOR_FEW_SHOT_EXAMPLES}

{batch_text}

Return ONLY JSON: {{"001": "anchor sentence", "002": "anchor sentence", ...}}
No explanation, no markdown, no preamble."""


def _build_visual_anchors(
    scenes: list[dict],
    cheap_llm_client: LLMProvider,
    settings: "Settings | None" = None,
) -> dict[int, str]:
    """Batch call: narration → visual_anchor per scene index.

    Tries VISUAL_ANCHOR_MODEL first, falls back to VISUAL_ANCHOR_FALLBACK_MODEL
    on any failure. Falls back to an empty dict if both fail (non-blocking).
    """
    prompt = _build_anchor_batch_prompt(scenes)
    models: list[str | None]
    if settings is not None:
        models = [
            getattr(settings, "VISUAL_ANCHOR_MODEL", None),
            getattr(settings, "VISUAL_ANCHOR_FALLBACK_MODEL", None),
        ]
    else:
        models = [None]

    for model in models:
        try:
            response = cheap_llm_client.generate(
                prompt, json_mode=True, temperature=0.0, model=model
            )
            data = _parse_json_response(response.text)
            if not data:
                logger.warning(
                    "Visual anchor batch returned invalid JSON (model={}) — trying fallback",
                    model,
                )
                continue
            return {
                int(k): v for k, v in data.items() if isinstance(v, str) and v.strip()
            }
        except Exception as exc:
            logger.warning(
                "Visual anchor attempt failed (model={}): {} — trying fallback",
                model,
                exc,
            )

    logger.warning(
        "Visual anchor batch failed on all models — proceeding without anchors"
    )
    return {}


def _attach_emotional_metadata(project_id: str, scenes: list[dict]) -> None:
    """
    Read script-segments.json (produced by Pass 2 of the script enhancer) and
    attach the closest matching segment to each scene as linked_segment.

    This populates emotional_intensity, is_hook, is_rehook, is_frame_label,
    is_bridge, and resolves_story on every scene — core metadata used by
    motion assignment, pause timing, BGM mixing, and retention scoring.
    """
    script_dir = Path(WORKSPACE_DIR) / project_id / "script"
    segments_path = script_dir / "script-segments.json"
    if not segments_path.exists():
        return

    try:
        data = json.loads(segments_path.read_text(encoding="utf-8"))
        segments = data.get("segments", [])
    except (json.JSONDecodeError, OSError):
        return

    for scene in scenes:
        scene_words = set(scene.get("narration", "").lower().split())
        best_idx = -1
        best_overlap = 0

        for j, seg in enumerate(segments):
            seg_words = set(seg["text"].lower().split())
            overlap = len(scene_words & seg_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_idx = j

        if best_idx >= 0 and best_overlap > 0:
            scene["linked_segment"] = segments[best_idx]


def _extract_all_narrations(script: str) -> list[str]:
    """Extract narration segments from a script for Story Bible generation.

    Reuses the same splitting logic as _split_script_to_scenes but returns
    only the narration text list (no scene dicts).
    """
    scenes = _split_script_to_scenes(script)
    return [s.get("narration", "") for s in scenes if s.get("narration")]


def _split_script_to_scenes(
    script: str, target_words: int = _TARGET_WORDS_PER_SCENE
) -> list[dict]:
    """
    Split a script into scenes using Python only — no LLM, no truncation risk.

    Strategy:
    1. Clean markdown from the text
    2. Split each paragraph into individual sentences
    3. Group consecutive sentences until the bucket reaches ~target_words
    4. Prefer splitting AT paragraph breaks when the bucket is half-full

    Produces ~25-35 scenes from a 700-word script (12-20s each at -20% TTS rate).
    Every word from the script is preserved verbatim.
    """
    # ── 1. Clean residual markdown ─────────────────────────────────────────
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", script, flags=re.DOTALL)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"`(.+?)`", r"\1", text)

    # ── 2. Break into sentences across all paragraphs ─────────────────────
    # Split by paragraph first to respect major section breaks
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    # Regex that splits AFTER sentence-ending punctuation followed by a capital
    _SENT_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-Z\"‘’])")

    all_sentences: list[tuple[str, bool]] = []  # (sentence, is_paragraph_end)
    for para in paragraphs:
        # Also split on single newlines within the paragraph
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        para_text = " ".join(lines)
        sents = _SENT_RE.split(para_text)
        for i, s in enumerate(sents):
            is_last = i == len(sents) - 1
            all_sentences.append((s.strip(), is_last))

    # ── 3. Group sentences into scenes ────────────────────────────────────
    scenes: list[dict] = []
    bucket: list[str] = []
    bucket_words = 0

    def _flush() -> None:
        if not bucket:
            return
        narration = " ".join(bucket)
        narration = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", narration).strip()
        wc = len(narration.split())
        title = " ".join(narration.split()[:4]).rstrip(".,!?...")
        scenes.append(
            {
                "index": len(scenes) + 1,
                "title": title,
                "narration": narration,
                "duration_seconds": max(8, int(wc * 0.5)),
                "visual_prompt": "",
                "visual_metadata": {},
                "scene_type": "generated_image",
                "shot_type": "medium_shot",
            }
        )
        bucket.clear()

    for sentence, is_para_end in all_sentences:
        wc = len(sentence.split())
        would_overflow = bucket_words + wc > target_words * 1.6

        if would_overflow and bucket:
            _flush()
            bucket_words = 0

        bucket.append(sentence)
        bucket_words += wc

        # Flush at paragraph boundaries when bucket is reasonably full
        if is_para_end and bucket_words >= target_words * 0.6:
            _flush()
            bucket_words = 0

    _flush()

    # Post-process: cap hook scenes (first 10%) to shorter durations
    hook_limit = max(2, int(len(scenes) * 0.10))
    for s in scenes[:hook_limit]:
        if s["duration_seconds"] > 6:
            s["duration_seconds"] = 6

    return scenes


def _normalise_closing(text: str) -> str:
    """Lowercase, collapse repeated dots, strip trailing punctuation."""
    import re as _re

    return _re.sub(r"\.{2,}", ".", text.lower().strip()).rstrip(".")


def _is_closing_scene(narration: str) -> bool:
    """
    Return True if this narration belongs to the channel's closing section.

    Matches any scene whose text is a substring of (or contains) a known
    closing phrase.  Checks both:
      - _CLOSING_TRIGGERS — built at module load from the default brand config
      - The current brand config — catches runtime config reloads and
        multi-channel scenarios where config/brand_config.yaml was swapped

    Text is normalised (lowercase, collapsed repeated dots) before comparison
    so a config typo like "Clear mind.." still matches "Clear mind.".
    """
    low = _normalise_closing(narration)

    for trigger in _CLOSING_TRIGGERS:
        t = _normalise_closing(trigger)
        if t in low or low in t:
            return True

    cfg = get_brand_config()
    for text in (cfg.closing.text(), cfg.signature.text(), cfg.cta.text()):
        if text:
            trigger = _normalise_closing(text)
            if trigger and (trigger in low or low in trigger):
                return True

    return False


def _is_opening_scene(narration: str) -> bool:
    """Return True if the narration contains the channel's disabled opening line.

    Used defensively to ensure the opening line can never be folded into the
    closing_block collection by _mark_asset_scenes().
    """
    low = _normalise_closing(narration)
    for trigger in _OPENING_TRIGGERS:
        t = _normalise_closing(trigger)
        if t and (t in low or low in t):
            return True
    return False


def _mark_asset_scenes(scenes: list[dict]) -> list[dict]:
    """
    Post-process the scene list to guarantee the FINAL scene of every render is
    the dedicated brand card asset, with closing/CTA/signature narration attached
    to it — regardless of whether an existing scene's text happens to match
    closing/CTA/signature phrasing.

    Asset path and animation are read from config/brand_config.yaml so no code
    change is needed when switching channels.

    When ``closing_position`` is ``before_final_quote``:
      - Removes every scene whose narration matches closing / CTA / signature
        triggers OR the opening-line trigger, preventing double-ups.
      - Appends a new brand asset card as the final scene with the combined
        narration so the closing is never silently dropped and the last scene
        is always the dedicated brand card.

    Returns the same list, mutated in-place.
    """
    brand_cfg = get_brand_config()

    if not brand_cfg.closing.enabled or not brand_cfg.branding.asset_path:
        logger.debug(
            "branding: skipped closing asset card — closing.enabled={} asset_path={!r}",
            brand_cfg.closing.enabled,
            brand_cfg.branding.asset_path,
        )
        return scenes

    asset_path = brand_cfg.branding.asset_path
    animation = brand_cfg.branding.asset_animation

    parts: list[str] = []
    if brand_cfg.closing.enabled and brand_cfg.closing.text():
        parts.append(brand_cfg.closing.text())
    if brand_cfg.cta.enabled and brand_cfg.cta.text():
        parts.append(brand_cfg.cta.text())
    if brand_cfg.signature.enabled and brand_cfg.signature.text():
        parts.append(brand_cfg.signature.text())
    combined_narration = " ".join(parts)

    def _should_remove(scene: dict) -> bool:
        narration = scene.get("narration", "")
        return _is_closing_scene(narration) or _is_opening_scene(narration)

    scenes[:] = [s for s in scenes if not _should_remove(s)]

    new_scene = {
        "index": len(scenes) + 1,
        "title": "Brand Card",
        "narration": combined_narration,
        "duration_seconds": max(5, int(len(combined_narration.split()) * 0.5)),
        "visual_prompt": "",
        "visual_metadata": {},
        "scene_type": "brand_card",
        "shot_type": "medium_shot",
        "asset_id": asset_path,
        "asset_path": asset_path,
        "animation": animation,
    }
    scenes.append(new_scene)
    logger.info(
        "branding: appended closing asset card as scene {} "
        "with combined narration ({} words)",
        new_scene["index"],
        len(combined_narration.split()),
    )

    return scenes


_BOILERPLATE_SUFFIXES = [
    "16:9 aspect ratio. No text, no watermark, no subtitle, no logo.",
    "No text, no watermark, no subtitle, no logo.",
    "No text, no watermark, photorealistic.",
    "16:9 aspect ratio.",
]


def _strip_image_prompt_boilerplate(prompt: str) -> str:
    """Strip repeated boilerplate suffixes from a prompt for cleaner IMAGE_PROMPTS.md.

    The global instructions header in IMAGE_PROMPTS.md tells the user to
    append these to every prompt, so per-scene repetition is noise.
    """
    result = prompt.rstrip()
    for suffix in _BOILERPLATE_SUFFIXES:
        if result.endswith(suffix):
            result = result[: -len(suffix)].rstrip(" ,.")
    return result


# ---------------------------------------------------------------------------
# Prompt meta-annotation stripper
# ---------------------------------------------------------------------------

_PHASE_LABEL_PAT = re.compile(
    r"\b(hook|build|climax|opening|resolution|transition)\s+phase\s*[—\-–:,]\s*",
    re.IGNORECASE,
)
_META_ANNOTATION_PATTERNS: list[re.Pattern[str]] = [
    # Arc-phase labels: "Hook phase —", "Build phase:", etc.
    _PHASE_LABEL_PAT,
    # Anchor-role justification notes
    re.compile(
        r"Kai\s+absent\s+by\s+immutable\s+scene\s+constraint[^.]*\.?\s*", re.IGNORECASE
    ),
    re.compile(r"anchor_role\s*=\s*\w+\s+because[^.]*\.?\s*", re.IGNORECASE),
    # Pipeline-internal scene-group notes that leaked outside their valid context
    re.compile(r"Scene\s+\d+\s+establishes[^.]*;[^.]*\.\s*", re.IGNORECASE),
]


def _strip_prompt_meta_annotations(prompt: str) -> str:
    """Remove pipeline-internal annotations that must not reach the image generator.

    Phase labels ("Hook phase —"), anchor-role justifications, and scene-planning
    meta-text are generated by the LLM as editorial notes but contaminate the
    visual_prompt when they appear there. This function strips them deterministically
    so the image generator receives only visual descriptions.
    """
    result = prompt
    for pat in _META_ANNOTATION_PATTERNS:
        result = pat.sub("", result)
    # Collapse any double-spaces left by removal
    result = re.sub(r"  +", " ", result).strip()
    return result


_EXPORT_STYLE_HYBRID = (
    "STYLE: Hybrid cinematic — photorealistic environment (architecture, nature, interiors, props); "
    "illustrated storybook characters with ink outlines and cel shading (NOT photorealistic). "
    "16:9 aspect ratio."
)
_EXPORT_STYLE_DOC = "STYLE: Photorealistic documentary cinema. 16:9 aspect ratio."
_EXPORT_GLOBAL_NEGATIVES = (
    "No text, no watermark, no subtitle, no logo. "
    "No photorealistic characters, no realistic human photos, no realistic animals. "
    "No deformed hands, no extra fingers, no mutated or fused limbs."
)


def _env_has_character_contamination(environment_prompt: str) -> bool:
    """True if environment_prompt appears to contain character-staging text.

    Checks the first 200 characters for known character-spec markers that should
    live in character_staging instead.
    """
    env_prefix = environment_prompt.lower()[:200]
    return any(m in env_prefix for m in _CHARACTER_ENV_CONTAMINATION_MARKERS)


def _repair_structured_prompt_dict(
    sp_dict: dict,
    anchor_role: str,
    scene_idx: int,
) -> tuple[dict, list[str]]:
    """Repair inconsistencies in a StructuredImagePrompt dict after LLM generation.

    Detected and repaired:
    1. Character-staging text inside environment_prompt when character_staging is empty.
       The LLM occasionally violates the schema by placing the character description in
       the wrong field. When detected, the text is split at the canonical " — " separator:
       the part before becomes character_staging; the part after becomes environment_prompt.
    2. HYBRID style prefix inside environment_prompt (the LLM included it verbatim).
    3. Duplicate HYBRID style headers in compiled_prompt (logged but not auto-fixed —
       the image generator reads the first header, and the duplicate is redundant noise).

    Returns (repaired_dict, [error_messages]).
    Errors are logged by the caller; the repair never blocks the pipeline.
    """
    errors: list[str] = []
    result = dict(sp_dict)

    character_staging: str = result.get("character_staging") or ""
    environment_prompt: str = result.get("environment_prompt") or ""

    # ── Repair 1: character text in environment_prompt ────────────────────────
    if (
        not character_staging
        and environment_prompt
        and _env_has_character_contamination(environment_prompt)
    ):
        errors.append(
            f"ERROR: Scene {scene_idx} — LLM placed character-staging text inside "
            f"environment_prompt (character_staging is empty). "
            f"Detected marker in: {environment_prompt[:80]!r}"
        )
        sep_idx = environment_prompt.find(_CHAR_ENV_SEPARATOR)
        if sep_idx > 0:
            extracted_char = environment_prompt[:sep_idx].strip()
            extracted_env = environment_prompt[
                sep_idx + len(_CHAR_ENV_SEPARATOR) :
            ].strip()
            result["character_staging"] = extracted_char
            result["environment_prompt"] = extracted_env
            errors.append(
                f"  REPAIRED Scene {scene_idx}: character staging extracted "
                f"('{extracted_char[:80]}...')"
            )
        else:
            errors.append(
                f"  UNREPAIRED Scene {scene_idx}: no ' — ' separator found; "
                "character/environment text remains mixed in environment_prompt."
            )

    # ── Repair 2: HYBRID prefix inside environment_prompt ─────────────────────
    current_env = result.get("environment_prompt") or ""
    if current_env.upper().startswith("HYBRID CINEMATIC STYLE"):
        stripped = (
            current_env[current_env.find(":") + 1 :].strip()
            if ":" in current_env
            else current_env
        )
        result["environment_prompt"] = stripped
        errors.append(
            f"WARNING: Scene {scene_idx} — environment_prompt started with HYBRID "
            "style header; stripped to isolate environment description."
        )

    # ── Check 3: duplicate HYBRID headers in compiled_prompt (log only) ───────
    compiled: str = result.get("compiled_prompt") or ""
    if compiled:
        hybrid_count = compiled.upper().count("HYBRID CINEMATIC STYLE")
        if hybrid_count > 1:
            errors.append(
                f"WARNING: Scene {scene_idx} — compiled_prompt contains "
                f"{hybrid_count} HYBRID style header(s). LLM duplicated the style "
                "directive inside the body. No auto-repair (image generator reads "
                "the first header; duplicate is redundant but not contradictory)."
            )

    return result, errors


def _load_story_bible_for_export(project_id: str) -> "StoryBible | None":
    """Load bible.json from the story-bible workspace directory, if it exists."""
    bible_path = Path(WORKSPACE_DIR) / project_id / "story-bible" / "bible.json"
    if not bible_path.exists():
        return None
    try:
        data = json.loads(bible_path.read_text(encoding="utf-8"))
        return StoryBible(**data)
    except Exception as exc:
        logger.warning("Could not load story bible for export: {}", exc)
        return None


def _assemble_export_prompt(
    scene: dict,
    settings: Settings,
    story_bible: "StoryBible | None" = None,
) -> str:
    """Build a self-contained, semantically-ordered image-generation prompt.

    Semantic priority order (scene-specific content first, global context after):
      1. PRIMARY SUBJECT — who/what must be shown
      2. PRIMARY ACTION  — character posture/action, or environment key element
      3. ENVIRONMENT     — full setting description (character-free)
      4. COMPOSITION     — shot type + camera angle
      5. CAMERA          — focal length
      6. CHARACTER REF   — locked visual reference for characters in this scene only
      7. STYLE           — compact master style directive (global; authoritative)
      8. LIGHTING        — lighting + color palette
      9. CONTINUITY      — continuity note (omitted if empty)
     10. NEGATIVE        — must-not constraints (auto-filtered against positive content)

    Contradiction invariants enforced here:
    - PRIMARY ACTION never says "no character present" when character text exists
      anywhere in the assembled prompt (environment_prompt contamination guard).
    - KAI: character reference block is only emitted when character_staging is
      non-empty.  An empty character_staging means the LLM produced no character
      action for this scene; injecting a KAI block would contradict that.
    - NEGATIVE forbidden_objects items that conflict with the positive content are
      silently dropped and a WARNING is logged.

    Falls back to raw visual_prompt if no structured_prompt exists.
    """
    from ytfactory.images.prompt_validator import (
        check_positive_negative_conflicts,
        validate_prompt_contradictions,
    )

    sp = scene.get("structured_prompt")
    if not sp:
        return _strip_image_prompt_boilerplate(scene.get("visual_prompt", ""))

    if isinstance(sp, dict):
        character_staging: str = sp.get("character_staging") or ""
        environment_prompt: str = sp.get("environment_prompt") or ""
        shot_type: str = (sp.get("shot_type") or "medium").replace("_", " ")
        camera_angle: str = (sp.get("camera_angle") or "eye_level").replace("_", " ")
        focal_length: str = sp.get("focal_length") or "50mm"
        lighting_match: str = sp.get("lighting_match") or ""
        color_palette_phase: str = sp.get("color_palette_phase") or ""
        continuity_ref: str = sp.get("continuity_ref") or ""
    else:
        character_staging = sp.character_staging or ""
        environment_prompt = sp.environment_prompt or ""
        shot_type = (sp.shot_type or "medium").replace("_", " ")
        camera_angle = (sp.camera_angle or "eye_level").replace("_", " ")
        focal_length = sp.focal_length or "50mm"
        lighting_match = sp.lighting_match or ""
        color_palette_phase = sp.color_palette_phase or ""
        continuity_ref = sp.continuity_ref or ""

    anchor_role = scene.get("anchor_role", "absent")
    scene_analysis = scene.get("scene_analysis") or {}
    scene_idx = scene.get("index", 0)

    # ── Pre-flight: detect character text leaked into environment_prompt ──────
    # When the LLM puts character description into environment_prompt instead of
    # character_staging, both fields are inconsistent.  If character_staging is
    # empty but environment_prompt starts with character markers, we cannot
    # safely say "no character present" — that would contradict the environment
    # text.  We detect this state and emit the prompt without the contradictory
    # "no character" action line.
    _env_contaminated = (
        not character_staging
        and bool(environment_prompt)
        and _env_has_character_contamination(environment_prompt)
    )
    if _env_contaminated:
        logger.warning(
            "Scene {}: character staging text found in environment_prompt "
            "(character_staging is empty). Suppressing 'no character present' "
            "action line to avoid contradiction. Run repair pass to fix source data.",
            scene_idx,
        )

    # Clean HYBRID style prefix from environment_prompt (should not appear there)
    if environment_prompt.upper().startswith("HYBRID CINEMATIC STYLE"):
        colon_pos = environment_prompt.find(":")
        if colon_pos >= 0:
            environment_prompt = environment_prompt[colon_pos + 1 :].strip()

    lines: list[str] = []

    # ── 1. PRIMARY SUBJECT ────────────────────────────────────────────────────
    # First identifying clause from character_staging (preferred) or environment.
    # When environment is contaminated with character text, derive subject from
    # the environment portion only (after the " — " separator if present).
    if character_staging:
        first = re.split(r"(?<=[,;—])\s*", character_staging)[0].rstrip(",;— ").strip()
        primary_subject = (
            first if len(first) >= 10 else character_staging.split(".")[0].strip()
        )
    elif _env_contaminated:
        # environment_prompt has character text; extract environment portion if separated
        sep_idx = environment_prompt.find(_CHAR_ENV_SEPARATOR)
        env_for_subject = (
            environment_prompt[sep_idx + len(_CHAR_ENV_SEPARATOR) :].strip()
            if sep_idx >= 0
            else ""
        )
        first = re.split(r"[,.]", env_for_subject)[0].strip() if env_for_subject else ""
        primary_subject = first if len(first) >= 10 else "Symbolic environment"
    else:
        first = re.split(r"[,.]", environment_prompt)[0].strip()
        primary_subject = first if len(first) >= 10 else environment_prompt[:80]
    lines.append(f"PRIMARY SUBJECT: {primary_subject}.")

    # ── 2. PRIMARY ACTION ─────────────────────────────────────────────────────
    # INVARIANT: never say "no character present" when character description exists
    # anywhere in the prompt — that creates an explicit contradiction.
    if character_staging:
        lines.append(f"PRIMARY ACTION: {character_staging}")
    elif not _env_contaminated:
        # Truly no character content in either field → safe to declare environment-only.
        lines.append(
            "PRIMARY ACTION: Environment-only/symbolic scene — no character present."
        )
    # else: environment_prompt has character content → skip contradictory action line.

    # ── 3. ENVIRONMENT ────────────────────────────────────────────────────────
    if environment_prompt:
        lines.append(f"ENVIRONMENT: {environment_prompt}")

    # ── 4. COMPOSITION ────────────────────────────────────────────────────────
    lines.append(f"COMPOSITION: {shot_type.title()} shot, {camera_angle} camera angle.")

    # ── 5. CAMERA ─────────────────────────────────────────────────────────────
    lines.append(f"CAMERA: {focal_length}.")

    # ── 6. CHARACTER REFERENCE — only when character_staging is non-empty ─────
    # INVARIANT: never emit KAI block when character_staging is empty.
    # An empty character_staging means this is either an environment-only scene or
    # the character was placed in environment_prompt (contaminated).  Either way,
    # emitting a KAI: identity block alongside "no character present" text is a
    # direct contradiction.
    char_refs: list[str] = []
    if anchor_role in ("primary", "spectator") and character_staging:
        char_refs.append(f"KAI: {KAI_COMPRESSED_SPEC}.")
    if story_bible and story_bible.characters:
        allowed = (
            scene_analysis.get("allowed_characters", [])
            if isinstance(scene_analysis, dict)
            else getattr(scene_analysis, "allowed_characters", [])
        ) or []
        allowed_lower = {a.lower() for a in allowed}
        for char in story_bible.characters:
            if char.name.lower() in allowed_lower and char.name.lower() != "kai":
                ref = f"{char.appearance}. {char.clothing}".strip(". ")
                char_refs.append(f"{char.name.upper()}: {ref}.")
    for ref in char_refs:
        lines.append(ref)

    # ── 7. STYLE (compact, global — authoritative) ────────────────────────────
    # Global character style constraint is stated here once and takes precedence
    # over any scene-specific style language.  Image generators should read this
    # as the override rule for all character rendering decisions.
    hybrid = getattr(settings, "HYBRID_STYLE_ENABLED", False)
    lines.append(_EXPORT_STYLE_HYBRID if hybrid else _EXPORT_STYLE_DOC)

    # ── 8. LIGHTING + COLOR ───────────────────────────────────────────────────
    lighting_parts: list[str] = []
    if lighting_match:
        lighting_parts.append(lighting_match.rstrip("."))
    if color_palette_phase:
        lighting_parts.append(f"Color: {color_palette_phase}")
    if lighting_parts:
        lines.append(f"LIGHTING: {'. '.join(lighting_parts)}.")

    # ── 9. CONTINUITY ─────────────────────────────────────────────────────────
    if continuity_ref and continuity_ref.strip():
        lines.append(f"CONTINUITY: {continuity_ref.strip()}")

    # ── 10. NEGATIVE CONSTRAINTS ─────────────────────────────────────────────
    # Filter out forbidden_objects items that contradict the positive content.
    # Including a "do not show: lamp" when the scene explicitly depicts a lamp is
    # a direct contradiction that confuses image generators.
    negatives = _EXPORT_GLOBAL_NEGATIVES
    if isinstance(scene_analysis, dict):
        forbidden = scene_analysis.get("forbidden_objects") or []
        if forbidden:
            positive_text = "\n".join(lines)
            conflict_warnings = check_positive_negative_conflicts(
                positive_text, [str(o) for o in forbidden], scene_idx
            )
            for warn in conflict_warnings:
                logger.warning("Positive/negative conflict detected: {}", warn)
            safe_forbidden = [
                str(o)
                for o in forbidden[:8]
                if not any(
                    w in positive_text.lower()
                    for w in str(o).lower().split()
                    if len(w) > 3
                )
            ]
            if safe_forbidden:
                negatives += f" Do not show: {', '.join(safe_forbidden)}."
    lines.append(f"NEGATIVE: {negatives}")

    assembled = "\n".join(lines)

    # ── Post-assembly contradiction check (log only — never blocks) ───────────
    contradictions = validate_prompt_contradictions(assembled, scene_idx)
    for error in contradictions:
        logger.error("PROMPT CONTRADICTION: {}", error)

    return assembled


def _write_prompts_file(
    project_id: str,
    scenes: list[dict],
    style: str | None,
    settings: Settings,
    story_bible: "StoryBible | None" = None,
) -> Path:
    """
    Write IMAGE_PROMPTS.md to the images/ directory.
    Also writes IMAGE_PROMPTS-part-NN.md split files (max 9 prompts each).

    Each exported prompt is assembled from structured scene fields using
    _assemble_export_prompt — semantically ordered, self-contained, zero extra LLM calls.
    """
    if story_bible is None:
        story_bible = _load_story_bible_for_export(project_id)

    images_dir = Path(WORKSPACE_DIR) / project_id / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    abs_images_dir = images_dir.resolve()

    w = settings.image_width
    h = settings.image_height
    total_scenes = len(scenes)
    style_label = style or "documentary"

    primary_scene_ids = [
        s["index"] for s in scenes if s.get("anchor_role") in ("primary", "spectator")
    ]
    first_primary = primary_scene_ids[0] if primary_scene_ids else 1
    primary_scenes_str = ", ".join(str(i) for i in primary_scene_ids)

    lines: list[str] = [
        f"# Image Prompts — {project_id}",
        f"**Style:** {style_label} | **Scenes:** {total_scenes} | **Size:** {w}×{h} px (16:9)",
        "",
        "---",
        "",
    ]

    if getattr(settings, "ANCHOR_CHARACTER_ENABLED", False):
        lines += [
            "## Step 0 — Before You Start (Image Generator Setup)",
            "",
            "**ChatGPT / DALL-E 3:** Paste this message ONCE at the start of a new conversation,",
            "before pasting any scene prompt:",
            "",
            "```",
            f"I am generating a {total_scenes}-scene philosophical documentary storyboard in a MANDATORY hybrid",
            "visual style. You MUST follow this style for every single image without exception.",
            "",
            "⚠️ CRITICAL RULE — TWO-LAYER STYLE (never ignore this):",
            "LAYER 1 — ENVIRONMENT: 100% photorealistic. Architecture, nature, interiors, soil,",
            "trees, props, lighting, and shadows must look like real cinema photography.",
            "LAYER 2 — CHARACTERS: 100% illustrated cartoon. Every human, eagle, bird, or animal",
            "MUST be rendered as a hand-painted storybook illustration — visible ink outlines, flat",
            "cel shading, painterly texture, graphic novel quality. Characters must NEVER look like",
            "real photos. They should look like 2D cartoon characters placed inside a real photograph.",
            "",
            "DO NOT make characters photorealistic. DO NOT make the environment cartoon.",
            "Think of it as: real-world photo background + animated cartoon characters composited on top.",
            "",
            f"ANCHOR CHARACTER (KAI): Appears in scenes {primary_scenes_str}. Kai is a young man,",
            "late 20s, lean build, short dark hair, simple clothing. Render Kai as an illustrated",
            "storybook character (NOT photorealistic) — ink outlines, cel shading, painterly texture.",
            "Kai is almost always shown from behind, in silhouette, or in profile — almost never",
            "full front-facing.",
            "",
            "Keep Kai's illustrated appearance identical across all his scenes. I will paste each",
            "scene prompt one by one now.",
            "```",
            "",
            f"Keep all {total_scenes} generations in ONE conversation window. If style drifts, paste",
            'scene 1 back and say "same hybrid style — continue with scene [X]".',
            "",
            f"**Midjourney / Leonardo:** Generate scene {first_primary} first. Use that as your style",
            "reference (--sref) for all subsequent scenes. For Kai-primary scenes, also use --cref.",
            "",
            "---",
            "",
        ]

    lines += [
        "## Global Instructions (apply to ALL prompts below)",
        "",
        "Append these to every prompt when pasting into a generator:",
        "- **Aspect ratio:** 16:9",
        "- **Character style:** All characters (humans, animals, birds, eagles) MUST be illustrated cartoon style with ink outlines and cel shading — NOT photorealistic",
        "- **Environment style:** Background and environment only are 100% photorealistic cinema photography",
        "- **Negative:** No text, no watermark, no subtitle, no logo, no photorealistic characters, no realistic humans, no realistic animals, no real-photo people",
        "",
        "These lines are stripped from individual prompts below to reduce repetition.",
        "",
        "---",
        "",
        "## How to Use",
        "",
        "1. Copy each prompt below into your preferred image generator.",
        f"2. Generate at **{w}×{h}** resolution (16:9). Any 16:9 size works — it gets resized.",
        "3. Download and **rename** each image to the exact filename shown (e.g. `scene-001.png`).",
        f"4. Place all images in this folder:  \n   `{abs_images_dir}`",
        "5. Re-run the pipeline — placed images are detected automatically and image generation is skipped.",
        "",
        "## Recommended Free Tools",
        "",
        "| Tool | Best for | Link |",
        "|------|----------|------|",
        "| **Leonardo AI** | Photorealistic, free daily credits | https://leonardo.ai |",
        "| **Adobe Firefly** | Safe, commercial-use images | https://firefly.adobe.com |",
        "| **Ideogram** | Text-accurate, stylized | https://ideogram.ai |",
        "| **Midjourney** | Highest quality (paid) | https://midjourney.com |",
        "| **DALL-E 3** | Via ChatGPT, great quality | https://chatgpt.com |",
        "",
        '**Tip:** For this hybrid style in Leonardo AI, use the *Cinematic Kino* or *Photorealism* model for the background, but set the **Alchemy** style to "Illustration" or "Comic Book". Set negative prompt: `text, watermark, logo, blurry, photorealistic characters, realistic humans, realistic animals, real photo people`',
        "",
        "---",
        "",
        "## Re-run Command (after placing images)",
        "",
        "```bash",
        "# Delete old auto-generated scene videos so they re-render with your new images",
        f"rm workspace/jobs/{project_id}/video/scene-*.mp4",
        "",
        "# Re-run — existing images and audio are skipped, only video is rebuilt",
        f'ytfactory run "[your topic]" --project {project_id} --script [your_script.md] --style {style_label} --auto',
        "```",
        "",
        "---",
        "",
    ]

    # Snapshot header content before per-scene blocks — reused in every split file.
    header_lines = list(lines)

    scene_line_groups: list[list[str]] = []
    for scene in scenes:
        idx: int = scene["index"]
        filename = f"scene-{idx:03d}.png"
        save_path = abs_images_dir / filename
        vm = scene.get("visual_metadata", {})
        prompt_display = _assemble_export_prompt(scene, settings, story_bible)
        scene_group: list[str] = [
            f"## Scene {idx} — `{filename}`",
            "",
            f"**Save to:** `{save_path}`",
            "",
            f"**Narration:** _{scene.get('narration', '')}_",
            "",
            "**Image Prompt:**",
            "",
            prompt_display,
            "",
            f"**Visual Metadata:** era={vm.get('era', '—')} role={vm.get('narrative_role', '—')} "
            f"env={vm.get('environment', '—')} mood={vm.get('mood', '—')} "
            f"style={vm.get('visual_style', '—')} modern={vm.get('allow_modern_objects', '—')}",
            "",
            "---",
            "",
        ]
        scene_line_groups.append(scene_group)
        lines.extend(scene_group)

    content = "\n".join(lines)
    out_path = images_dir / "IMAGE_PROMPTS.md"
    out_path.write_text(content, encoding="utf-8")

    _write_split_prompt_files(images_dir, header_lines, scene_line_groups)

    return out_path


MAX_PROMPTS_PER_SPLIT_FILE = 9


def _write_split_prompt_files(
    images_dir: Path,
    header_lines: list[str],
    scene_line_groups: list[list[str]],
) -> None:
    """Write IMAGE_PROMPTS-part-NN.md files, max MAX_PROMPTS_PER_SPLIT_FILE prompts each.

    Every split file is self-contained: full header/global content + its chunk of prompt
    blocks. Stale part files from previous longer runs are removed.
    """
    total = len(scene_line_groups)
    n_parts = math.ceil(total / MAX_PROMPTS_PER_SPLIT_FILE) if total else 0

    existing_parts = sorted(images_dir.glob("IMAGE_PROMPTS-part-*.md"))
    new_part_paths: set[Path] = set()

    for part_idx in range(n_parts):
        start = part_idx * MAX_PROMPTS_PER_SPLIT_FILE
        end = min(start + MAX_PROMPTS_PER_SPLIT_FILE, total)
        chunk = scene_line_groups[start:end]

        part_lines = header_lines.copy()
        for group in chunk:
            part_lines.extend(group)

        part_path = images_dir / f"IMAGE_PROMPTS-part-{part_idx + 1:02d}.md"
        new_part_paths.add(part_path)
        part_path.write_text("\n".join(part_lines), encoding="utf-8")
        logger.debug("Split file {}: scenes {}-{}", part_path.name, start + 1, end)

    for old_path in existing_parts:
        if old_path not in new_part_paths:
            old_path.unlink(missing_ok=True)
            logger.debug("Removed stale split file: {}", old_path.name)

    logger.info(
        "Generated {} prompts — Master: IMAGE_PROMPTS.md ({}) — Splits: {} file{}, max {}/file",
        total,
        total,
        n_parts,
        "s" if n_parts != 1 else "",
        MAX_PROMPTS_PER_SPLIT_FILE,
    )


def _validate_prompt_split(master_path: Path, images_dir: Path) -> list[str]:
    """Validate split prompt files against the master file.

    Returns a list of error strings (empty = all checks passed).
    Deterministic local check — zero LLM calls.
    """
    errors: list[str] = []

    if not master_path.exists():
        return [f"Master file not found: {master_path}"]

    master_content = master_path.read_text(encoding="utf-8")
    master_indices = [
        int(m.group(1))
        for m in re.finditer(r"^## Scene (\d+)", master_content, re.MULTILINE)
    ]
    total = len(master_indices)

    part_paths = sorted(images_dir.glob("IMAGE_PROMPTS-part-*.md"))
    if not part_paths:
        return errors

    split_indices: list[int] = []
    for part_path in part_paths:
        part_content = part_path.read_text(encoding="utf-8")
        part_scene_indices = [
            int(m.group(1))
            for m in re.finditer(r"^## Scene (\d+)", part_content, re.MULTILINE)
        ]
        if len(part_scene_indices) > MAX_PROMPTS_PER_SPLIT_FILE:
            errors.append(
                f"{part_path.name}: {len(part_scene_indices)} prompts exceeds max "
                f"{MAX_PROMPTS_PER_SPLIT_FILE}"
            )
        if not part_scene_indices:
            errors.append(f"{part_path.name}: contains no scene prompt blocks")
        if "## Global Instructions" not in part_content:
            errors.append(
                f"{part_path.name}: missing shared header ('## Global Instructions')"
            )
        split_indices.extend(part_scene_indices)

    if len(split_indices) != total:
        errors.append(f"Split total {len(split_indices)} != master total {total}")
    elif split_indices != master_indices:
        missing = sorted(set(master_indices) - set(split_indices))
        extra = sorted(set(split_indices) - set(master_indices))
        if missing:
            errors.append(f"Missing scenes in splits: {missing}")
        if extra:
            errors.append(f"Extra scenes in splits: {extra}")
        elif split_indices != master_indices:
            errors.append("Scene order in splits does not match master")

    return errors


def _write_faithfulness_gate_report(project_id: str, scenes: list[dict]) -> Path:
    """Evaluate the faithfulness gate and write its result to scenes/faithfulness-gate.json.

    Non-blocking — the gate never raises or halts the pipeline. Failures are
    logged and recorded so a human can review and manually fix flagged image
    prompts in Phase 2. two_phase.pipeline._write_phase1_report() folds this
    file into phase1_report.json under the "faithfulness_gate" key.
    """
    gate_result = evaluate_faithfulness_gate(scenes)
    out_path = Path(WORKSPACE_DIR) / project_id / "scenes" / "faithfulness-gate.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(gate_result.to_dict(), indent=2), encoding="utf-8")
    if gate_result.failed_count:
        console.print(
            f"  [yellow]⚠[/yellow] Faithfulness gate: {gate_result.failed_count} scene(s) FAILED "
            f"— {gate_result.passed_count} PASS, {gate_result.skipped_count} SKIPPED "
            f"[dim](see {out_path})[/dim]"
        )
    else:
        console.print(
            f"  [green]✓[/green] Faithfulness gate passed — "
            f"{gate_result.passed_count} PASS, {gate_result.skipped_count} SKIPPED"
        )
    return out_path


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM JSON responses."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end])
    return text.strip()


_ANCHOR_ROLES: frozenset[str] = frozenset({"primary", "spectator", "absent"})

# Words stripped before comparing prompts for duplication — style boilerplate and
# structural filler that appears in every prompt regardless of scene content.
_VP_BOILERPLATE: frozenset[str] = frozenset(
    {
        "hybrid",
        "cinematic",
        "style",
        "photorealistic",
        "environment",
        "illustrated",
        "hand",
        "painted",
        "storybook",
        "characters",
        "composited",
        "matching",
        "lighting",
        "shadows",
        "shot",
        "angle",
        "color",
        "colour",
        "palette",
        "continuity",
        "aspect",
        "ratio",
        "text",
        "watermark",
        "subtitle",
        "logo",
        "documentary",
        "quality",
        "realism",
        "depth",
        "field",
        "natural",
        "film",
        "grain",
        "image",
        "visual",
        "scene",
        "background",
        "foreground",
        "light",
        "warm",
        "cool",
        "camera",
        "wide",
        "medium",
        "close",
        "level",
        "cast",
        "shadow",
        "glow",
        "soft",
        "dark",
        "deep",
        "long",
        "high",
        "inch",
        # English stop words
        "this",
        "that",
        "with",
        "from",
        "into",
        "over",
        "under",
        "through",
        "across",
        "between",
        "around",
        "their",
        "there",
        "where",
        "which",
        "have",
        "been",
        "each",
        "same",
        "both",
        "will",
        "also",
        "more",
    }
)


_CHARACTER_STRIP_RE = re.compile(
    r"illustrated\s+in\s+hand[- ]painted.*?(?:16[:\s]*9|no text|no watermark|$)",
    re.IGNORECASE | re.DOTALL,
)

# Words specific to character descriptions — stripped when comparing environments.
_CHARACTER_BOILERPLATE: frozenset[str] = frozenset(
    {
        "lean",
        "young",
        "stubble",
        "shirt",
        "trousers",
        "clothing",
        "hair",
        "dark",
        "late",
        "20s",
        "plain",
        "simple",
        "wearing",
        "standing",
        "sitting",
        "facing",
        "profile",
        "posture",
        "pose",
        "variant",
        "back",
        "behind",
        "front",
        "shoulders",
        "arms",
        "hands",
        "pockets",
        "weight",
        "foot",
        "expression",
        "calm",
        "quiet",
        "determined",
        "reflective",
        "thoughtful",
        "peaceful",
        "storybook",
        "illustrated",
        "character",
        "composited",
        "outlines",
        "shading",
        "painterly",
        "realistic",
        "consistent",
        "previous",
    }
)


def _extract_env_words(prompt: str) -> frozenset[str]:
    """Extract environment-describing words from a prompt, stripping
    character descriptions and boilerplate."""
    cleaned = _CHARACTER_STRIP_RE.sub(" ", prompt.lower())
    return frozenset(
        w
        for w in re.sub(r"[^\w\s]", " ", cleaned).split()
        if len(w) > 3 and w not in _VP_BOILERPLATE and w not in _CHARACTER_BOILERPLATE
    )


def _is_prompt_duplicate(
    prompt: str,
    earlier_prompts: dict[int, str],
    threshold: float = 0.65,
) -> int | None:
    """Return the index of the first earlier scene whose prompt has ≥ threshold
    word-overlap with *prompt*, or None if no duplicate is found.

    Uses an overlap coefficient (intersection / min-set-size) so short prompts
    don't trivially match long ones.  Boilerplate terms are stripped first so
    shared style headers don't inflate the score.

    Threshold is 65% — high enough that scenes sharing a story setting (river,
    palace) don't false-positive on shared vocabulary, but low enough to catch
    near-copy-paste duplicates. Environment diversity is handled separately by
    ``_is_environment_duplicate`` (strips characters, checks cluster count).
    """
    words = frozenset(
        w
        for w in re.sub(r"[^\w\s]", " ", prompt.lower()).split()
        if len(w) > 3 and w not in _VP_BOILERPLATE
    )
    if not words:
        return None
    for earlier_idx, earlier_prompt in sorted(earlier_prompts.items()):
        earlier_words = frozenset(
            w
            for w in re.sub(r"[^\w\s]", " ", earlier_prompt.lower()).split()
            if len(w) > 3 and w not in _VP_BOILERPLATE
        )
        if not earlier_words:
            continue
        overlap = len(words & earlier_words) / min(len(words), len(earlier_words))
        if overlap >= threshold:
            logger.debug(
                "Prompt duplication: {:.0%} overlap with scene {:03d}",
                overlap,
                earlier_idx,
            )
            return earlier_idx
    return None


def _is_environment_duplicate(
    prompt: str,
    earlier_prompts: dict[int, str],
    threshold: float = 0.60,
    max_reuses: int = 3,
) -> int | None:
    """Check if this scene reuses a setting that already appears in too many
    earlier scenes.

    A setting can appear up to *max_reuses* times — legitimate story locations
    (river, court) recur 2-3 times. Once *max_reuses* earlier scenes share
    ≥ *threshold* environment overlap with this prompt, the earliest match is
    returned so a DUPLICATE_PROMPT error can be injected.

    Strips character description sections and character-specific words before
    comparing, so "counting room + Kai" vs "counting room + old man" is detected.
    """
    env_words = _extract_env_words(prompt)
    if len(env_words) < 5:
        return None
    matching_earlier: list[int] = []
    for earlier_idx, earlier_prompt in sorted(earlier_prompts.items()):
        earlier_env = _extract_env_words(earlier_prompt)
        if len(earlier_env) < 5:
            continue
        overlap = len(env_words & earlier_env) / min(len(env_words), len(earlier_env))
        if overlap >= threshold:
            matching_earlier.append(earlier_idx)
    if len(matching_earlier) >= max_reuses:
        first_match = matching_earlier[0]
        logger.debug(
            "Environment overuse: {} earlier scenes share this setting "
            "(first match: scene {:03d})",
            len(matching_earlier),
            first_match,
        )
        return first_match
    return None


# Unambiguous human role words: if any of these appear in the narration, the scene
# contains human characters and human_classification=NO_HUMAN_ALLOWED is wrong.
_STRONG_HUMAN_ROLES: frozenset[str] = frozenset(
    {
        "king",
        "queen",
        "minister",
        "priest",
        "elder",
        "merchant",
        "soldier",
        "guard",
        "judge",
        "teacher",
        "master",
        "servant",
        "prince",
        "princess",
        "emperor",
        "crowd",
        "villager",
        "disciple",
        "farmer",
        "doctor",
        "hunter",
        "adviser",
        "advisor",
        "counselor",
        "monk",
        "sage",
        "warrior",
        "general",
        "swimmer",
        "fisherman",
        "shepherd",
        "pilgrim",
        "devotee",
        "speaker",
    }
)

# Multi-word phrases that unambiguously indicate human presence.
# Single-word "man"/"woman" are too generic (mankind, ottoman, etc.) but
# these compound phrases are safe.
_STRONG_HUMAN_PHRASES: tuple[str, ...] = (
    "old man",
    "old woman",
    "young man",
    "young woman",
    "a man who",
    "a woman who",
    "the man who",
    "the woman who",
    "a man of",
    "a woman of",
    "the person who",
    "a person who",
    "anyone who",
    "someone who",
    "whoever has",
    "whoever wants",
    "the one who",
    "his wife",
    "her husband",
    "his family",
    "a family",
    "his body",
    "her body",
    "his heart",
    "her heart",
    "his face",
    "her face",
    "his eyes",
    "her eyes",
)


def _sanitize_scene_analysis(
    scene_analysis: dict,
    entities: "SceneEntities",
    narration: str,
) -> tuple[dict, "SceneEntities"]:
    """Fix obvious entity extraction errors before validation so the validator
    enforces correct constraints instead of guaranteed-false ones.

    Corrects three classes of error that cause every retry to fail:

    1. Active narration participants in forbidden_characters — if a character
       is explicitly named as doing something in the narration (e.g. "Swimmer"
       in a scene about swimming), they cannot be forbidden.

    2. human_classification=NO_HUMAN_ALLOWED when the narration explicitly names
       human roles (king, minister, crowd, etc.) — upgraded to HUMAN_REQUIRED
       so the validator doesn't block prompts that correctly include people.

    3. scene_analysis.human_requirement disagrees with entity extraction —
       the scene analysis (story-first LLM) says humans are required/permitted
       but the entity extraction (narrower LLM) says NO_HUMAN_ALLOWED.
       Trust scene_analysis because it has more narrative context.
    """
    narration_lower = narration.lower()
    sanitized_analysis = dict(scene_analysis)

    # 1. Remove from forbidden_characters any term that appears in allowed_characters
    #    OR that appears as an active participant in the narration.
    allowed_lower = {
        c.lower() for c in (sanitized_analysis.get("allowed_characters") or [])
    }
    forbidden_chars = sanitized_analysis.get("forbidden_characters") or []
    cleaned_forbidden: list[str] = []
    for char in forbidden_chars:
        char_lower = char.lower()
        if char_lower in allowed_lower:
            logger.debug(
                "scene_analysis sanity: removing '{}' from forbidden (also allowed)",
                char,
            )
            continue
        if len(char_lower) > 3 and re.search(
            r"\b" + re.escape(char_lower) + r"\b", narration_lower
        ):
            logger.debug(
                "scene_analysis sanity: removing '{}' from forbidden (active in narration)",
                char,
            )
            continue
        cleaned_forbidden.append(char)
    sanitized_analysis["forbidden_characters"] = cleaned_forbidden

    # 2. Upgrade human_classification if narration contains strong human roles
    #    or unambiguous multi-word human phrases.
    sanitized_entities = entities
    if entities.human_classification == HumanClassification.NO_HUMAN_ALLOWED:
        trigger: str | None = None
        for role in _STRONG_HUMAN_ROLES:
            if re.search(r"\b" + re.escape(role) + r"\b", narration_lower):
                trigger = role
                break
        if trigger is None:
            for phrase in _STRONG_HUMAN_PHRASES:
                if re.search(r"\b" + re.escape(phrase) + r"\b", narration_lower):
                    trigger = phrase
                    break
        if trigger is not None:
            logger.warning(
                "scene_analysis sanity: upgrading human_classification "
                "NO_HUMAN_ALLOWED → HUMAN_REQUIRED (narration contains '{}')",
                trigger,
            )
            sanitized_entities = dc_replace(
                entities, human_classification=HumanClassification.HUMAN_REQUIRED
            )

    # 3. Cross-check scene_analysis.human_requirement against entity extraction.
    if sanitized_entities.human_classification == HumanClassification.NO_HUMAN_ALLOWED:
        hr = sanitized_analysis.get("human_requirement", "forbidden")
        hr_upgrade_map = {
            "required": HumanClassification.HUMAN_REQUIRED,
            "permitted_symbolic": HumanClassification.HUMAN_OPTIONAL,
            "optional": HumanClassification.HUMAN_OPTIONAL,
        }
        target = hr_upgrade_map.get(hr)
        if target is not None:
            logger.warning(
                "scene_analysis sanity: upgrading human_classification "
                "NO_HUMAN_ALLOWED → {} (scene_analysis.human_requirement='{}')",
                target.value,
                hr,
            )
            sanitized_entities = dc_replace(
                sanitized_entities, human_classification=target
            )

    # 4. Upgrade human_requirement="forbidden" when narration has strong human
    #    indicators — prevents V2 from emitting "NO human characters" for scenes
    #    where the narration clearly describes people acting.
    if sanitized_analysis.get("human_requirement") == "forbidden":
        hr_trigger: str | None = None
        for role in _STRONG_HUMAN_ROLES:
            if re.search(r"\b" + re.escape(role) + r"\b", narration_lower):
                hr_trigger = role
                break
        if hr_trigger is None:
            for phrase in _STRONG_HUMAN_PHRASES:
                if re.search(r"\b" + re.escape(phrase) + r"\b", narration_lower):
                    hr_trigger = phrase
                    break
        if hr_trigger is not None:
            logger.warning(
                "scene_analysis sanity: upgrading human_requirement "
                "forbidden → required (narration contains '{}')",
                hr_trigger,
            )
            sanitized_analysis["human_requirement"] = "required"

    # 5. Cap hallucinated forbidden_objects lists.
    #    Normal scenes have 0–10 forbidden objects. A list exceeding the cap
    #    is LLM hallucination (e.g. 370 items dumping every possible noun)
    #    and causes cascading false FORBIDDEN_OBJECT failures.
    _MAX_FORBIDDEN_OBJECTS = 15
    forbidden_objs = sanitized_analysis.get("forbidden_objects") or []
    if len(forbidden_objs) > _MAX_FORBIDDEN_OBJECTS:
        logger.warning(
            "scene_analysis sanity: clearing {} hallucinated forbidden_objects "
            "(normal range 0–10, threshold {})",
            len(forbidden_objs),
            _MAX_FORBIDDEN_OBJECTS,
        )
        sanitized_analysis["forbidden_objects"] = []

    # 6. Remove forbidden_objects that the narration explicitly mentions.
    #    If the narration says "gold" or "coin", forbidding "gold coins" is wrong.
    forbidden_objs = sanitized_analysis.get("forbidden_objects") or []
    if forbidden_objs:
        cleaned_objs: list[str] = []
        for obj in forbidden_objs:
            obj_words = obj.lower().split()
            narration_mentions = any(
                re.search(r"\b" + re.escape(w) + r"\b", narration_lower)
                for w in obj_words
                if len(w) > 2
            )
            if narration_mentions:
                logger.debug(
                    "scene_analysis sanity: removing '{}' from forbidden_objects "
                    "(mentioned in narration)",
                    obj,
                )
            else:
                cleaned_objs.append(obj)
        if len(cleaned_objs) < len(forbidden_objs):
            logger.warning(
                "scene_analysis sanity: removed {} forbidden_objects mentioned in narration",
                len(forbidden_objs) - len(cleaned_objs),
            )
        sanitized_analysis["forbidden_objects"] = cleaned_objs

    return sanitized_analysis, sanitized_entities


def _parse_visual_prompts(text: str) -> list[dict] | None:
    """Parse Phase-2 output: [{index, visual_prompt, visual_metadata?}].

    Handles several LLM output styles:
    - Clean JSON array
    - JSON inside ```json...``` code fences (anywhere in the response)
    - Per-scene separate arrays on separate lines
    - JSON array anywhere in text (regex fallback)

    visual_metadata is optional for backward compatibility with cached plans
    or LLM responses that omit it.
    """

    def _valid(items: list) -> bool:
        return bool(items and all("index" in i and "visual_prompt" in i for i in items))

    raw = _strip_fences(text)

    # ── Try 1: whole stripped text is valid JSON ──────────────────────────
    try:
        data = json.loads(raw)
        items = (
            data.get("scenes", data.get("prompts", []))
            if isinstance(data, dict)
            else data
        )
        if isinstance(items, list) and _valid(items):
            return items
    except json.JSONDecodeError:
        pass

    # ── Try 2: JSON array inside a code fence block (Claude-style output) ─
    import re as _re

    for fence_re in [r"```json\s*(\[.*?\])\s*```", r"```\s*(\[.*?\])\s*```"]:
        m = _re.search(fence_re, text, _re.DOTALL)
        if m:
            try:
                items = json.loads(m.group(1))
                if isinstance(items, list) and _valid(items):
                    return items
            except json.JSONDecodeError:
                pass

    # ── Try 3: multiple separate JSON arrays on separate lines ────────────
    items = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, list):
                items.extend(obj)
        except json.JSONDecodeError:
            pass
    if _valid(items):
        return items

    # ── Try 4: find first [...] JSON array anywhere in text ───────────────
    m = _re.search(r"(\[[\s\S]*?\])\s*(?:```|$|\n\n)", text)
    if m:
        try:
            items = json.loads(m.group(1))
            if isinstance(items, list) and _valid(items):
                return items
        except json.JSONDecodeError:
            pass

    return None


def _generate_vp_sub_batches(
    llm: LLMProvider,
    batch: list[dict],
    style: str,
    visual_diary: list[str],
    entity_constraints_section: str = "",
    scene_analysis_section: str = "",
) -> list[dict] | None:
    """Retry a truncated batch by splitting it in half and calling each half separately."""
    half = max(1, len(batch) // 2)
    merged: list[dict] = []
    for sub in [batch[:half], batch[half:]]:
        if not sub:
            continue
        sub_prompt = build_visual_prompts_prompt(
            sub,
            style,
            prev_context=visual_diary or None,
            entity_constraints_section=entity_constraints_section,
            scene_analysis_section=scene_analysis_section,
        )
        sub_resp = llm.generate(sub_prompt, temperature=0.35)
        if sub_resp.finish_reason == "length":
            logger.warning(
                "Sub-batch {}-{} still truncated after split — accepting partial results",
                sub[0]["index"],
                sub[-1]["index"],
            )
        sub_list = _parse_visual_prompts(sub_resp.text)
        if sub_list:
            merged.extend(sub_list)
    return merged or None


# ── Cinematic Pacing System ────────────────────────────────────────────────────

_VALID_MUSIC_ACTIONS: frozenset[str] = frozenset(
    {
        "continue",
        "continue_softly",
        "slight_swell",
        "emotional_swell",
        "resolve",
        "fade",
        "fade_to_silence",
        "hold",
    }
)

# Imported at call site from the prompts module — defined here for node-level validation.
_VALID_MOODS: frozenset[str] = frozenset(
    {
        "neutral",
        "reflective",
        "building",
        "dramatic",
        "resolving",
        "fading",
    }
)

# Default music entry used when the LLM omits or mis-formats a field.
_DEFAULT_MUSIC: dict = {"action": "continue", "mood": "neutral", "intensity": 0.5}


def _parse_music_fields(val: dict) -> dict:
    """Extract and validate music fields from a parsed pacing dict entry."""
    action = str(val.get("action", "continue"))
    if action not in _VALID_MUSIC_ACTIONS:
        action = "continue"
    mood = str(val.get("mood", "neutral"))
    if mood not in _VALID_MOODS:
        mood = "neutral"
    try:
        intensity = float(val.get("intensity", 0.5))
        intensity = max(0.0, min(1.0, intensity))
    except (TypeError, ValueError):
        intensity = 0.5
    return {"action": action, "mood": mood, "intensity": intensity}


def _run_pacing_pass(
    scenes: list[dict],
    llm_client: LLMProvider,
) -> dict[int, dict]:
    """Single batch LLM call → per-scene pacing dict.

    Returns {scene_index: {"enabled": bool, "duration": float,
                           "music": {"action": str, "mood": str, "intensity": float}}}.
    Non-blocking: on any failure returns an empty dict so scenes render unchanged.
    """
    if not scenes:
        return {}

    prompt = build_pacing_prompt(scenes)
    try:
        response = llm_client.generate(prompt, temperature=0.0, json_mode=True)
        raw = _parse_json_response(response.text)
        if not isinstance(raw, dict):
            logger.warning("Pacing LLM returned non-dict; skipping pacing pass")
            return {}
    except Exception as exc:
        logger.warning("Pacing LLM call failed: {} — skipping pacing pass", exc)
        return {}

    result: dict[int, dict] = {}
    for key, val in raw.items():
        try:
            idx = int(key)
        except (ValueError, TypeError):
            continue
        if not isinstance(val, dict):
            continue

        enabled = bool(val.get("enabled", False))
        try:
            duration = float(val.get("duration", 0.0))
        except (TypeError, ValueError):
            duration = 0.0
        if not enabled:
            duration = 0.0

        result[idx] = {
            "enabled": enabled,
            "duration": duration,
            "music": _parse_music_fields(val),
        }

    return result


def _apply_director_pass(
    scenes: list[dict],
    pacing_map: dict[int, dict],
) -> dict[int, dict]:
    """Pure-Python global review pass — enforces distribution without an LLM call.

    Rules enforced (in order):
    1. No consecutive reflection beats — remove the shorter of any adjacent pair.
    2. Final generated (non-asset) scene always gets an ending reflection ≥5.0s.
    3. If total reflections exceed 25% of scene count, trim lowest-priority ones
       (those with "continue" action and shortest duration, excluding final).
    """
    gen_scenes = [
        s for s in scenes if s.get("scene_type") not in ("asset", "brand_card")
    ]
    if not gen_scenes:
        return pacing_map

    pacing = dict(pacing_map)  # copy — don't mutate the input

    def _default_entry() -> dict:
        return {"enabled": False, "duration": 0.0, "music": dict(_DEFAULT_MUSIC)}

    # Ensure every scene has an entry (default = no reflection)
    for s in gen_scenes:
        if s["index"] not in pacing:
            pacing[s["index"]] = _default_entry()

    # Rule 1: no consecutive reflection beats
    indices = [s["index"] for s in gen_scenes]
    for i in range(1, len(indices)):
        prev_idx = indices[i - 1]
        curr_idx = indices[i]
        prev = pacing.get(prev_idx, {})
        curr = pacing.get(curr_idx, {})
        if prev.get("enabled") and curr.get("enabled"):
            # Keep the longer; disable the shorter
            if curr.get("duration", 0) >= prev.get("duration", 0):
                pacing[prev_idx]["enabled"] = False
                pacing[prev_idx]["duration"] = 0.0
            else:
                pacing[curr_idx]["enabled"] = False
                pacing[curr_idx]["duration"] = 0.0

    # Rule 2: final generated scene must have an ending reflection ≥5.0s
    final_idx = gen_scenes[-1]["index"]
    final_p = pacing.setdefault(final_idx, _default_entry())
    if not final_p.get("enabled") or final_p.get("duration", 0.0) < 5.0:
        final_p["enabled"] = True
        final_p["duration"] = max(5.0, final_p.get("duration", 0.0))
        final_p["music"] = {
            "action": "continue_softly",
            "mood": "reflective",
            "intensity": 0.3,
        }

    # Rule 3: trim excess reflections (>25%)
    max_allowed = max(2, int(len(gen_scenes) * 0.25))
    enabled_indices = [idx for idx in indices if pacing.get(idx, {}).get("enabled")]
    if len(enabled_indices) > max_allowed:
        # Candidates: exclude final; prefer "continue" action and shortest duration
        removable = sorted(
            [i for i in enabled_indices if i != final_idx],
            key=lambda i: (
                pacing[i].get("music", {}).get("action", "continue") == "continue",
                -pacing[i].get("duration", 0.0),
            ),
            reverse=True,
        )
        for idx in removable[: len(enabled_indices) - max_allowed]:
            pacing[idx]["enabled"] = False
            pacing[idx]["duration"] = 0.0

    enabled_count = sum(1 for i in indices if pacing.get(i, {}).get("enabled"))
    logger.info(
        "Cinematic Pacing: {}/{} scenes with reflection beats (director pass applied)",
        enabled_count,
        len(gen_scenes),
    )
    return pacing


def _extract_narrative_ending(script: str) -> str:
    """Strip brand wrap and return the last narrative sentence."""
    brand_markers = [
        "This is Atma Theory",
        "If this reflection resonated",
        "Clear mind",
        "Meaningful life",
        "stay with us on the journey",
    ]
    lines = script.strip().split("\n")
    for i, line in enumerate(lines):
        if any(marker in line for marker in brand_markers):
            for j in range(i - 1, -1, -1):
                if lines[j].strip():
                    return lines[j].strip()
    return lines[-1].strip()


_QUALITY_GATE_PROMPT = """\
You are a script quality reviewer. Run all 4 checks below on the script.
For EACH check, output PASS or FAIL and, on FAIL, one sentence describing the specific problem.

CRITICAL GATE INSTRUCTIONS — you must follow these exactly, they override your own judgment:

- For the hook-to-ending loop check: you will be given a NARRATIVE_ENDING field.
  Evaluate ONLY that field. Do not read the script's final lines. Do not consider
  anything after the narrative ending. If NARRATIVE_ENDING echoes the opening image,
  this check PASSES. Full stop.

- For the no repeated beats check: the following progressions are ALWAYS allowed and
  must NEVER be flagged as repeated beats:
  (a) A story observation about the eagle → followed by a human parallel making the
      same point = pipeline formula, not repetition
  (b) A fear/identity point in the story section → a fear/identity conclusion in the
      philosophical section = arc progression, not repetition
  Only flag repeated beats if the EXACT SAME POINT appears TWICE within the SAME
  section (both in story, or both in human parallel) with nothing new between them.

- For the no disclaimer paragraphs check: the following are NEVER disclaimer paragraphs
  and must NEVER be flagged:
  (a) Any sentence containing "Not a promise" or "Not a demand" inside a practice or
      action section — this is framing, not disclaiming
  (b) Any story beat describing a character's situation, fear, or fate
  (c) Any philosophical statement about fear, identity, impermanence, or the human condition
  (d) Any paragraph that translates a story beat into a universal principle —
      e.g. "The traveler lost his life — this is what distraction costs"
      or "The body we depend on is temporary" following a story's climax
  (e) Any philosophical teaching that follows directly from the narrative
  Only flag if a paragraph makes factual claims about the real world (statistics,
  medical claims, financial advice) with no story grounding, OR directly tells the
  viewer what to do in their real life without connecting it to a story beat.

CHECKS:
1. SINGLE_VISUAL_WORLD — Does only one metaphor/visual universe exist throughout the script?
   FAIL if more than one distinct visual world is introduced (e.g. an eagle story, then an unrelated lamp metaphor).
2. NO_REPEATED_BEATS — Does every paragraph advance the script?
   A repeated beat is when the EXACT SAME POINT appears TWICE within the SAME narrative stage
   (both in story, or both in human parallel) with nothing new between them.
   A story beat followed by its human-parallel equivalent is the pipeline formula — NEVER a repeated beat.
   FAIL only if the identical idea appears twice within the same section with no development.
3. HOOK_ENDING_LOOP — Does NARRATIVE_ENDING echo or resolve the opening image?
   Evaluate ONLY the NARRATIVE_ENDING field provided below. Ignore the script's final lines entirely.
   FAIL only if NARRATIVE_ENDING does not echo or resolve the opening image or tension.
4. NO_DISCLAIMER_PARAGRAPHS — Is all hardship or limitation shown through story or character?
   FAIL only if a paragraph makes factual claims about the real world (statistics, medical claims,
   financial advice) with no story grounding, OR directly tells the viewer what to do in their real
   life without connecting it to a story beat (e.g. "Poverty is real. Loss is real. These are hard truths.").
   NEVER flag: story beats, practice framing ("Not a promise..."), philosophical statements about
   fear/identity/impermanence, paragraphs that translate a story beat into a universal principle
   ("The body we depend on is temporary" after a story climax), or philosophical teachings that
   follow directly from the narrative arc.

NARRATIVE_ENDING (pre-extracted, brand wrap already stripped — use this for check 3):
{narrative_ending}

SCRIPT:
{script}

Respond ONLY with this JSON, nothing else:
{{
  "single_visual_world": {{"result": "PASS"|"FAIL", "reason": ""}},
  "no_repeated_beats": {{"result": "PASS"|"FAIL", "reason": ""}},
  "hook_ending_loop": {{"result": "PASS"|"FAIL", "reason": ""}},
  "no_disclaimer_paragraphs": {{"result": "PASS"|"FAIL", "reason": ""}}
}}
"""


class ScriptQualityGateError(RuntimeError):
    """Raised when the script fails the quality gate before scene planning."""


def _run_script_quality_gate(script_md: str, llm: LLMProvider) -> None:
    """Run the 4-check quality gate on the script. Raises ScriptQualityGateError if any check fails.

    Non-blocking on LLM/parse failure — logs a warning and passes through so a broken
    gate model can't silently halt every pipeline run.
    """
    narrative_ending = _extract_narrative_ending(script_md)
    prompt = _QUALITY_GATE_PROMPT.format(
        script=script_md[:6000], narrative_ending=narrative_ending
    )
    try:
        response = llm.generate(prompt, temperature=0.0)
        raw = response.text.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("Script quality gate LLM call failed ({}); skipping gate", exc)
        return

    failures: list[str] = []
    check_labels = {
        "single_visual_world": "Single visual world",
        "no_repeated_beats": "No repeated beats",
        "hook_ending_loop": "Hook-to-ending loop",
        "no_disclaimer_paragraphs": "No disclaimer paragraphs",
    }
    for key, label in check_labels.items():
        check = data.get(key, {})
        if isinstance(check, dict) and check.get("result") == "FAIL":
            reason = check.get("reason", "no reason provided")
            failures.append(f"[{label}] {reason}")

    if failures:
        msg = (
            "SCRIPT QUALITY GATE FAILED — fix these issues before scene planning:\n"
            + "\n".join(f"  ✗ {f}" for f in failures)
        )
        raise ScriptQualityGateError(msg)

    logger.info("Script quality gate: all 4 checks passed")


def _inject_continuity_context(
    scenes: list[dict],
    scene_analysis_map: dict,
) -> StoryState:
    """Build StoryState and inject story_context + action_constraints into each scene dict.

    Called from BOTH the fresh-generation path and the cached idempotency path so that
    every scene dict always carries up-to-date continuity data regardless of whether
    a new plan was generated or an existing one was loaded from disk.
    """
    story_state = build_story_state(scenes, scene_analysis_map)
    for _s in scenes:
        if _s.get("scene_type", "generated_image") != "generated_image":
            continue
        _idx = _s["index"]
        _narration = _s.get("narration", "")
        _s["story_context"] = story_state.get_story_context_for_scene(_idx)
        _s["action_constraints"] = build_action_constraints_block(_narration)
    return story_state


def scene_planner_node(state: VideoState) -> dict:
    """
    Scene Planner Agent:
    1. Script quality gate (4 checks) — halts pipeline if script fails
    2. Load script from state / disk
    3. Generate scene plan JSON with retry loop on parse failure
    4. Validate and fix duration totals
    5. Second-pass: enhance visual prompts with cinematography guidance
    6. Save scene-plan.json + scene-plan.md
    """
    settings = Settings()
    llm = get_llm_for_role(settings, "scene_planner")
    artifact_repo = ArtifactRepository()
    project_repo = ProjectRepository()

    topic = state["topic"]
    project_id = state["project_id"]
    style = state.get("style")

    # Atma Theory narrative intelligence — present for new Atma projects, absent for legacy.
    beats: list[dict] = state.get("beats") or []
    script_identity_dict: dict = state.get("script_identity") or {}
    identity_context = _make_identity_context(script_identity_dict)

    project_repo.update_stage(project_id, "scenes", "running")
    style_label = f" [{style}]" if style else ""
    console.print(
        f"\n[bold cyan]🎬 Scene Planner Agent[/bold cyan]{style_label} — "
        f"planning scenes for: [italic]{topic}[/italic]\n"
    )

    # ── Idempotency: load existing plan from disk if available ────────────
    existing_plan_path = Path(WORKSPACE_DIR) / project_id / "scenes" / "scene-plan.json"
    current_id_hash = _identity_hash(script_identity_dict)
    if existing_plan_path.exists():
        existing = json.loads(existing_plan_path.read_text(encoding="utf-8"))
        cached_id_hash = existing.get("identity_hash", "")
        if cached_id_hash != current_id_hash:
            # Identity has changed since the plan was generated — the cached
            # VisualBible and scene prompts were not seeded with the current
            # ScriptIdentity.  Invalidate and fall through to full regeneration.
            logger.info(
                "scene_planner: identity_hash mismatch (cached={!r} current={!r}) — "
                "invalidating cached plan and regenerating",
                cached_id_hash, current_id_hash,
            )
            console.print(
                "  [yellow]↻[/yellow] Scene plan identity changed — regenerating..."
            )
        else:
            scenes = existing.get("scenes", [])

            for _scene in scenes:
                if "visual_metadata" not in _scene:
                    _scene["visual_metadata"] = {}
                if not _scene.get("anchor_role"):
                    _scene["anchor_role"] = "absent"

            # Defensive: strip heading prefix from scene 1 narration if it leaked from
            # a run before this fix was in place.  Patches the cached JSON in-place so
            # subsequent reads are already clean (idempotent — heading_text won't match
            # after first strip).  Three fallback sources for the heading text:
            #   1. script_md in graph state  2. script.md on disk  3. project title
            _raw_script = state.get("script_md", "") or ""
            if not _raw_script:
                _sp = Path(WORKSPACE_DIR) / project_id / "script" / "script.md"
                if _sp.exists():
                    _raw_script = _sp.read_text(encoding="utf-8")
            _, _heading = strip_script_heading(_raw_script) if _raw_script else ("", "")
            if not _heading:
                _proj = project_repo.load(project_id)
                _heading = _proj.title.upper() if _proj and _proj.title else ""
            if _heading:
                _heading_text = _heading.strip()
                for _scene in scenes:
                    _narration = _scene.get("narration", "")
                    if _narration.startswith(_heading_text):
                        _scene["narration"] = _narration[len(_heading_text) :].lstrip(
                            " ,.:;"
                        )
                        existing_plan_path.write_text(
                            json.dumps({"scenes": scenes}, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        # Subtitles always rebuild from narration, but audio and video are
                        # skipped when the file already exists.  Delete stale files so the
                        # next generate-voice / render run picks up the corrected text.
                        _idx = _scene.get("index", 0)
                        _job_dir = Path(WORKSPACE_DIR) / project_id
                        for _stale in [
                            _job_dir / "audio" / f"scene-{_idx:03d}.mp3",
                            _job_dir / "video" / f"scene-{_idx:03d}.mp4",
                        ]:
                            if _stale.exists():
                                _stale.unlink()
                                logger.info(
                                    "Deleted stale {} for scene {:03d} after heading-strip patch",
                                    _stale.name,
                                    _idx,
                                )
                        break

            total = sum(s.get("duration_seconds", 0) for s in scenes)
            console.print(
                f"  [green]✓[/green] Loaded existing scene plan — "
                f"{len(scenes)} scenes, ~{total / 60:.1f} min (skipping LLM calls)"
            )

            # Re-apply brand-card guarantee so cached plans (including plans from
            # before this fix) always end with the dedicated brand card asset.
            scenes = _mark_asset_scenes(scenes)

            # ── Atma beat metadata upgrade for cached plans ───────────────────
            # Plans pre-dating Atma integration lack assigned_beat.  When beats
            # are present in state, run beat assignment once so cached scenes
            # carry the same metadata as freshly generated scenes.  Idempotent:
            # if assigned_beat is already on all scenes (same beats, re-run), the
            # existing values are preserved by _assign_beat_metadata's intensity guard.
            if beats and not any(s.get("assigned_beat") for s in scenes):
                _assign_beat_metadata(scenes, beats)
                console.print(
                    f"  [green]✓[/green] Cached plan upgraded: beat metadata assigned "
                    f"({len(beats)} beats → "
                    f"{len([s for s in scenes if s.get('assigned_beat')])} scenes)"
                )

            # ── Re-inject story context for cached plans ─────────────────────
            # Scenes loaded from disk have story_context="" (the planner's idempotency
            # early-return previously skipped all continuity code).  Rebuild the
            # analysis map from the scene_analysis stored per-scene, then call the
            # shared helper so every scene receives fresh story_context and
            # action_constraints before the plan is written back to disk.
            _cached_analysis_map: dict[int, Any] = {
                _s["index"]: _s["scene_analysis"]
                for _s in scenes
                if _s.get("scene_analysis")
            }
            if _cached_analysis_map:
                _cached_story_state = _inject_continuity_context(
                    scenes, _cached_analysis_map
                )
                _cached_findings = ContinuityValidator(_cached_story_state).validate_all(
                    scenes, _cached_analysis_map
                )
                _cached_errors = [f for f in _cached_findings if f.is_error()]
                _cached_warnings = [f for f in _cached_findings if f.is_warning()]
                if _cached_errors:
                    for _f in _cached_errors:
                        logger.error("STORY CONTINUITY (cached): {}", str(_f))
                    console.print(
                        f"  [bold red]⚠ {len(_cached_errors)} story continuity errors "
                        f"in cached plan[/bold red]"
                    )
                if _cached_warnings:
                    for _f in _cached_warnings:
                        logger.warning("STORY CONTINUITY WARNING (cached): {}", str(_f))
                    console.print(
                        f"  [yellow]⚠ {len(_cached_warnings)} story continuity warnings[/yellow]"
                    )
                console.print(
                    f"  [green]✓[/green] Story context refreshed — "
                    f"{len(_cached_story_state.characters)} chars, "
                    f"{len(_cached_story_state.props)} props"
                )

            existing_plan_path.write_text(
                json.dumps({"scenes": scenes}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            prompts_path = _write_prompts_file(project_id, scenes, style, settings)
            console.print(f"  [green]✓[/green] Image prompts: [dim]{prompts_path}[/dim]")
            _write_faithfulness_gate_report(project_id, scenes)
            project_repo.update_stage(project_id, "scenes", "completed")
            return {"scene_plan": scenes}

    # Load script — prefer state, fall back to disk
    script_md = state.get("script_md", "")
    if not script_md:
        script_path = Path(WORKSPACE_DIR) / project_id / "script" / "script.md"
        if not script_path.exists():
            raise FileNotFoundError("Script not found. Run script-writer first.")
        script_md = script_path.read_text(encoding="utf-8")

    # Strip leading H1 heading — it is a structural label, not spoken narration.
    script_md, _ = strip_script_heading(script_md)

    # Remove duplicate consecutive brand-signature lines that can accumulate
    # when Pass 2 of the script enhancer re-appends closing/CTA phrases.
    lines = script_md.splitlines()
    if lines:
        deduped = [lines[0]]
        for line in lines[1:]:
            if line.strip() != deduped[-1].strip():
                deduped.append(line)
        script_md = "\n".join(deduped)

    # ── V2: Generate Visual Bible once before per-scene planning ─────────────
    if settings.VISUAL_BIBLE_ENABLED:
        console.print("  [cyan]→[/cyan] V2: generating visual bible...")
    visual_bible = _generate_visual_bible(
        script_md, llm, settings, script_identity_context=identity_context
    )
    if settings.VISUAL_BIBLE_ENABLED:
        console.print(
            f'  [green]✓[/green] Visual Bible: "{visual_bible.dominant_metaphor[:60]}..."'
        )

    # ── Story Bible: locked character/location/world descriptions ─────────
    story_bible = StoryBible()
    if settings.VISUAL_BIBLE_ENABLED:
        console.print(
            "  [cyan]→[/cyan] Generating Story Bible (characters, locations, world)..."
        )
        all_narrations = _extract_all_narrations(script_md)
        story_bible = load_or_generate_story_bible(
            project_id=project_id,
            workspace_dir=WORKSPACE_DIR,
            narrations=all_narrations,
            llm=llm,
            audience_profile=getattr(settings, "AUDIENCE_PROFILE", "western_english"),
            script_identity_context=identity_context,
        )
        # Sync color progression from VisualBible into StoryBible
        if visual_bible.color_arc:
            story_bible.style.color_progression = visual_bible.color_arc.copy()
        if story_bible.characters or story_bible.locations:
            console.print(
                f"  [green]✓[/green] Story Bible: "
                f"{len(story_bible.characters)} characters, "
                f"{len(story_bible.locations)} locations, "
                f"{len(story_bible.do_not_change)} locked rules"
            )

    # ── Script Quality Gate — must pass before any scene planning ────────────
    console.print("  [cyan]→[/cyan] Script quality gate: running 4 checks...")
    try:
        _run_script_quality_gate(script_md, llm)
        console.print("  [green]✓[/green] Script quality gate: all checks passed")
    except ScriptQualityGateError as _gate_err:
        console.print(
            f"\n  [bold red]✗ SCRIPT QUALITY GATE FAILED[/bold red]\n{_gate_err}\n"
        )
        project_repo.update_stage(project_id, "scenes", "failed")
        raise PipelineAbort("scene_planner", str(_gate_err)) from _gate_err

    # ── Phase 1: Python-based script splitting (no LLM, no truncation risk) ──
    # The LLM was reliably failing to return 25+ scenes in one JSON response —
    # Groq cuts off mid-stream when output tokens get large. Python splitting is
    # deterministic, instant, and preserves every word verbatim.
    console.print("  [cyan]→[/cyan] Phase 1: splitting script into scenes...")
    scenes: list[dict] = _split_script_to_scenes(script_md)

    # Detect channel closing scenes and mark them as asset scenes so that
    # image generation is skipped and the brand card is used instead.
    _mark_asset_scenes(scenes)
    asset_count = sum(
        1 for s in scenes if s.get("scene_type") in ("asset", "brand_card")
    )
    if asset_count:
        brand_asset = get_brand_config().branding.asset_path
        console.print(
            f"  [green]✓[/green] {asset_count} closing scene(s) marked as asset scenes "
            f"[dim]({brand_asset})[/dim]"
        )

    # Attach emotional metadata from script-segments.json (produced by Pass 2
    # of the script enhancer). This is core metadata used by motion, pauses,
    # music, and retention scoring downstream.
    _attach_emotional_metadata(project_id, scenes)

    # For Atma projects: assign beat metadata from the approved 7-beat structure.
    # This runs after _attach_emotional_metadata so beat-derived values only fill
    # in where script-segments.json did not already provide them (emotional_intensity).
    if beats:
        _assign_beat_metadata(scenes, beats)
        console.print(
            f"  [green]✓[/green] Atma beat metadata: {len(beats)} beats → "
            f"{len([s for s in scenes if s.get('assigned_beat')])} scenes assigned"
        )

    # ── Scene Analysis (NEW) — structured story-first grounding per scene ─────
    console.print("  [cyan]→[/cyan] Analyzing scenes for story-first grounding...")
    _analysis_llm = _get_cheap_llm(settings, "extraction")
    scene_analysis_map: dict[int, dict] = {}
    for scene in scenes:
        if scene.get("scene_type", "generated_image") == "generated_image":
            analysis = _analyze_scene(
                scene.get("narration", ""), scene["index"], _analysis_llm
            )
            analysis = _posthoc_correct_scene_analysis(
                analysis, scene.get("narration", ""), scene["index"]
            )
            scene_analysis_map[scene["index"]] = analysis
            scene["scene_analysis"] = analysis
            # Propagate narrative_phase to the top-level scene dict so downstream
            # stages (SSML enhancer, motion engine) can read it without unwrapping
            # scene_analysis.  Falls back to UNKNOWN if LLM didn't classify.
            raw_phase = analysis.get("narrative_phase", "") if isinstance(analysis, dict) else ""
            scene["narrative_phase"] = emotion_policy.parse_phase(raw_phase).value
    scene_analysis_section = build_scene_analysis_section(scene_analysis_map)
    console.print(
        f"  [green]✓[/green] Scene analysis complete for {len(scene_analysis_map)} scenes"
    )

    # ── Emotional diversity validation ───────────────────────────────────────
    _gen_scenes = [s for s in scenes if s.get("scene_type", "generated_image") == "generated_image"]
    _phase_seq = [s.get("narrative_phase", "UNKNOWN") for s in _gen_scenes]
    _passes, _distinct, _families = emotion_policy.validate_script_diversity(_phase_seq)
    if _passes:
        logger.info(
            "Emotion diversity: {} distinct families — PASS (min {})",
            _distinct, 5,
        )
    else:
        logger.warning(
            "Emotion diversity: only {} distinct families ({}) — BELOW MINIMUM of 5. "
            "Script may be emotionally flat. Check narrative_phase assignments.",
            _distinct, ", ".join(_families),
        )
        console.print(
            f"  [yellow]⚠ Emotion diversity: {_distinct} distinct families "
            f"(min 5). Script may be emotionally flat.[/yellow]"
        )
    _adj_warnings = emotion_policy.validate_adjacent_continuity(
        _phase_seq,
        [emotion_policy.get_target(emotion_policy.parse_phase(p)).primary for p in _phase_seq],
    )
    for _scene_idx, _adj_msg in _adj_warnings:
        logger.warning("Adjacent continuity: {}", _adj_msg)

    # ── Story State — track characters/props across scenes ───────────────────
    # Must run AFTER scene_analysis_map is populated and BEFORE Phase 2 prompts,
    # so each scene's context block can be injected into its visual prompt.
    # _inject_continuity_context calls build_story_state internally and writes
    # story_context + action_constraints into every generated-image scene dict.
    story_state = _inject_continuity_context(scenes, scene_analysis_map)
    console.print(
        f"  [green]✓[/green] Story state: {len(story_state.characters)} characters, "
        f"{len(story_state.props)} props tracked"
    )

    total = sum(s.get("duration_seconds", 0) for s in scenes)
    narration_words = sum(len(s.get("narration", "").split()) for s in scenes)
    console.print(
        f"  [green]✓[/green] {len(scenes)} scenes — "
        f"{narration_words} words — {total:.0f}s (~{total / 60:.1f} min)"
    )

    # ── V4: Enrich scenes with shot types before Phase 2 ─────────────────
    _v4_engine = ImagePromptEngineV4()
    scenes = _v4_engine.enrich_scenes_with_shots(scenes)
    shot_plan = _v4_engine.get_shot_plan(scenes)
    console.print(
        f"  [cyan]→[/cyan] V4 shot plan: "
        f"{len(set(shot_plan))} distinct types across {len(shot_plan)} scenes"
    )

    # ── Phase 2: Visual prompts — use the configured LLM provider ───────────
    # Batch size: 10 scenes keeps each batch well under an 8192-token proxy cap (~500 tok/prompt).
    # Groq uses 7 (tighter output limit). If the proxy returns finish_reason=length the batch
    # is automatically split in half and retried by _generate_vp_sub_batches().
    # Asset scenes are excluded — they have no visual_prompt and skip image generation.
    _VP_BATCH = 7 if settings.llm_provider.lower() == "groq" else 10
    generated_scenes = [
        s for s in scenes if s.get("scene_type", "generated_image") == "generated_image"
    ]

    # ── Layer 1: Entity Extraction Pass ──────────────────────────────────
    _extraction_llm = _get_cheap_llm(settings, "extraction")
    entity_map: dict[int, SceneEntities] = {}
    for scene in generated_scenes:
        entities = _extract_scene_entities(scene.get("narration", ""), _extraction_llm)
        entity_map[scene["index"]] = entities
        logger.debug(
            "Entity extraction scene {:03d}: category={} human_classification={} chars={}",
            scene["index"],
            entities.scene_category,
            entities.human_classification.value,
            entities.characters,
        )
    entity_constraints_section = _build_entity_constraints_section(
        generated_scenes, entity_map
    )

    # ── Narrative-Visual Bridge (Task 2.7) ────────────────────────────────
    # Runs after entity extraction, before prompt generation, so abstract/
    # empty-chars scenes get a concrete literal directive instead of drifting
    # to generic aesthetic imagery. Non-blocking: on any failure scenes
    # generate exactly as before this task.
    _llm_validation_client = _get_cheap_llm(settings, "llm_validation")
    if settings.visual_anchor_enabled:
        visual_anchors = _build_visual_anchors(
            generated_scenes, _llm_validation_client, settings
        )
    else:
        visual_anchors = {}
    for scene in generated_scenes:
        scene["visual_anchor"] = visual_anchors.get(scene["index"], "")
    if visual_anchors:
        console.print(
            f"  [green]✓[/green] Visual anchors: {len(visual_anchors)}/{len(generated_scenes)} scenes"
        )

    # ── Cinematic Pacing System ───────────────────────────────────────────────
    # Single batch call → per-scene reflection beats + music actions.
    # Director pass (pure Python) enforces distribution targets.
    # Non-blocking: if LLM fails, scenes get no pacing metadata and render unchanged.
    if settings.cinematic_pacing_enabled:
        console.print(
            "  [cyan]→[/cyan] Cinematic Pacing: assigning reflection beats..."
        )
        _pacing_llm = _get_cheap_llm(settings, "extraction")
        pacing_map = _run_pacing_pass(generated_scenes, _pacing_llm)
        if pacing_map:
            pacing_map = _apply_director_pass(scenes, pacing_map)
            for scene in scenes:
                idx = scene["index"]
                p = pacing_map.get(idx)
                if p:
                    scene["scene_pacing"] = {
                        "reflection": {
                            "enabled": p["enabled"],
                            "duration": p["duration"],
                        },
                        "music": p["music"],
                    }
            enabled_count = sum(
                1
                for s in scenes
                if s.get("scene_pacing", {}).get("reflection", {}).get("enabled")
            )
            console.print(
                f"  [green]✓[/green] Pacing: {enabled_count}/{len(generated_scenes)} "
                f"reflection beats assigned"
            )
        else:
            console.print(
                "  [yellow]⚠[/yellow] Pacing LLM failed — proceeding without reflection beats"
            )

    console.print(
        f"  [cyan]→[/cyan] Phase 2: generating visual prompts "
        f"[dim]({settings.llm_provider}, batches of {_VP_BATCH}, "
        f"{len(generated_scenes)}/{len(scenes)} scenes)[/dim]..."
    )
    vp_map: dict[int, str] = {}
    _vm_map: dict[int, dict] = {}
    _ar_map: dict[int, str] = {}
    _faithfulness_qa: dict[int, dict] = {}
    visual_diary: list[
        str
    ] = []  # cross-batch continuity: short summaries of prompts already written

    for batch_start in range(0, len(generated_scenes), _VP_BATCH):
        batch = generated_scenes[batch_start : batch_start + _VP_BATCH]
        batch_nums = f"{batch[0]['index']}–{batch[-1]['index']}"
        prompt = build_visual_prompts_prompt(
            batch,
            style,
            prev_context=visual_diary or None,
            entity_constraints_section=entity_constraints_section,
            scene_analysis_section=scene_analysis_section,
        )
        vp_response = llm.generate(prompt, temperature=0.35)

        # If the proxy hit its output token cap, split the batch and retry each half.
        # Parsing a truncated response risks silently dropping the last N scenes.
        if vp_response.finish_reason == "length":
            logger.warning(
                "Batch {} hit output token limit ({} tokens) — splitting into sub-batches",
                batch_nums,
                vp_response.completion_tokens,
            )
            vp_list = _generate_vp_sub_batches(
                llm, batch, style, visual_diary, entity_constraints_section
            )
        else:
            vp_list = _parse_visual_prompts(vp_response.text)
            # Retry once on parse failure
            if vp_list is None:
                logger.warning("Batch {} parse failed — retrying", batch_nums)
                vp_response = llm.generate(prompt, temperature=0.35)
                vp_list = _parse_visual_prompts(vp_response.text)

        if vp_list:
            expected_indexes = [s["index"] for s in batch]
            returned_indexes = [item["index"] for item in vp_list]

            # Safety net: if LLM reset indexes (e.g. returned 1-7 instead of 15-21),
            # remap by position so the correct scenes get their prompts.
            if returned_indexes != expected_indexes and len(vp_list) == len(batch):
                logger.warning(
                    "Batch {} — LLM returned indexes {} instead of {}; remapping by position",
                    batch_nums,
                    returned_indexes,
                    expected_indexes,
                )
                for item, scene in zip(vp_list, batch):
                    vp_map[scene["index"]] = item["visual_prompt"]
                    if "visual_metadata" in item:
                        _vm_map[scene["index"]] = item["visual_metadata"]
                    if item.get("anchor_role") in _ANCHOR_ROLES:
                        _ar_map[scene["index"]] = item["anchor_role"]
            else:
                for item in vp_list:
                    vp_map[item["index"]] = item["visual_prompt"]
                    if "visual_metadata" in item:
                        _vm_map[item["index"]] = item["visual_metadata"]
                    if item.get("anchor_role") in _ANCHOR_ROLES:
                        _ar_map[item["index"]] = item["anchor_role"]

            # Update visual diary for the next batch — first ~72 chars capture subject + environment
            for scene in batch:
                if scene["index"] in vp_map:
                    summary = vp_map[scene["index"]][:72].rstrip(",. ")
                    visual_diary.append(f"Sc.{scene['index']}: {summary}")
            visual_diary = visual_diary[-14:]  # keep the 14 most recent entries

            console.print(
                f"  [green]✓[/green] Scenes {batch_nums} — {len(vp_list)} prompts"
            )
        else:
            logger.warning(
                "Visual prompt batch {} returned malformed JSON after retry; using fallback",
                batch_nums,
            )

    # ── Layer 3: Story Fidelity Validation ─────────────────────────────────
    # Per-scene generate -> validate -> structured-retry loop. Replaces the old
    # two-system design (inline story-fidelity retry + a separate batch
    # "Retrying N failed prompt(s)" phase) that fired a second, differently-shaped
    # retry request after all scenes were already processed and could never parse
    # the result. See docs/script/task-2.2-retry-engine-reliability.md.
    console.print("  [cyan]→[/cyan] Validating prompt fidelity...")
    _validation_llm = _get_cheap_llm(settings, "validation")
    validation_issues = 0
    max_retries = settings.scene_planner_max_retries
    use_json_mode = settings.scene_planner_json_mode

    # Collect all allowed_characters across the entire story so a character
    # that appears in ANY scene's analysis (e.g. "old man" in scene 3) is
    # recognized as a real story character everywhere — not just in the
    # scenes where the entity extractor happened to list it.
    _story_characters: set[str] = set()
    for _sc in generated_scenes:
        for _ch in _sc.get("scene_analysis", {}).get("allowed_characters") or []:
            _story_characters.add(_ch)

    for scene in generated_scenes:
        idx = scene["index"]
        current_prompt = vp_map.get(idx, "")
        if not current_prompt:
            continue
        entities = entity_map.get(idx)
        if not entities:
            continue

        scene_analysis = scene.get("scene_analysis", {})
        # Correct entity extraction errors before the validation loop runs —
        # wrong forbidden_characters or NO_HUMAN_ALLOWED on a scene with people
        # makes the validator impossible to satisfy on any attempt.
        scene_analysis, entities = _sanitize_scene_analysis(
            scene_analysis, entities, scene.get("narration", "")
        )
        attempt = 0
        last_violation = ""
        final_status = FaithfulnessStatus.FAILED
        attempts = 0
        critical_error_codes: list[str] = []
        llm_validated = False
        llm_reason_text = ""

        while attempt <= max_retries:
            deterministic_result = run_validators(
                scene_analysis=scene_analysis,
                prompt=current_prompt,
                narration=scene.get("narration", ""),
                human_classification=entities.human_classification,
                scene_category=entities.scene_category,
                visual_anchor=scene.get("visual_anchor", ""),
                story_characters=_story_characters,
            )

            # Duplicate-prompt check: if this scene's prompt is ≥65% lexically
            # similar to any earlier scene's finalized prompt, inject a critical
            # DUPLICATE_PROMPT error so the retry loop regenerates it fresh.
            # Only compare against scenes with a LOWER index (earlier in video)
            # whose prompts are already finalized in vp_map.
            earlier_vp = {k: v for k, v in vp_map.items() if k < idx}
            dup_of = _is_prompt_duplicate(current_prompt, earlier_vp)
            if dup_of is None:
                dup_of = _is_environment_duplicate(current_prompt, earlier_vp)
            if dup_of is not None:
                logger.warning(
                    "Scene {:03d} | attempt {} | DUPLICATE of scene {:03d} — forcing retry",
                    idx,
                    attempt,
                    dup_of,
                )
                dup_error = ValidationError(
                    code="DUPLICATE_PROMPT",
                    message=f"Prompt reuses the environment from scene {dup_of}.",
                    severity="critical",
                    violated_item=f"scene {dup_of}",
                    hint=vp_map.get(dup_of, "")[:200],
                )
                deterministic_result = ValidationResult(
                    passed=False,
                    errors=deterministic_result.errors + [dup_error],
                )

            # Task 2.4 Fix 1 / Task 2.5 Fix C: zero CRITICAL errors = PASS,
            # always — the single unified evaluation point for every attempt.
            # `deterministic_result.passed` requires zero errors of ANY
            # severity (including minor ones like STORY_TIME_MISSING or
            # CAMERA_MISSING), so a minor-only issue was blocking PASS despite
            # zero critical violations — that was scenes 020/022's "FAIL | 0
            # errors" with no legacy-disagreement log line (a different path
            # from scene 028's legacy-override case, but the same root bug:
            # something other than "zero critical errors" was gating PASS).
            # The legacy LLM faithfulness check remains advisory only — it
            # must never override a clean deterministic result.
            critical_errors = deterministic_result.critical_errors
            if not critical_errors:
                if settings.faithfulness_validation_enabled:
                    legacy_passed, legacy_violation = _validate_prompt_faithfulness(
                        scene.get("narration", ""),
                        entities,
                        current_prompt,
                        _validation_llm,
                    )
                    if not legacy_passed:
                        logger.warning(
                            "Scene {:03d} | attempt {} | deterministic PASS, "
                            "legacy faithfulness check disagreed ({}) — accepting anyway "
                            "(zero deterministic errors = pass)",
                            idx,
                            attempt,
                            legacy_violation,
                        )
                final_status = FaithfulnessStatus.PASS
                attempts = attempt + 1
                vp_map[idx] = current_prompt
                logger.info("Scene {:03d} | attempt {} | PASS", idx, attempt)
                break

            critical_error_codes = [e.code for e in critical_errors]

            # Task 2.6 Part 2: ENVIRONMENT_MISMATCH / HUMAN_CLASSIFICATION_VIOLATED
            # need semantic understanding keyword matching can't provide. Only
            # spend an LLM call when they're the ONLY remaining failures —
            # structural violations (FORBIDDEN_CHARACTER, SYMBOLIC_REPLACEMENT,
            # etc.) go through the normal retry path first.
            if (
                settings.faithfulness_llm_validation_enabled
                and _should_use_llm_validation(critical_error_codes)
            ):
                llm_passed, llm_reason = _run_llm_validation(
                    scene_analysis,
                    entities.human_classification,
                    current_prompt,
                    _llm_validation_client,
                    settings,
                )
                if llm_passed:
                    logger.info(
                        "Scene {:03d} | attempt {} | LLM validation PASS (overrides deterministic) | {}",
                        idx,
                        attempt,
                        llm_reason,
                    )
                    final_status = FaithfulnessStatus.PASS
                    attempts = attempt + 1
                    llm_validated = True
                    llm_reason_text = llm_reason
                    vp_map[idx] = current_prompt
                    break
                logger.warning(
                    "Scene {:03d} | attempt {} | LLM validation FAIL | {}",
                    idx,
                    attempt,
                    llm_reason,
                )
                llm_reason_text = llm_reason
                # Fall through to normal retry.

            feedback = compose_feedback(deterministic_result)

            if not feedback:
                feedback = "Prompt failed validation. Please regenerate preserving the story and narration."

            logger.warning(
                "Scene {:03d} | attempt {} | FAIL | {} errors",
                idx,
                attempt,
                len(critical_errors),
            )
            validation_issues += 1
            last_violation = feedback

            if attempt >= max_retries:
                final_status = FaithfulnessStatus.FAILED
                attempts = attempt + 1
                logger.error(
                    "Scene {:03d} | FAILED after {} retries | final violation: {}",
                    idx,
                    max_retries,
                    feedback,
                )
                break

            attempt += 1
            logger.info(
                "Scene {:03d} | retrying (attempt {}/{}) | json_mode={}",
                idx,
                attempt,
                max_retries,
                use_json_mode,
            )

            retry_prompt = build_retry_prompt(
                scene=scene,
                scene_analysis=scene_analysis,
                narration=scene.get("narration", ""),
                violation_feedback=feedback,
                style=style,
                entity_constraints_section=entity_constraints_section,
                scene_analysis_section=scene_analysis_section,
                human_classification=entities.human_classification,
                current_prompt=current_prompt,  # always pass the most recent version
            )
            retry_resp = llm.generate(
                retry_prompt,
                json_mode=False,
                json_schema=None,
                temperature=0.35,
            )
            new_prompt = _strip_fences(retry_resp.text)
            if len(new_prompt) >= 50:
                current_prompt = new_prompt
                vp_map[idx] = current_prompt
                logger.info("Scene {:03d} | retry accepted on attempt {}", idx, attempt)
            else:
                final_status = FaithfulnessStatus.FAILED
                attempts = attempt + 1
                logger.error(
                    "Scene {:03d} | retry response too short on attempt {} ({} chars)",
                    idx,
                    attempt,
                    len(new_prompt),
                )
                break

        _faithfulness_qa[idx] = {
            "status": final_status.value,
            "violation": last_violation,
            "attempts": attempts,
            "critical_errors": critical_error_codes
            if final_status == FaithfulnessStatus.FAILED
            else [],
            "llm_validated": llm_validated,
            "llm_reason": llm_reason_text,
        }

    if validation_issues:
        console.print(
            f"  [yellow]⚠[/yellow] Prompt fidelity: {validation_issues} issue(s) — retries attempted"
        )
    else:
        console.print("  [green]✓[/green] Prompt fidelity passed")

    # Apply prompts and visual_metadata; fall back to title-based placeholder for any missed scene
    for s in scenes:
        if s["index"] in vp_map:
            s["visual_prompt"] = vp_map[s["index"]]
        elif not s.get("visual_prompt"):
            s["visual_prompt"] = (
                f"Cinematic wide shot, {s.get('title', 'contemplative moment')}, "
                "golden hour lighting, silhouette, spiritual documentary, no text, no watermark, photorealistic"
            )
        if s["index"] in _vm_map and not s.get("visual_metadata"):
            s["visual_metadata"] = _vm_map[s["index"]]
        if not s.get("visual_metadata"):
            s["visual_metadata"] = {}
        if s["index"] in _ar_map:
            s["anchor_role"] = _ar_map[s["index"]]
        elif not s.get("anchor_role"):
            s["anchor_role"] = "absent"
        if s["index"] in _faithfulness_qa:
            s["faithfulness_qa"] = _faithfulness_qa[s["index"]]
        elif s.get("scene_type") in ("asset", "brand_card"):
            s["faithfulness_qa"] = {
                "status": FaithfulnessStatus.SKIPPED.value,
                "violation": "",
                "attempts": 0,
                "critical_errors": [],
                "llm_validated": False,
                "llm_reason": "",
            }

    # ── Character presence enforcement ────────────────────────────────────
    # character_presence is authoritative: strips stray Kai from non-Kai scenes
    # and sets anchor_role from character_presence when that field is set.
    # No automatic Kai injection (no distribution/closing-scene override).
    scenes = _enforce_primary_kai_spec(scenes)
    scenes = _propagate_environment_anchors(scenes)
    scenes = _enforce_style_footer(scenes, hybrid=settings.HYBRID_STYLE_ENABLED)
    scenes = _enforce_era_consistency(scenes)

    # ── V2: Per-scene structured prompt generation ────────────────────────
    if settings.HYBRID_STYLE_ENABLED or settings.VISUAL_BIBLE_ENABLED:
        console.print(
            f"  [cyan]→[/cyan] V2: building structured prompts for "
            f"{len([s for s in scenes if s.get('scene_type') != 'brand_card'])} scenes..."
        )
        gen_scenes = [s for s in scenes if s.get("scene_type") != "brand_card"]
        for i, scene in enumerate(gen_scenes):
            prev = gen_scenes[i - 1] if i > 0 else None
            sp = _build_structured_prompt(
                scene=scene,
                visual_bible=visual_bible,
                scene_index=i,
                total_scenes=len(gen_scenes),
                llm=llm,
                settings=settings,
                prev_scene=prev,
                story_bible=story_bible,
                story_context=scene.get("story_context", ""),
                narrative_context=_make_scene_narrative_context(scene, script_identity_dict),
            )
            sp_dict, repair_errors = _repair_structured_prompt_dict(
                sp.model_dump(),
                scene.get("anchor_role", "absent"),
                scene.get("index", i + 1),
            )
            for err in repair_errors:
                logger.error("STRUCTURED PROMPT REPAIR: {}", err)
            scene["structured_prompt"] = sp_dict
            scene["visual_prompt"] = (
                sp_dict.get("compiled_prompt") or sp.compiled_prompt
            )
        console.print(
            f"  [green]✓[/green] V2 structured prompts: {len(gen_scenes)} scenes"
        )

        # Re-validate faithfulness_qa against the FINAL prompts (V2 override
        # may have resolved errors that were present in the pre-V2 prompts).
        for scene in gen_scenes:
            idx = scene["index"]
            entities = entity_map.get(idx)
            if not entities or not scene.get("faithfulness_qa"):
                continue
            sa = scene.get("scene_analysis", {})
            sa, ents = _sanitize_scene_analysis(
                sa, entities, scene.get("narration", "")
            )
            post_v2_result = run_validators(
                scene_analysis=sa,
                prompt=scene["visual_prompt"],
                narration=scene.get("narration", ""),
                human_classification=ents.human_classification,
                scene_category=ents.scene_category,
                visual_anchor=scene.get("visual_anchor", ""),
                story_characters=_story_characters,
            )
            if not post_v2_result.critical_errors:
                scene["faithfulness_qa"] = {
                    "status": FaithfulnessStatus.PASS.value,
                    "violation": "",
                    "attempts": scene["faithfulness_qa"].get("attempts", 0),
                    "critical_errors": [],
                    "llm_validated": scene["faithfulness_qa"].get(
                        "llm_validated", False
                    ),
                    "llm_reason": scene["faithfulness_qa"].get("llm_reason", ""),
                }

    # ── V2: Post-V2 Kai re-enforcement ─────────────────────────────────
    # V2 may have generated aerial prompts for Kai-primary scenes despite
    # the shot_type constraint; demote those to absent so Step 0 is accurate.
    scenes = _enforce_primary_kai_spec(scenes)

    # ── Strip pipeline meta-annotations from all visual prompts ─────────
    # Phase labels, anchor-role justifications, and internal planning notes
    # contaminate the image generator when they appear inside visual_prompt.
    for _s in scenes:
        if _s.get("visual_prompt"):
            _s["visual_prompt"] = _strip_prompt_meta_annotations(_s["visual_prompt"])
        # Also clean the compiled_prompt inside structured_prompt if present
        _sp = _s.get("structured_prompt")  # type: ignore[assignment]
        if isinstance(_sp, dict) and _sp.get("compiled_prompt"):
            _sp["compiled_prompt"] = _strip_prompt_meta_annotations(
                _sp["compiled_prompt"]
            )

    # ── V2: Sync visual_metadata from structured prompts ────────────────
    scenes = _sync_metadata_from_v2(scenes)

    # ── V2: Continuity validation (flag-and-log only) ─────────────────────
    continuity_warnings = _validate_visual_continuity(scenes, visual_bible)

    # ── Story continuity validation (character/prop state, action grounding) ─
    _story_validator = ContinuityValidator(story_state)
    _continuity_findings = _story_validator.validate_all(scenes, scene_analysis_map)
    _story_errors = [f for f in _continuity_findings if f.is_error()]
    _story_warnings = [f for f in _continuity_findings if f.is_warning()]
    if _story_errors:
        for _f in _story_errors:
            logger.error("STORY CONTINUITY ERROR: {}", str(_f))
        console.print(
            f"  [bold red]⚠ {len(_story_errors)} story continuity errors (see logs)[/bold red]"
        )
    if _story_warnings:
        for _f in _story_warnings:
            logger.warning("STORY CONTINUITY WARNING: {}", str(_f))
        console.print(
            f"  [yellow]⚠ {len(_story_warnings)} story continuity warnings[/yellow]"
        )

    # ── Canonical prompt validation (post-LLM contradiction check) ─────────
    _continuity_report = ContinuityReport()
    if settings.scene_continuity_enabled and settings.scene_continuity_prompt_validation:
        _prompt_validation_errors = 0
        for _s in scenes:
            if _s.get("scene_type", "generated_image") != "generated_image":
                continue
            _idx = _s["index"]
            _prompt = _s.get("visual_prompt", "")
            if not _prompt:
                continue
            from ytfactory.scene_continuity.models import scene_mode_from_narrative_role
            _vm = _s.get("visual_metadata") or {}
            _narrative_role = (
                _vm.get("narrative_role", "STORY") if isinstance(_vm, dict)
                else getattr(_vm, "narrative_role", "STORY")
            ) or "STORY"
            _mode = scene_mode_from_narrative_role(_narrative_role)
            _sa = scene_analysis_map.get(_idx)
            _findings = validate_prompt_against_state(
                _prompt, story_state, _idx, _mode, _sa
            )
            _errors = [f for f in _findings if f.is_error()]
            if _errors:
                _prompt_validation_errors += len(_errors)
                for _f in _errors:
                    logger.error("PROMPT CONTINUITY VIOLATION Scene {}: {}", _idx, str(_f))
                _scene_status = SceneContinuityStatus(
                    scene_index=_idx,
                    status="REPAIRED" if _f.suggested_fix else "FAILED",
                    prompt_violations=_errors,
                )
                _continuity_report.record_scene(_scene_status)
            else:
                _scene_status = SceneContinuityStatus(
                    scene_index=_idx, status="PASS"
                )
                _continuity_report.record_scene(_scene_status)

        if _prompt_validation_errors:
            console.print(
                f"  [yellow]⚠[/yellow] Prompt continuity: {_prompt_validation_errors} violation(s) in generated prompts"
            )
        else:
            console.print(
                "  [green]✓[/green] Prompt continuity: all prompts match canonical state"
            )

    # ── Write continuity report ─────────────────────────────────────────
    _project_dir = Path(WORKSPACE_DIR) / project_id
    if settings.scene_continuity_enabled:
        _report_path = _continuity_report.write_report(_project_dir)
        if settings.scene_continuity_debug and _continuity_report.all_violations:
            console.print(
                f"  [dim]Continuity report: {_report_path}[/dim]"
            )

    # ── Visual Intelligence logging ──────────────────────────────────────
    for s in scenes:
        vm = s.get("visual_metadata", {})
        logger.info(
            "Scene {:03d} | era={} role={} env={} mood={} style={} "
            "allow_modern={} reason={}",
            s["index"],
            vm.get("era", "—"),
            vm.get("narrative_role", "—"),
            vm.get("environment", "—"),
            vm.get("mood", "—"),
            vm.get("visual_style", "—"),
            vm.get("allow_modern_objects", "—"),
            vm.get("reason", "—"),
        )

    # ── V4: Diagnostics, validation, and debug output ─────────────────────
    v4_report = _v4_engine.build_diagnostics(scenes)
    v4_issues = _v4_engine.validate(scenes, v4_report)

    if v4_issues:
        for issue in v4_issues:
            logger.warning("V4 image prompt: {}", issue)
        console.print(
            f"  [yellow]⚠[/yellow] V4 validation: {len(v4_issues)} issue(s) — "
            f"diversity score {v4_report.diversity_score:.2f}"
        )
    else:
        console.print(
            f"  [green]✓[/green] V4 validation passed — "
            f"diversity score {v4_report.diversity_score:.2f}, "
            f"{len(set(shot_plan))} shot types"
        )

    if settings.image_prompt_debug:
        debug_dir = _v4_engine.write_debug_output(project_id, scenes, v4_report)
        console.print(f"  [green]✓[/green] V4 debug output: [dim]{debug_dir}[/dim]")

    # ── Persist artifacts ─────────────────────────────────────────────────
    scene_plan = {
        "topic": topic,
        "total_duration_seconds": total,
        "scenes": scenes,
        "visual_bible": visual_bible.model_dump(),
        "continuity_warnings": continuity_warnings,
        "identity_hash": current_id_hash,
    }
    artifact_repo.write_json(project_id, "scenes", "scene-plan.json", scene_plan)

    # Human-readable markdown summary
    md_lines = [
        f"# Scene Plan: {topic}\n",
        f"Total: {len(scenes)} scenes, ~{total / 60:.1f} min\n",
    ]
    for s in scenes:
        vm = s.get("visual_metadata", {})
        md_lines.append(
            f"## Scene {s['index']}: {s['title']} ({s['duration_seconds']}s)\n"
            f"**Narration:** {s['narration']}\n\n"
            f"**Visual:** {s['visual_prompt']}\n\n"
            f"**Visual Metadata:** era={vm.get('era', '—')} role={vm.get('narrative_role', '—')} "
            f"env={vm.get('environment', '—')} mood={vm.get('mood', '—')} "
            f"style={vm.get('visual_style', '—')} modern={vm.get('allow_modern_objects', '—')}\n"
        )
    artifact_repo.write_markdown(
        project_id, "scenes", "scene-plan.md", "\n".join(md_lines)
    )

    project_repo.update_stage(project_id, "scenes", "completed")

    # ── Write Story Bible files ──────────────────────────────────────────
    if story_bible.characters or story_bible.locations:
        bible_dir = write_story_bible(story_bible, project_id, WORKSPACE_DIR, scenes)
        console.print(f"  [green]✓[/green] Story Bible: [dim]{bible_dir}[/dim]")

    # ── Write prompts file for manual image generation ────────────────────
    prompts_path = _write_prompts_file(
        project_id, scenes, style, settings, story_bible=story_bible
    )
    console.print(
        f"  [green]✓[/green] Image prompts exported: [dim]{prompts_path}[/dim]"
    )

    # ── Faithfulness pre-render gate (non-blocking) ────────────────────────
    _write_faithfulness_gate_report(project_id, scenes)

    # Print summary table
    table = Table(title="Scene Plan", show_lines=True)
    table.add_column("#", style="cyan", width=4)
    table.add_column("Title", style="bold")
    table.add_column("Duration", width=8)
    table.add_column("Narration preview", max_width=50)
    for s in scenes:
        narration_preview = (
            s["narration"][:60] + "…" if len(s["narration"]) > 60 else s["narration"]
        )
        scene_label = s["title"] + (
            " [asset]" if s.get("scene_type") in ("asset", "brand_card") else ""
        )
        table.add_row(
            str(s["index"]), scene_label, f"{s['duration_seconds']}s", narration_preview
        )
    console.print(table)
    console.print(
        Panel(
            f"[green]Scene plan complete[/green] — {len(scenes)} scenes, ~{total / 60:.1f} minutes",
            title="Scene Planner Agent",
            border_style="green",
        )
    )

    return {"scene_plan": scenes}
