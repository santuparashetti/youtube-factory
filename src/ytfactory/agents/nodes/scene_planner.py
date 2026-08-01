"""Scene planner node — Python splits narrations, LLM adds visual prompts only."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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
    prepend_storyboard_header,
)
from ytfactory.agents.state import VideoState
from ytfactory.branding.config import get_brand_config
from ytfactory.config.settings import Settings
from ytfactory.images.faithfulness_gate import evaluate_faithfulness_gate
from ytfactory.images.prompt_engine import ImagePromptEngineV4
from ytfactory.images.validators import (
    HUMAN_CLASSIFICATION_RULES,
    RETRY_RESPONSE_SCHEMA,
    HumanClassification,
    build_retry_prompt,
    compose_feedback,
    parse_retry_response,
    run_validators,
)
from ytfactory.scenes.models import FaithfulnessStatus
from ytfactory.shared.constants import WORKSPACE_DIR
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
) -> tuple[bool, str]:
    """Binary environment+human check via a cheap LLM call.

    Returns (passed, reason). Never blocks on failure — a parse error is
    treated as a pass so a flaky validator call can't stall the retry loop.
    """
    prompt = build_llm_validation_prompt(
        scene_category=scene_analysis.get("scene_category", "abstract"),
        human_classification=human_classification.value,
        environment=scene_analysis.get("environment", ""),
        visual_prompt=visual_prompt,
    )
    try:
        response = llm_client.generate(prompt, json_mode=True, temperature=0.0)
        data = _parse_json_response(response.text)
        if not data:
            logger.warning("LLM validation returned invalid JSON — accepting prompt")
            return True, "llm_parse_failed: invalid JSON"
        passed = bool(data.get("environment_ok", True)) and bool(data.get("human_ok", True))
        return passed, data.get("reason", "")
    except Exception as exc:
        logger.warning("LLM validation call failed: {} — accepting prompt", exc)
        return True, f"llm_parse_failed: {exc}"


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
) -> dict[int, str]:
    """Batch call: narration → visual_anchor per scene index.

    Falls back to an empty dict on any failure (non-blocking) — scenes then
    generate exactly as they did before this task.
    """
    prompt = _build_anchor_batch_prompt(scenes)
    try:
        response = cheap_llm_client.generate(prompt, json_mode=True, temperature=0.0)
        data = _parse_json_response(response.text)
        if not data:
            logger.warning("Visual anchor batch returned invalid JSON — proceeding without anchors")
            return {}
        return {
            int(k): v for k, v in data.items() if isinstance(v, str) and v.strip()
        }
    except Exception as exc:
        logger.warning("Visual anchor batch failed: {} — proceeding without anchors", exc)
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

    lines: list[str] = [
        f"# Image Prompts — {project_id}",
        f"**Style:** {style_label} | **Scenes:** {total_scenes} | **Size:** {w}×{h} px (16:9)",
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
        prompt_text = scene.get("visual_prompt", "")
        if scene.get("scene_type") != "brand_card":
            prompt_text = prepend_storyboard_header(prompt_text)

        lines += [
            f"## Scene {idx} — `{filename}`",
            "",
            f"**Save to:** `{save_path}`",
            "",
            f"**Narration:** _{scene.get('narration', '')}_",
            "",
            "**Image Prompt:**",
            "",
            f"> {prompt_text}",
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
        visual_anchors = _build_visual_anchors(generated_scenes, _llm_validation_client)
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
            else:
                for item in vp_list:
                    vp_map[item["index"]] = item["visual_prompt"]
                    if "visual_metadata" in item:
                        _vm_map[item["index"]] = item["visual_metadata"]

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
    retry_schema = RETRY_RESPONSE_SCHEMA if settings.scene_planner_strict_schema else None

    for scene in generated_scenes:
        idx = scene["index"]
        current_prompt = vp_map.get(idx, "")
        if not current_prompt:
            continue
        entities = entity_map.get(idx)
        if not entities:
            continue

        scene_analysis = scene.get("scene_analysis", {})
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
                    scene_analysis, entities.human_classification, current_prompt, _llm_validation_client
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
            )
            retry_resp = llm.generate(
                retry_prompt,
                json_mode=use_json_mode,
                json_schema=retry_schema,
                temperature=0.35,
            )
            parsed = parse_retry_response(retry_resp.text, idx)
            if parsed:
                current_prompt = parsed["visual_prompt"]
                last_violation = parsed.get("violation_addressed", "")
                vp_map[idx] = current_prompt
                logger.info("Scene {:03d} | retry passed parsing on attempt {}", idx, attempt)
            else:
                final_status = FaithfulnessStatus.FAILED
                attempts = attempt + 1
                logger.error("Scene {:03d} | retry parse failed on attempt {}", idx, attempt)
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
    scene_plan = {"topic": topic, "total_duration_seconds": total, "scenes": scenes}
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
