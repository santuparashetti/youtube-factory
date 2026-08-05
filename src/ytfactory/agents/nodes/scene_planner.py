"""Scene planner node — Python splits narrations, LLM adds visual prompts only."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace as dc_replace
from pathlib import Path
from typing import Literal

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from video_core.providers.llm.base import LLMProvider
from video_core.providers.llm.factory import get_llm_provider
from ytfactory.agents.prompts.branding import (
    CLOSING_VARIATIONS,
    SOFT_CTA,
    WELCOME_VARIATIONS,
)
from ytfactory.agents.prompts.scene_planner import (
    ENTITY_EXTRACTION_PROMPT,
    FAITHFULNESS_VALIDATION_PROMPT,
    build_llm_validation_prompt,
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
from ytfactory.scenes.models import FaithfulnessStatus, StructuredImagePrompt, VisualBible
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.story_bible.composer import compose_scene_context
from ytfactory.story_bible.generator import load_or_generate_story_bible
from ytfactory.story_bible.models import StoryBible
from ytfactory.story_bible.writer import write_story_bible
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
    "dark hair", "simple dark shirt", "lean young man",
    "light stubble", "plain trousers",
]


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
    "sitting", "seated", "standing", "walking", "looking", "facing",
    "leaning", "kneeling", "watching", "holding", "reaching", "turning",
    "positioned", "gazing", "staring", "moving", "stepping",
    # Simple present forms (V2 compiled_prompt style)
    "sits", "stands", "walks", "looks", "faces",
    "leans", "kneels", "watches", "holds", "reaches", "turns",
    "gazes", "stares", "moves", "steps",
    # Past tense forms
    "stood", "sat", "walked", "looked", "faced", "leaned", "knelt",
    "watched", "held", "reached", "turned", "gazed", "stared",
]


def _has_action_staging(prompt: str) -> bool:
    """True if the prompt contains an active character action verb."""
    p = prompt.lower()
    return any(v in p for v in _ACTION_VERBS)


# Camera angles where a standing character cannot logically be placed.
# "looking straight down" is a common false positive for _has_character_staging.
_AERIAL_INDICATORS = [
    "aerial", "drone shot", "bird's eye", "looking straight down",
    "top-down", "overhead shot", "straight down on",
]


def _is_aerial_shot(prompt: str) -> bool:
    """True if the prompt describes an overhead/aerial camera angle."""
    p = prompt.lower()
    return any(ind in p for ind in _AERIAL_INDICATORS)


def _enforce_primary_kai_spec(scenes: list[dict]) -> list[dict]:
    """For primary scenes:
    - Aerial/overhead shots: reclassify to 'absent' — Kai cannot stand in a
      bird's-eye or straight-down drone shot. Also strips any previously
      injected Kai spec so the prompt is clean.
    - Kai markers present AND action verb present: leave unchanged (correct).
    - Kai markers present but NO action verb: reclassify to 'absent' — the spec
      was prepended by the LLM but the staging is atmospheric, creating a
      contradiction (Kai spec with no character action).
    - No Kai markers, has character staging: prepend Kai spec.
    - No Kai markers, no character staging (atmospheric/symbolic): reclassify
      to 'absent' to prevent Kai spec + empty-scene contradiction.
    """
    for scene in scenes:
        if scene.get("anchor_role") != "primary":
            continue
        prompt = scene.get("visual_prompt", "")

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
            # Strip any prepended Kai spec so the prompt is clean.
            for marker in [KAI_COMPRESSED_SPEC + " —", KAI_COMPRESSED_SPEC]:
                prompt = prompt.replace(marker, "").strip()
            scene["visual_prompt"] = prompt
            scene["anchor_role"] = "absent"
        elif _has_character_staging(prompt):
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

_STYLE_FOOTER_SYMBOLIC = (
    "No text, no watermark, photorealistic."
)

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
        "documentary-quality realism", "no text, no watermark", "photorealistic",
        "ink outlines", "cel shading", "painterly storybook texture",
        "not photorealistic", "no subtitle", "no logo",
    ]:
        prompt = re.sub(
            rf'[,.]?\s*{re.escape(indicator)}[^.]*\.?',
            '',
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
    """
    Ensures every visual_prompt ends with the correct style/quality footer.
    primary / spectator + hybrid  → illustrated character footer (ink outlines, cel shading)
    primary / spectator + non-hybrid → photorealistic human quality footer
    absent                         → symbolic footer (no human quality instructions)

    Partial footer phrases are stripped before the full footer is appended so
    phrases never appear twice.
    """
    for scene in scenes:
        role = scene.get("anchor_role", "absent")
        prompt = scene.get("visual_prompt", "").rstrip()

        if role in ("primary", "spectator"):
            footer = _STYLE_FOOTER_ILLUSTRATED if hybrid else _STYLE_FOOTER_HUMAN
            # Marker phrase that signals the correct footer is already present.
            char_marker = "ink outlines" if hybrid else "highly detailed human face"
        else:
            footer = _STYLE_FOOTER_SYMBOLIC
            char_marker = None

        has_full_footer = _has_footer(prompt)
        needs_upgrade = (
            char_marker is not None and char_marker not in prompt.lower()
        )

        if has_full_footer and not needs_upgrade:
            continue  # already complete and correct

        # Strip any partial indicator phrases before appending the full footer.
        stripped = _strip_partial_footer(prompt)
        scene["visual_prompt"] = f"{stripped} {footer}"

    return scenes


def _enforce_closing_scene_primary(scenes: list[dict]) -> list[dict]:
    """The last non-asset scene must be anchor_role='primary'. Override + prepend spec if not."""
    closing_idx: int | None = None
    for i in reversed(range(len(scenes))):
        if scenes[i].get("scene_type") not in ("asset", "brand_card"):
            closing_idx = i
            break
    if closing_idx is None:
        return scenes
    closing = scenes[closing_idx]
    if closing.get("anchor_role") != "primary":
        closing["anchor_role"] = "primary"
        prompt = closing.get("visual_prompt", "")
        if not _has_kai_markers(prompt):
            if _has_character_staging(prompt):
                closing["visual_prompt"] = f"{KAI_COMPRESSED_SPEC} — {prompt}"
            else:
                closing["visual_prompt"] = (
                    f"{KAI_COMPRESSED_SPEC} — standing still, facing forward, "
                    f"looking outward with quiet resolve. "
                    f"{prompt}"
                )
    return scenes


def _enforce_kai_distribution(
    scenes: list[dict],
    entity_map: dict[int, "SceneEntities"],
) -> list[dict]:
    """Ensure Kai appears in at least 30% of non-asset scenes, spread across arc phases.

    Runs AFTER _enforce_primary_kai_spec and _enforce_closing_scene_primary so it
    accounts for scenes that were downgraded to absent by those guards.  Newly
    promoted scenes get the Kai spec prepended via a follow-up
    _enforce_primary_kai_spec call in the main pipeline.
    """
    gen_scenes = [s for s in scenes if s.get("scene_type") not in ("asset", "brand_card")]
    total = len(gen_scenes)
    if total < 4:
        return scenes

    kai_count = sum(1 for s in gen_scenes if s.get("anchor_role") in ("primary", "spectator"))
    target = max(3, int(total * 0.30))
    if kai_count >= target:
        return scenes

    needed = target - kai_count

    candidates: list[tuple[dict, int]] = []
    for s in gen_scenes:
        if s.get("anchor_role") in ("primary", "spectator"):
            continue
        if _is_aerial_shot(s.get("visual_prompt", "")):
            continue
        idx = s.get("index", 0)
        ents = entity_map.get(idx)
        if ents and ents.human_classification == HumanClassification.NO_HUMAN_ALLOWED:
            continue
        priority = 2 if (ents and ents.human_classification in (
            HumanClassification.HUMAN_REQUIRED,
            HumanClassification.HUMAN_OPTIONAL,
            HumanClassification.HUMAN_SYMBOLIC,
        )) else 1
        candidates.append((s, priority))

    if not candidates:
        return scenes

    # Spread evenly across arc phases so Kai isn't clustered in one section.
    phase_buckets: dict[str, list[tuple[dict, int]]] = {
        "opening": [], "build": [], "climax": [], "resolution": [],
    }
    for s, prio in candidates:
        phase = _get_arc_phase(s.get("index", 1), total)
        phase_buckets[phase].append((s, prio))

    # Sort each bucket: higher priority first, then by scene index for stability.
    for bucket in phase_buckets.values():
        bucket.sort(key=lambda x: (-x[1], x[0].get("index", 0)))

    promoted = 0
    # Round-robin across phases to distribute evenly.
    phase_order = ["opening", "build", "climax", "resolution"]
    while promoted < needed:
        advanced = False
        for phase in phase_order:
            if promoted >= needed:
                break
            bucket = phase_buckets[phase]
            if bucket:
                scene, _ = bucket.pop(0)
                scene["anchor_role"] = "primary"
                prompt = scene.get("visual_prompt", "")
                if not _has_kai_markers(prompt):
                    if _has_character_staging(prompt):
                        scene["visual_prompt"] = f"{KAI_COMPRESSED_SPEC} — {prompt}"
                    else:
                        scene["visual_prompt"] = (
                            f"{KAI_COMPRESSED_SPEC} — standing still, facing forward, "
                            f"looking outward with quiet resolve. {prompt}"
                        )
                promoted += 1
                advanced = True
        if not advanced:
            break

    if promoted > 0:
        logger.info(
            "Kai distribution: promoted {} scenes to primary (total {}/{})",
            promoted, kai_count + promoted, total,
        )
    return scenes


def _enforce_era_consistency(scenes: list[dict]) -> list[dict]:
    """Harmonize era metadata to the dominant era across all generated scenes.

    Prevents visual whiplash from mixing ANCIENT/HISTORICAL/MODERN styles
    in a single video.  TRANSITIONAL scenes are intentional bridges and are
    never overridden.  SYMBOLIC scenes are era-neutral and are left alone.
    """
    gen_scenes = [s for s in scenes if s.get("scene_type") not in ("asset", "brand_card")]
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
                s.get("index"), old_era, dominant_era,
            )

    if harmonized > 0:
        logger.info(
            "Era consistency: harmonized {}/{} scenes to dominant era '{}'",
            harmonized, len(gen_scenes), dominant_era,
        )
    return scenes


# Environment keyword mapping for metadata sync from V2 prompts.
_ENVIRONMENT_KEYWORDS: dict[str, list[str]] = {
    "FOREST": ["forest", "woods", "trees", "grove", "jungle", "woodland", "canopy"],
    "TEMPLE": ["temple", "shrine", "cathedral", "church", "mosque", "chapel", "sanctuary"],
    "ASHRAM": ["ashram", "monastery", "hermitage", "retreat", "meditation hall"],
    "KINGDOM": ["palace", "throne", "castle", "court", "kingdom", "fortress", "citadel"],
    "BATTLEFIELD": ["battlefield", "battle", "combat", "army", "siege", "warzone"],
    "CITY": ["city", "street", "urban", "downtown", "skyline", "skyscraper", "alley", "boulevard"],
    "OFFICE": ["office", "desk", "boardroom", "corporate", "cubicle", "conference room"],
    "HOME": ["home", "house", "apartment", "kitchen", "bedroom", "living room", "domestic", "cottage", "hearth"],
    "MOUNTAIN": ["mountain", "cliff", "peak", "summit", "hill", "ridge", "highland", "alpine"],
    "RIVER": ["river", "stream", "lake", "pond", "water", "shore", "bank", "ghat", "riverbank"],
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
            (sp.get("environment_prompt", "") if isinstance(sp, dict)
             else getattr(sp, "environment_prompt", ""))
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
                scene.get("index"), old_env, best_match,
            )

    if synced > 0:
        logger.info("Metadata sync: updated environment for {}/{} scenes from V2 prompts", synced, len(scenes))
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


def _generate_visual_bible(script_text: str, llm: LLMProvider, settings: Settings) -> VisualBible:
    """Single LLM call to produce a VisualBible. Falls back to stub on failure."""
    if not settings.VISUAL_BIBLE_ENABLED:
        return _stub_visual_bible()

    prompt_text = _load_prompt_file("VISUAL_BIBLE_PROMPT.md")
    full_prompt = f"{prompt_text}\n\nSCRIPT:\n{script_text}"
    try:
        response = llm.generate(full_prompt, temperature=0.4)
        raw = response.text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
        data = json.loads(raw)
        return VisualBible(**data)
    except Exception as e:
        logger.warning("VisualBible generation failed: {} — using stub", e)
        return _stub_visual_bible()


def _get_arc_phase(scene_index: int, total_scenes: int) -> str:
    """Map scene position to emotional arc phase."""
    ratio = scene_index / max(total_scenes - 1, 1)
    if ratio < 0.20:
        return "opening"
    elif ratio < 0.65:
        return "build"
    elif ratio < 0.80:
        return "climax"
    else:
        return "resolution"


def _arc_to_shot_key(arc_phase: str) -> str:
    mapping = {
        "opening": "opening_scenes",
        "build": "build_scenes",
        "climax": "climax_scene",
        "resolution": "resolution_scenes",
    }
    return mapping.get(arc_phase, "build_scenes")


_CAMERA_ANGLE_BY_PHASE = {
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
) -> StructuredImagePrompt:
    """LLM call per scene to produce a StructuredImagePrompt."""
    arc_phase = _get_arc_phase(scene_index, total_scenes)

    style_directive = _load_prompt_file("CINEMATIC_HYBRID_STYLE.md") if settings.HYBRID_STYLE_ENABLED else ""
    anchor_role = scene.get("anchor_role", "absent")
    pose_rules = _load_prompt_file("KAI_POSE_RULES.md") if (anchor_role != "absent" and settings.KAI_POSE_DISCIPLINE_ENABLED) else ""
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
    era = (scene.get("visual_metadata") or {}).get("era", "") if isinstance(scene.get("visual_metadata"), dict) else (getattr(scene.get("visual_metadata"), "era", "") or "")
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
        prev_env = sp.get("environment_prompt", "") if isinstance(sp, dict) else getattr(sp, "environment_prompt", "")
        prev_lighting = (sp.get("lighting_match", "") if isinstance(sp, dict) else getattr(sp, "lighting_match", ""))[:80]
        prev_focal = (sp.get("focal_length", "") if isinstance(sp, dict) else getattr(sp, "focal_length", ""))[:40]
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
        "7. If Kai scene: one-line pose rule reminder\n"
        '8. End with: "16:9 aspect ratio. No text, no watermark, no subtitle, no logo."\n'
    ) if settings.HYBRID_STYLE_ENABLED else (
        "COMPILED_PROMPT ASSEMBLY RULES:\n"
        "1. Shot type, camera angle, and focal_length (e.g. 'Wide shot, high angle, 24mm')\n"
        "2. environment_prompt verbatim — derive from the narration's central idea, not a generic default.\n"
        "3. If character_staging is not null: character_staging + lighting_match\n"
        "4. color_palette_phase\n"
        "5. continuity_ref (brief)\n"
        '6. End with: "16:9 aspect ratio. No text, no watermark, no subtitle, no logo."\n'
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

    system_prompt = (
        "You are a cinematographer writing image generation prompts for a philosophical documentary.\n\n"
        + (f"{style_directive}\n\n" if style_directive else "")
        + (f"{pose_rules}\n\n" if pose_rules else "")
        + (f"{audience_block}\n" if audience_block else "")
        + (f"{era_block}\n" if era_block else "")
        + f"{bible_context}\n\n"
        + (f"{story_bible_block}\n\n" if story_bible_block else "")
        + (f"{prev_context}\n\n" if prev_context else "")
        + f"SCENE POSITION: Scene {scene_index + 1} of {total_scenes}. Arc phase: {arc_phase}.\n\n"
        + 'OUTPUT: Respond ONLY with a JSON object matching this schema exactly:\n'
        + '{\n'
        + ('  "shot_type": "<one of: establishing_wide|medium|close_up|insert|POV|over_shoulder|silhouette>",\n'
           if anchor_role in ("primary", "spectator")
           else '  "shot_type": "<one of: establishing_wide|medium|close_up|insert|POV|over_shoulder|silhouette|aerial>",\n')
        + '  "camera_angle": "<one of: eye_level|low_angle|high_angle|dutch_tilt>",\n'
        + '  "environment_prompt": "<photorealistic environment description — no character details>",\n'
        + '  "character_staging": "<illustrated character description, or null if no character>",\n'
        + '  "lighting_match": "<one sentence: how character lighting matches environment>",\n'
        + '  "focal_length": "<lens — e.g. 24mm wide-angle, 35mm, 50mm standard, 85mm portrait, 135mm telephoto>",\n'
        + '  "color_palette_phase": "<arc phase + specific palette for this scene>",\n'
        + '  "continuity_ref": "<reference to prev/next scene environment and Kai clothing if applicable>",\n'
        + '  "compiled_prompt": "<full merged prompt for image generator — see assembly rules below>"\n'
        + '}\n\n'
        + 'FOCAL LENGTH GUIDE (match to shot_type):\n'
        + '  establishing_wide / aerial → 24mm wide-angle (expansive, environmental scale)\n'
        + '  medium / over_shoulder → 50mm standard (natural perspective, no distortion)\n'
        + '  close_up / insert → 85mm portrait or 100mm macro (shallow DOF, subject isolation)\n'
        + '  POV → 35mm (natural human perspective)\n'
        + '  silhouette → 35mm or 50mm (clean silhouette edges)\n'
        + '  Vary focal length across consecutive scenes — avoid repeating the same lens.\n\n'
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
            "- NEVER substitute \"man\", \"woman\", \"person\", \"figure\", or \"people\" for a named entity\n"
            "- Use the EXACT names from the allowed list in character_staging\n"
            "- If a character name feels generic (e.g. \"villager\"), use it verbatim — do not upgrade\n"
            "  to \"man\" or \"woman\"\n"
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
            f"- Forbidden characters: {', '.join(forbidden[:6]) if forbidden else 'none'}\n"
            f"- Required environment: {required_env if required_env else 'as narrated'}\n"
        )

    kai_placement_block = ""
    if anchor_role == "spectator":
        kai_placement_block = (
            "\nKAI SPATIAL PLACEMENT (CRITICAL — spectator scene):\n"
            "Kai must be INSIDE the same physical space as the main action.\n"
            "If the scene is indoors: Kai stands inside the room, near a wall or at the back — "
            "NOT outside a doorway or window looking in.\n"
            "If the scene is outdoors: Kai stands in the same outdoor space — "
            "NOT inside a building looking out.\n"
            "One environment. Kai is a witness from within, not a viewer from another location.\n"
        )

    # Extract emotional beat for Kai posture selection
    _vm = scene.get("visual_metadata") or {}
    _emotional_beat = (
        (_vm.get("mood") if isinstance(_vm, dict) else getattr(_vm, "mood", "")) or ""
    )
    _scene_analysis = scene.get("scene_analysis") or {}
    if not _emotional_beat and _scene_analysis:
        _emotional_beat = (
            (_scene_analysis.get("emotional_beat") if isinstance(_scene_analysis, dict)
             else getattr(_scene_analysis, "emotional_beat", "")) or ""
        )
    _posture_variant = ("A", "B", "C")[scene.get("index", scene_index) % 3]
    kai_emotion_hint = (
        f"\nSCENE EMOTIONAL BEAT: {_emotional_beat} — "
        f"use POSTURE VARIANT {_posture_variant} from the EMOTION-RESPONSIVE BODY LANGUAGE table above. "
        "Variant letters rotate A→B→C across scenes to prevent consecutive Kai scenes from sharing the same posture.\n"
    ) if _emotional_beat and anchor_role != "absent" else ""

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
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
        data = json.loads(raw)
        sp = StructuredImagePrompt(**data)
        # Guard: LLM sometimes omits the hybrid header for EXPLANATION/ANALOGY/CTA roles.
        # Inject it deterministically so no role ever slips through without it.
        if settings.HYBRID_STYLE_ENABLED and not sp.compiled_prompt.lstrip().upper().startswith("HYBRID"):
            data["compiled_prompt"] = _HYBRID_COMPRESSED_PREFIX + " " + sp.compiled_prompt
            sp = StructuredImagePrompt(**data)
        return sp
    except Exception as e:
        logger.warning("StructuredImagePrompt build failed for scene {}: {} — using fallback", scene_index + 1, e)
        fallback_prompt = scene.get(
            "visual_prompt",
            "cinematic environment. 16:9 aspect ratio. No text, no watermark, no subtitle, no logo.",
        )
        if settings.HYBRID_STYLE_ENABLED and not fallback_prompt.lstrip().upper().startswith("HYBRID"):
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
            env = scene["structured_prompt"].get("environment_prompt", "").lower() if isinstance(scene["structured_prompt"], dict) else getattr(scene["structured_prompt"], "environment_prompt", "").lower()
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
            st = sp.get("shot_type") if isinstance(sp, dict) else getattr(sp, "shot_type", None)
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
            st = sp.get("shot_type") if isinstance(sp, dict) else getattr(sp, "shot_type", None)
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
            staging = sp.get("character_staging") if isinstance(sp, dict) else getattr(sp, "character_staging", None)
            if staging:
                staging_lower = staging.lower()
                if "facing forward" in staging_lower or "front-facing" in staging_lower or "looking directly" in staging_lower:
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
            ca = sp.get("camera_angle") if isinstance(sp, dict) else getattr(sp, "camera_angle", None)
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
        "a", "an", "the", "of", "in", "on", "at", "by", "with", "and", "or",
        "is", "are", "to", "from", "as", "that", "this", "it", "for", "its",
        "into", "over", "under", "through", "across", "between", "around",
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
            words = {w for w in re.sub(r"[^\w\s]", " ", env.lower()).split()
                     if w not in _STOP_WORDS and len(w) > 3}
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
            fl = sp.get("focal_length") if isinstance(sp, dict) else getattr(sp, "focal_length", None)
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

    if not model_override:
        return get_llm_provider(settings)

    provider_type = settings.llm_provider.lower()
    update: dict = {}
    if provider_type == "anthropic":
        update["anthropic_model"] = model_override
    elif provider_type == "gemini":
        update["gemini_text_model"] = model_override
    elif provider_type == "groq":
        update["groq_model"] = model_override
    elif provider_type == "ollama":
        update["ollama_model"] = model_override
    elif provider_type == "deepinfra":
        update["deepinfra_model"] = model_override

    if update:
        return get_llm_provider(settings.model_copy(update=update))
    return get_llm_provider(settings)


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
        logger.warning("Entity extraction returned invalid JSON; defaulting to abstract")
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
    lines.append("  - Narration is about an eagle and chick → prompt adds 'a man watching from a cliff' ❌")
    lines.append("  - Narration is about Bhagiratha → prompt adds a generic man in grey linen ❌")
    lines.append("  - Narration is a rhetorical question → prompt shows a specific person ❌")
    lines.append("")
    return "\n".join(lines)


def _build_entity_constraints_section(scenes: list[dict], entity_map: dict[int, SceneEntities]) -> str:
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
        lines.append(f"  category={entities.scene_category}  human_classification={entities.human_classification.value}: {hc_rule}")
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
            response = llm_client.generate(prompt, json_mode=True, temperature=0.0, model=model)
            data = _parse_json_response(response.text)
            if not data:
                logger.warning(
                    "LLM validation returned invalid JSON (model={}) — trying fallback", model
                )
                continue
            passed = bool(data.get("environment_ok", True)) and bool(data.get("human_ok", True))
            return passed, data.get("reason", "")
        except Exception as exc:
            logger.warning(
                "LLM validation call failed (model={}): {} — trying fallback", model, exc
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
                "Visual anchor attempt failed (model={}): {} — trying fallback", model, exc
            )

    logger.warning("Visual anchor batch failed on all models — proceeding without anchors")
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
            "branding: skipped closing asset card — "
            "closing.enabled={} asset_path={!r}",
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


def _write_prompts_file(
    project_id: str,
    scenes: list[dict],
    style: str | None,
    settings: Settings,
) -> Path:
    """
    Write IMAGE_PROMPTS.md to the images/ directory.
    The user can take these prompts to any image generator, download the images,
    and place them with the exact filename shown — the pipeline will use them
    automatically (skipping its own image generation for those scenes).
    """
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
            f"I am generating a {total_scenes}-scene philosophical documentary storyboard in a specific",
            "hybrid visual style. Keep this style consistent across every image.",
            "",
            "VISUAL STYLE: The environment in every image must be 100% photorealistic — architecture,",
            "nature, interiors, props, lighting, and shadows rendered as cinema photography. Human",
            "characters only are illustrated — premium hand-painted storybook style with clean ink",
            "outlines, soft cel shading, and graphic novel quality. Characters are composited into the",
            "photorealistic environment with matching lighting and realistic shadows.",
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
            "scene 1 back and say \"same hybrid style — continue with scene [X]\".",
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
        "- **Negative:** No text, no watermark, no subtitle, no logo",
        "- **Rendering:** Photorealistic environment (unless the prompt specifies otherwise)",
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
        "**Tip:** For spiritual documentary style, try Leonardo with the *Cinematic Kino* or",
        "*Photorealism* model. Set negative prompt: `text, watermark, logo, blurry, cartoon`",
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

    for scene in scenes:
        idx: int = scene["index"]
        filename = f"scene-{idx:03d}.png"
        save_path = abs_images_dir / filename
        vm = scene.get("visual_metadata", {})
        # V2: use structured_prompt.compiled_prompt if available; fall back to visual_prompt.
        # No "Storyboard Mode" language — compiled_prompt is self-contained.
        sp = scene.get("structured_prompt")
        if sp and not isinstance(sp, dict):
            prompt_text = sp.compiled_prompt
        elif isinstance(sp, dict):
            prompt_text = sp.get("compiled_prompt") or scene.get("visual_prompt", "")
        else:
            prompt_text = scene.get("visual_prompt", "")

        prompt_display = _strip_image_prompt_boilerplate(prompt_text)
        lines += [
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

    content = "\n".join(lines)
    out_path = images_dir / "IMAGE_PROMPTS.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


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
    out_path.write_text(
        json.dumps(gate_result.to_dict(), indent=2), encoding="utf-8"
    )
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
_VP_BOILERPLATE: frozenset[str] = frozenset({
    "hybrid", "cinematic", "style", "photorealistic", "environment",
    "illustrated", "hand", "painted", "storybook", "characters", "composited",
    "matching", "lighting", "shadows", "shot", "angle", "color", "colour",
    "palette", "continuity", "aspect", "ratio", "text", "watermark", "subtitle",
    "logo", "documentary", "quality", "realism", "depth", "field", "natural",
    "film", "grain", "image", "visual", "scene", "background", "foreground",
    "light", "warm", "cool", "camera", "wide", "medium", "close", "level",
    "cast", "shadow", "glow", "soft", "dark", "deep", "long", "high", "inch",
    # English stop words
    "this", "that", "with", "from", "into", "over", "under", "through",
    "across", "between", "around", "their", "there", "where", "which",
    "have", "been", "each", "same", "both", "will", "also", "more",
})


_CHARACTER_STRIP_RE = re.compile(
    r"illustrated\s+in\s+hand[- ]painted.*?(?:16[:\s]*9|no text|no watermark|$)",
    re.IGNORECASE | re.DOTALL,
)

# Words specific to character descriptions — stripped when comparing environments.
_CHARACTER_BOILERPLATE: frozenset[str] = frozenset({
    "lean", "young", "stubble", "shirt", "trousers", "clothing",
    "hair", "dark", "late", "20s", "plain", "simple", "wearing",
    "standing", "sitting", "facing", "profile", "posture", "pose",
    "variant", "back", "behind", "front", "shoulders", "arms",
    "hands", "pockets", "weight", "foot", "expression", "calm",
    "quiet", "determined", "reflective", "thoughtful", "peaceful",
    "storybook", "illustrated", "character", "composited", "outlines",
    "shading", "painterly", "realistic", "consistent", "previous",
})


def _extract_env_words(prompt: str) -> frozenset[str]:
    """Extract environment-describing words from a prompt, stripping
    character descriptions and boilerplate."""
    cleaned = _CHARACTER_STRIP_RE.sub(" ", prompt.lower())
    return frozenset(
        w for w in re.sub(r"[^\w\s]", " ", cleaned).split()
        if len(w) > 3
        and w not in _VP_BOILERPLATE
        and w not in _CHARACTER_BOILERPLATE
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
        w for w in re.sub(r"[^\w\s]", " ", prompt.lower()).split()
        if len(w) > 3 and w not in _VP_BOILERPLATE
    )
    if not words:
        return None
    for earlier_idx, earlier_prompt in sorted(earlier_prompts.items()):
        earlier_words = frozenset(
            w for w in re.sub(r"[^\w\s]", " ", earlier_prompt.lower()).split()
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
_STRONG_HUMAN_ROLES: frozenset[str] = frozenset({
    "king", "queen", "minister", "priest", "elder", "merchant", "soldier",
    "guard", "judge", "teacher", "master", "servant", "prince", "princess",
    "emperor", "crowd", "villager", "disciple", "farmer", "doctor", "hunter",
    "adviser", "advisor", "counselor", "monk", "sage", "warrior", "general",
    "swimmer", "fisherman", "shepherd", "pilgrim", "devotee", "speaker",
})

# Multi-word phrases that unambiguously indicate human presence.
# Single-word "man"/"woman" are too generic (mankind, ottoman, etc.) but
# these compound phrases are safe.
_STRONG_HUMAN_PHRASES: tuple[str, ...] = (
    "old man", "old woman", "young man", "young woman",
    "a man who", "a woman who", "the man who", "the woman who",
    "a man of", "a woman of",
    "his wife", "her husband", "his family", "a family",
    "his body", "her body", "his heart", "her heart",
    "his face", "her face", "his eyes", "her eyes",
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
    allowed_lower = {c.lower() for c in (sanitized_analysis.get("allowed_characters") or [])}
    forbidden_chars = sanitized_analysis.get("forbidden_characters") or []
    cleaned_forbidden: list[str] = []
    for char in forbidden_chars:
        char_lower = char.lower()
        if char_lower in allowed_lower:
            logger.debug("scene_analysis sanity: removing '{}' from forbidden (also allowed)", char)
            continue
        if len(char_lower) > 3 and re.search(r"\b" + re.escape(char_lower) + r"\b", narration_lower):
            logger.debug(
                "scene_analysis sanity: removing '{}' from forbidden (active in narration)", char
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
                target.value, hr,
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
            len(forbidden_objs), _MAX_FORBIDDEN_OBJECTS,
        )
        sanitized_analysis["forbidden_objects"] = []

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
            sub, style, prev_context=visual_diary or None,
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


def scene_planner_node(state: VideoState) -> dict:
    """
    Scene Planner Agent:
    1. Load script from state / disk
    2. Generate scene plan JSON with retry loop on parse failure
    3. Validate and fix duration totals
    4. Second-pass: enhance visual prompts with cinematography guidance
    5. Save scene-plan.json + scene-plan.md
    """
    settings = Settings()
    llm = get_llm_provider(settings)
    artifact_repo = ArtifactRepository()
    project_repo = ProjectRepository()

    topic = state["topic"]
    project_id = state["project_id"]
    style = state.get("style")

    project_repo.update_stage(project_id, "scenes", "running")
    style_label = f" [{style}]" if style else ""
    console.print(
        f"\n[bold cyan]🎬 Scene Planner Agent[/bold cyan]{style_label} — "
        f"planning scenes for: [italic]{topic}[/italic]\n"
    )

    # ── Idempotency: load existing plan from disk if available ────────────
    existing_plan_path = Path(WORKSPACE_DIR) / project_id / "scenes" / "scene-plan.json"
    if existing_plan_path.exists():
        existing = json.loads(existing_plan_path.read_text(encoding="utf-8"))
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
                    _scene["narration"] = _narration[len(_heading_text):].lstrip(" ,.:;")
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
                                _stale.name, _idx,
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
    visual_bible = _generate_visual_bible(script_md, llm, settings)
    if settings.VISUAL_BIBLE_ENABLED:
        console.print(
            f"  [green]✓[/green] Visual Bible: \"{visual_bible.dominant_metaphor[:60]}...\""
        )

    # ── Story Bible: locked character/location/world descriptions ─────────
    story_bible = StoryBible()
    if settings.VISUAL_BIBLE_ENABLED:
        console.print("  [cyan]→[/cyan] Generating Story Bible (characters, locations, world)...")
        all_narrations = _extract_all_narrations(script_md)
        story_bible = load_or_generate_story_bible(
            project_id=project_id,
            workspace_dir=WORKSPACE_DIR,
            narrations=all_narrations,
            llm=llm,
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

    # ── Phase 1: Python-based script splitting (no LLM, no truncation risk) ──
    # The LLM was reliably failing to return 25+ scenes in one JSON response —
    # Groq cuts off mid-stream when output tokens get large. Python splitting is
    # deterministic, instant, and preserves every word verbatim.
    console.print("  [cyan]→[/cyan] Phase 1: splitting script into scenes...")
    scenes: list[dict] = _split_script_to_scenes(script_md)

    # Detect channel closing scenes and mark them as asset scenes so that
    # image generation is skipped and the brand card is used instead.
    _mark_asset_scenes(scenes)
    asset_count = sum(1 for s in scenes if s.get("scene_type") in ("asset", "brand_card"))
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

    # ── Scene Analysis (NEW) — structured story-first grounding per scene ─────
    console.print("  [cyan]→[/cyan] Analyzing scenes for story-first grounding...")
    _analysis_llm = _get_cheap_llm(settings, "extraction")
    scene_analysis_map: dict[int, dict] = {}
    for scene in scenes:
        if scene.get("scene_type", "generated_image") == "generated_image":
            analysis = _analyze_scene(
                scene.get("narration", ""), scene["index"], _analysis_llm
            )
            scene_analysis_map[scene["index"]] = analysis
            scene["scene_analysis"] = analysis
    scene_analysis_section = build_scene_analysis_section(scene_analysis_map)
    console.print(
        f"  [green]✓[/green] Scene analysis complete for {len(scene_analysis_map)} scenes"
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
    entity_constraints_section = _build_entity_constraints_section(generated_scenes, entity_map)

    # ── Narrative-Visual Bridge (Task 2.7) ────────────────────────────────
    # Runs after entity extraction, before prompt generation, so abstract/
    # empty-chars scenes get a concrete literal directive instead of drifting
    # to generic aesthetic imagery. Non-blocking: on any failure scenes
    # generate exactly as before this task.
    _llm_validation_client = _get_cheap_llm(settings, "llm_validation")
    if settings.visual_anchor_enabled:
        visual_anchors = _build_visual_anchors(generated_scenes, _llm_validation_client, settings)
    else:
        visual_anchors = {}
    for scene in generated_scenes:
        scene["visual_anchor"] = visual_anchors.get(scene["index"], "")
    if visual_anchors:
        console.print(
            f"  [green]✓[/green] Visual anchors: {len(visual_anchors)}/{len(generated_scenes)} scenes"
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
            batch, style, prev_context=visual_diary or None,
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
            vp_list = _generate_vp_sub_batches(llm, batch, style, visual_diary, entity_constraints_section)
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
        for _ch in (_sc.get("scene_analysis", {}).get("allowed_characters") or []):
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
                    idx, attempt, dup_of,
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
                        scene.get("narration", ""), entities, current_prompt, _validation_llm
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
            if settings.faithfulness_llm_validation_enabled and _should_use_llm_validation(
                critical_error_codes
            ):
                llm_passed, llm_reason = _run_llm_validation(
                    scene_analysis, entities.human_classification, current_prompt,
                    _llm_validation_client, settings,
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
            "critical_errors": critical_error_codes if final_status == FaithfulnessStatus.FAILED else [],
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

    # ── Kai enforcement guards ────────────────────────────────────────────
    scenes = _enforce_primary_kai_spec(scenes)
    scenes = _enforce_closing_scene_primary(scenes)
    scenes = _enforce_kai_distribution(scenes, entity_map)
    scenes = _enforce_primary_kai_spec(scenes)  # re-run for newly promoted scenes
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
            )
            scene["structured_prompt"] = sp.model_dump()
            scene["visual_prompt"] = sp.compiled_prompt  # backward compat
        console.print(f"  [green]✓[/green] V2 structured prompts: {len(gen_scenes)} scenes")

        # Re-validate faithfulness_qa against the FINAL prompts (V2 override
        # may have resolved errors that were present in the pre-V2 prompts).
        for scene in gen_scenes:
            idx = scene["index"]
            entities = entity_map.get(idx)
            if not entities or not scene.get("faithfulness_qa"):
                continue
            sa = scene.get("scene_analysis", {})
            sa, ents = _sanitize_scene_analysis(sa, entities, scene.get("narration", ""))
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
                    "llm_validated": scene["faithfulness_qa"].get("llm_validated", False),
                    "llm_reason": scene["faithfulness_qa"].get("llm_reason", ""),
                }

    # ── V2: Post-V2 Kai re-enforcement ─────────────────────────────────
    # V2 may have generated aerial prompts for Kai-primary scenes despite
    # the shot_type constraint; demote those to absent so Step 0 is accurate.
    scenes = _enforce_primary_kai_spec(scenes)

    # ── V2: Sync visual_metadata from structured prompts ────────────────
    scenes = _sync_metadata_from_v2(scenes)

    # ── V2: Continuity validation (flag-and-log only) ─────────────────────
    continuity_warnings = _validate_visual_continuity(scenes, visual_bible)

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
    prompts_path = _write_prompts_file(project_id, scenes, style, settings)
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
