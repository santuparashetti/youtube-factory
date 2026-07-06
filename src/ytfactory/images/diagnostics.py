"""Image prompt diagnostics — V5 quality reporting.

DiagnosticsReport aggregates all quality signals into a single serializable
object.  It is produced by ImagePromptEngineV4 after visual prompts have
been generated and is written to image_prompt_debug.json when debug mode
is on.

V5 additions:
  • AI cliché detection  — patterns that produce stock-looking AI imagery
  • Unsafe composition detection — shot types removed from V5 safe defaults
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field

# Objects that signal unimaginative or over-used imagery.
# Each entry may be a substring match (checked case-insensitively).
_REPETITIVE_OBJECTS: tuple[str, ...] = (
    "mist",
    "fog",
    "candle",
    "candlelight",
    " lake",
    "throne",
    "empty room",
    "fireplace",
    "lantern",
    "lotus",
    "open book",
    "hourglass",
    "clock tower",
    "golden gate",
    "vast landscape",
    "lush greenery",
    "beautiful surroundings",
    "open plain",
)

# Quality keywords that signal the prompt is in the right documentary style.
_STYLE_MARKERS: tuple[str, ...] = (
    "photorealistic",
    "documentary",
    "cinematic",
    "no text",
    "no watermark",
)

# V5 — AI visual clichés that signal generic / low-quality image generation.
_AI_CLICHES: tuple[str, ...] = (
    "giant hands",
    "floating clock",
    "cracked desert",
    "cosmic portal",
    "empty throne",
    "glowing eyes",
    "broken chains",
    "third eye",
    "floating orb",
    "fractal",
    "digital matrix",
    "silhouette with rays",
    "glowing chakra",
    "galaxy within",
    "ethereal glow emanating",
)

# V5 — Shot types removed from safe defaults in V5 (macro/POV/extreme close-up).
# Flagged when they appear explicitly in the prompt text.
_UNSAFE_COMPOSITIONS: tuple[str, ...] = (
    "macro shot",
    "extreme close-up",
    "extreme closeup",
    "pov shot",
    "first-person view",
    "first person view",
    "point of view shot",
    "isolated hands",
    "disembodied hands",
)


@dataclass
class DiagnosticsReport:
    """Full quality report for a batch of generated visual prompts."""

    # ── Shot planning ─────────────────────────────────────────────────────
    shot_distribution: dict[str, int] = field(default_factory=dict)
    consecutive_shot_repeats: list[int] = field(default_factory=list)  # 1-based indices

    # ── Character continuity ──────────────────────────────────────────────
    character_continuity_ok: bool = True
    protagonist_description: str = ""

    # ── Prompt uniqueness ─────────────────────────────────────────────────
    total_prompts: int = 0
    unique_prompts: int = 0
    unique_prompt_ratio: float = 1.0  # unique / total

    # ── Repetitive objects ────────────────────────────────────────────────
    repeated_objects: dict[str, list[int]] = field(default_factory=dict)

    # ── Visual diversity ──────────────────────────────────────────────────
    diversity_score: float = 1.0  # 0.0–1.0

    # ── Style consistency ─────────────────────────────────────────────────
    style_consistent: bool = True
    scenes_missing_style_markers: list[int] = field(default_factory=list)

    # ── Prompt lengths ────────────────────────────────────────────────────
    prompt_lengths: list[int] = field(default_factory=list)  # word counts per scene

    # ── V5 — AI clichés and unsafe compositions ───────────────────────────────
    ai_cliches_detected: dict[str, list[int]] = field(default_factory=dict)
    unsafe_compositions_detected: dict[str, list[int]] = field(default_factory=dict)

    # ── Human quality tracking ────────────────────────────────────────────
    human_scenes_count: int = 0
    human_quality_enforced: int = 0
    human_quality_missing: list[int] = field(default_factory=list)

    # ── Issues ────────────────────────────────────────────────────────────
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def build_report(scenes: list[dict], shot_plan: list[str]) -> DiagnosticsReport:
    """
    Compute a DiagnosticsReport from a list of scenes and their shot plan.

    Only examines scenes with scene_type == "generated_image" (or unset).
    Asset scenes are excluded from prompt quality checks.
    """
    report = DiagnosticsReport()

    generated = [
        s for s in scenes if s.get("scene_type", "generated_image") == "generated_image"
    ]
    prompts = [s.get("visual_prompt", "") for s in generated]
    indices = [s.get("index", i + 1) for i, s in enumerate(generated)]

    report.total_prompts = len(prompts)
    report.prompt_lengths = [len(p.split()) for p in prompts]

    # ── Shot distribution ─────────────────────────────────────────────────
    counts = Counter(shot_plan)
    report.shot_distribution = dict(counts)

    for i in range(1, len(shot_plan)):
        if shot_plan[i] == shot_plan[i - 1]:
            report.consecutive_shot_repeats.append(i + 1)

    # ── Prompt uniqueness (word-overlap Jaccard similarity) ───────────────
    report.unique_prompts = _count_unique_prompts(prompts)
    if report.total_prompts > 0:
        report.unique_prompt_ratio = report.unique_prompts / report.total_prompts

    # ── Repetitive objects ────────────────────────────────────────────────
    object_scenes: dict[str, list[int]] = {}
    for obj in _REPETITIVE_OBJECTS:
        matches = [
            indices[i] for i, p in enumerate(prompts) if obj.lower() in p.lower()
        ]
        if len(matches) >= 2:
            object_scenes[obj.strip()] = matches
    report.repeated_objects = object_scenes

    # ── Style consistency ─────────────────────────────────────────────────
    missing_style = []
    for i, prompt in enumerate(prompts):
        p_lower = prompt.lower()
        if not any(m in p_lower for m in _STYLE_MARKERS):
            missing_style.append(indices[i])
    report.scenes_missing_style_markers = missing_style
    report.style_consistent = len(missing_style) == 0

    # ── V5: AI cliché detection ───────────────────────────────────────────
    cliche_scenes: dict[str, list[int]] = {}
    for cliche in _AI_CLICHES:
        matches = [
            indices[i] for i, p in enumerate(prompts) if cliche.lower() in p.lower()
        ]
        if matches:
            cliche_scenes[cliche] = matches
    report.ai_cliches_detected = cliche_scenes

    # ── V5: Unsafe composition detection ─────────────────────────────────
    unsafe_scenes: dict[str, list[int]] = {}
    for comp in _UNSAFE_COMPOSITIONS:
        matches = [
            indices[i] for i, p in enumerate(prompts) if comp.lower() in p.lower()
        ]
        if matches:
            unsafe_scenes[comp] = matches
    report.unsafe_compositions_detected = unsafe_scenes

    # ── Human quality tracking ────────────────────────────────────────────
    from ytfactory.images.human_detector import (
        detect_human_presence,
        has_human_quality_reinforcement,
    )

    for i, scene in enumerate(generated):
        prompt = scene.get("visual_prompt", "")
        if detect_human_presence(prompt):
            report.human_scenes_count += 1
            if has_human_quality_reinforcement(prompt):
                report.human_quality_enforced += 1
            else:
                report.human_quality_missing.append(indices[i])

    # ── Diversity score ───────────────────────────────────────────────────
    report.diversity_score = _compute_diversity_score(report)

    # ── Issues list ───────────────────────────────────────────────────────
    if report.consecutive_shot_repeats:
        report.issues.append(
            f"Consecutive shot repeats at scenes: {report.consecutive_shot_repeats}"
        )
    if report.repeated_objects:
        for obj, scene_list in report.repeated_objects.items():
            report.issues.append(
                f"Repetitive object '{obj}' found in scenes: {scene_list}"
            )
    if not report.style_consistent:
        report.issues.append(
            f"Scenes missing style markers: {report.scenes_missing_style_markers}"
        )
    if report.unique_prompt_ratio < 0.8 and report.total_prompts > 3:
        report.issues.append(
            f"Low prompt uniqueness: {report.unique_prompt_ratio:.0%} unique"
        )
    if report.ai_cliches_detected:
        for cliche, scene_list in report.ai_cliches_detected.items():
            report.issues.append(
                f"AI cliché '{cliche}' found in scenes: {scene_list}"
            )
    if report.unsafe_compositions_detected:
        for comp, scene_list in report.unsafe_compositions_detected.items():
            report.issues.append(
                f"Unsafe composition '{comp}' found in scenes: {scene_list}"
            )
    if report.diversity_score < 0.5:
        report.issues.append(
            f"Low visual diversity score: {report.diversity_score:.2f}"
        )
    if report.human_quality_missing:
        report.issues.append(
            f"Human scenes missing quality reinforcement: {report.human_quality_missing}"
        )

    return report


def _count_unique_prompts(prompts: list[str]) -> int:
    """Count prompts that are not too similar to any earlier prompt.

    Uses simple bag-of-words Jaccard similarity.
    A prompt is 'unique' if its similarity to every earlier prompt is < 0.5.
    """
    if not prompts:
        return 0

    def _words(text: str) -> set[str]:
        return set(re.findall(r"\b[a-z]{4,}\b", text.lower()))

    unique_count = 1  # first prompt is always unique
    seen_word_sets = [_words(prompts[0])]

    for prompt in prompts[1:]:
        ws = _words(prompt)
        is_unique = True
        for seen in seen_word_sets:
            if ws and seen:
                intersection = len(ws & seen)
                union = len(ws | seen)
                if union > 0 and intersection / union >= 0.5:
                    is_unique = False
                    break
        if is_unique:
            unique_count += 1
        seen_word_sets.append(ws)

    return unique_count


def _compute_diversity_score(report: DiagnosticsReport) -> float:
    """Score from 0.0 to 1.0. Start at 1.0, deduct for each quality issue."""
    score = 1.0

    # Consecutive shot repeats: -0.1 each
    score -= 0.1 * len(report.consecutive_shot_repeats)

    # Repeated objects: -0.05 each unique object that repeats
    score -= 0.05 * len(report.repeated_objects)

    # Low uniqueness: deduct proportionally
    if report.total_prompts > 3:
        score -= max(0.0, (0.8 - report.unique_prompt_ratio) * 2)

    # Missing style markers: -0.02 per scene
    score -= 0.02 * len(report.scenes_missing_style_markers)

    # V5: AI clichés: -0.05 per unique cliché detected
    score -= 0.05 * len(report.ai_cliches_detected)

    # V5: Unsafe compositions: -0.05 per unique pattern detected
    score -= 0.05 * len(report.unsafe_compositions_detected)

    return max(0.0, min(1.0, score))
