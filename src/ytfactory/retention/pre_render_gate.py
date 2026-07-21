from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from ytfactory.retention.models import (
    EmotionalIntensity,
    RetentionScoreResult,
    ScriptSegment,
)
from ytfactory.scenes.models import Scene
from ytfactory.shared.constants import WORKSPACE_DIR


TIER_2_MOTION_TYPES = {"fog", "dust", "particles", "light_rays"}


# ── Script text normalization ────────────────────────────────────────────────

_QUOTE_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u2032": "'", "\u2035": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2033": '"', "\u2036": '"',
}

_DASH_CHARS = (
    "\u2010\u2011\u2012\u2013\u2014\u2015"
    + chr(0x2E3) + chr(0x2E2)
)
_DASH_RE = re.compile(f"[{_DASH_CHARS}]")

_CONTRACTION_SUFFIX_RE = re.compile(
    r"(\w+)'s\b|(\w+)'re\b|(\w+)'ve\b|(\w+)'ll\b|(\w+)'d\b",
    re.IGNORECASE,
)
_CONTRACTIONS_TO_STRIP = {
    "let", "it", "he", "she", "who", "that", "there", "here",
    "what", "where", "when", "why", "how",
}

_SPECIAL_CONTRACTIONS = {
    "'em": "em",
    "'til": "til",
    "'cause": "cause",
    "'round": "round",
}


def _normalize_script_text(text: str) -> str:
    """
    Normalize script text to a canonical form so regex pattern matching
    is robust to natural-language variants:

    1. Unicode smart quotes → ASCII apostrophes / straight quotes
    2. Em-dash / en-dash / hyphen variants → space
    3. Common contraction suffixes ('s, 're, 've, 'll, 'd) → removed
    4. Special contractions ('em, 'til, 'cause, 'round) → canonical
    5. Collapse intra-paragraph whitespace (preserves paragraph boundaries)
    """
    # 1. Quotes
    for src, dst in _QUOTE_MAP.items():
        text = text.replace(src, dst)

    # 2. Dashes → space
    text = _DASH_RE.sub(" ", text)

    # 3. Contraction suffixes on word stems
    def _strip_contraction(m: re.Match) -> str:
        for group in m.groups():
            if group is not None:
                suffix = m.group(0)[len(group):]
                if suffix == "'s" and group.lower() not in _CONTRACTIONS_TO_STRIP:
                    return m.group(0)
                return group
        return m.group(0)

    text = _CONTRACTION_SUFFIX_RE.sub(_strip_contraction, text)

    # 4. Special contractions (no preceding word char)
    for src, dst in _SPECIAL_CONTRACTIONS.items():
        text = text.replace(src, dst)

    # 5. Collapse whitespace within the line (do NOT collapse across paragraphs)
    lines = text.split("\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in lines]
    return "\n".join(lines)


# ── Script parsing ────────────────────────────────────────────────────────────


def parse_script_to_segments(script_md: str) -> list[ScriptSegment]:
    """
    Heuristic splitter: paragraphs → ScriptSegments with lightweight
    classification (no LLM call). Keyword-based detection for frame labels,
    hooks, rehooks, bridges, and story-resolution markers.

    Input text is normalized before matching so that natural-language
    variants (curly quotes, em-dashes, contraction spacing) do not cause
    silent skips.
    """
    script_md = _normalize_script_text(script_md)
    segments: list[ScriptSegment] = []
    paragraphs = [p.strip() for p in script_md.split("\n\n") if p.strip()]

    frame_label_patterns = re.compile(
        r"\b(four truths|three lessons|five principles|"
        r"first truth|second truth|third truth|"
        r"key takeaway|let\s+explore|welcome to)\b",
        re.IGNORECASE,
    )
    hook_patterns = re.compile(
        r"\b(imagine|picture this|what if|have you ever|"
        r"let me tell you|here\s+(is\s+)?the\s+thing|the truth is)\b",
        re.IGNORECASE,
    )
    rehook_patterns = re.compile(
        r"\b(but here\s+(is\s+)?the\s+thing|and yet|so why|"
        r"what happens next|here\s+(is\s+)?where\s+it|but wait)\b",
        re.IGNORECASE,
    )
    bridge_patterns = re.compile(
        r"\b(this is the key|what this means|the deeper lesson|"
        r"reflection|pause and consider|think about this)\b",
        re.IGNORECASE,
    )
    resolves_story_patterns = re.compile(
        r"\b(and so it ended|in the end|ultimately|the moral|"
        r"that was the moment|from that day)\b",
        re.IGNORECASE,
    )
    peak_patterns = re.compile(
        r"\b(never forget|this changed everything|the most important|"
        r"nothing else mattered|forever changed|critical|essential)\b",
        re.IGNORECASE,
    )

    for para in paragraphs:
        text = para.strip()
        if not text:
            continue
        is_frame = bool(frame_label_patterns.search(text))
        is_hook = bool(hook_patterns.search(text))
        is_rehook = bool(rehook_patterns.search(text))
        is_bridge = bool(bridge_patterns.search(text))
        resolves = bool(resolves_story_patterns.search(text))
        intensity = EmotionalIntensity.PEAK if peak_patterns.search(text) else EmotionalIntensity.NORMAL
        segments.append(
            ScriptSegment(
                text=text,
                is_hook=is_hook,
                is_rehook=is_rehook,
                is_frame_label=is_frame,
                is_bridge=is_bridge,
                resolves_story=resolves,
                emotional_intensity=intensity,
            )
        )

    return segments


# ── Pre-render gate checks ────────────────────────────────────────────────────


def check_frame_naming_gate(segments: list[ScriptSegment]) -> list[str]:
    """
    Hard reject if any segment with is_frame_label=True appears before
    the first segment with is_rehook=True.
    """
    if not segments:
        return []

    first_rehook_idx = next(
        (i for i, s in enumerate(segments) if s.is_rehook), None
    )
    if first_rehook_idx is None:
        return ["No rehook found in script — frame naming gate cannot be satisfied."]

    violations = [
        f"Frame label appears before first rehook (segment {i}): '{segments[i].text[:80]}...'"
        for i, s in enumerate(segments[:first_rehook_idx])
        if s.is_frame_label
    ]
    return violations


def check_bridge_requirement(segments: list[ScriptSegment]) -> list[str]:
    """
    Flag if a story-resolution segment is immediately followed by a frame-label
    segment with no bridge segment between them.
    """
    violations: list[str] = []
    for i, seg in enumerate(segments[:-1]):
        if seg.resolves_story and not seg.is_bridge:
            next_seg = segments[i + 1]
            if next_seg.is_frame_label:
                violations.append(
                    f"Bridge missing at segment {i}→{i+1}: story resolution "
                    f"followed directly by frame label without a bridge line."
                )
    return violations


def assign_hold_required(scenes: list[Scene], segments: list[ScriptSegment]) -> None:
    """
    For each scene whose linked_segment has emotional_intensity == PEAK,
    set hold_required=True and extend duration by +1.5–2.0s.
    Sequencing rule: hold happens on the current scene before any
    pose/composition change — do not let the hold overlap a scene cut.
    """
    for scene in scenes:
        seg = _linked_segment(scene, segments)
        if seg and seg.emotional_intensity == EmotionalIntensity.PEAK:
            scene.hold_required = True
            extension = 1.75
            scene.duration_seconds = round(scene.duration_seconds + extension, 2)


def check_pose_variety(scenes: list[Scene]) -> list[str]:
    """Reject if the same pose repeats across 3+ consecutive scenes."""
    violations: list[str] = []
    poses = [s.pose for s in scenes if s.pose]
    if len(poses) < 3:
        return violations
    run_start = 0
    for i in range(1, len(poses)):
        if poses[i] != poses[i - 1]:
            run_len = i - run_start
            if run_len >= 3:
                violations.append(
                    f"Pose '{poses[run_start]}' repeats {run_len} consecutive scenes "
                    f"(scenes {run_start + 1}–{i})."
                )
            run_start = i
    run_len = len(poses) - run_start
    if run_len >= 3:
        violations.append(
            f"Pose '{poses[run_start]}' repeats {run_len} consecutive scenes "
            f"(scenes {run_start + 1}–{len(poses)})."
        )
    return violations


def check_composition_variety(scenes: list[Scene]) -> list[str]:
    """Flag if 'center' composition repeats 3+ consecutive scenes."""
    violations: list[str] = []
    comps = [s.composition for s in scenes if s.composition]
    center_runs = 0
    run_start = 0
    for i, c in enumerate(comps):
        if c == "center":
            if center_runs == 0:
                run_start = i
            center_runs += 1
        else:
            if center_runs >= 3:
                violations.append(
                    f"'center' composition repeats {center_runs} consecutive scenes "
                    f"(scenes {run_start + 1}–{i})."
                )
            center_runs = 0
    if center_runs >= 3:
        violations.append(
            f"'center' composition repeats {center_runs} consecutive scenes "
            f"(scenes {run_start + 1}–{len(comps)})."
        )
    return violations


def check_scene_durations(scenes: list[Scene]) -> list[str]:
    """Flag scenes outside 2–5s unless hold_required=True."""
    violations: list[str] = []
    for scene in scenes:
        if scene.hold_required:
            continue
        dur = scene.duration_seconds
        if dur < 2.0:
            violations.append(
                f"Scene {scene.index}: duration {dur}s below 2s minimum."
            )
        elif dur > 5.0:
            violations.append(
                f"Scene {scene.index}: duration {dur}s exceeds 5s maximum."
            )
    return violations


def plan_text_reveal(scene: Scene) -> None:
    """
    If scene.text_overlay is set and scene.duration > 5s, split into
    text_reveal_segments (word/phrase groups), each shown 1–2s.
    """
    if not scene.text_overlay or scene.duration_seconds <= 5.0:
        return
    words = scene.text_overlay.split()
    groups: list[str] = []
    chunk = 4
    for i in range(0, len(words), chunk):
        groups.append(" ".join(words[i : i + chunk]))
    scene.text_reveal_segments = groups


# ── Orchestrator ──────────────────────────────────────────────────────────────


def run_pre_render_gate(
    segments: list[ScriptSegment],
    scenes: list[Scene],
    project_dir: Path | None = None,
) -> RetentionScoreResult:
    """
    Runs §1.1–1.4 checks. Hard-reject on frame naming gate failure.
    Score deductions for everything else.
    """
    violations: list[str] = []
    breakdown: dict[str, float] = {
        "hook": 100.0,
        "story_flow": 100.0,
        "visuals_editing": 100.0,
    }

    frame_violations = check_frame_naming_gate(segments)
    if frame_violations:
        violations.extend(f"[P1a] {v}" for v in frame_violations)
        breakdown["story_flow"] = 0.0

    bridge_violations = check_bridge_requirement(segments)
    if bridge_violations:
        violations.extend(f"[P4] {v}" for v in bridge_violations)
        breakdown["story_flow"] = max(breakdown["story_flow"] - 20.0, 0.0)

    assign_hold_required(scenes, segments)

    for scene in scenes:
        plan_text_reveal(scene)

    pose_violations = check_pose_variety(scenes)
    if pose_violations:
        violations.extend(f"[P3] {v}" for v in pose_violations)
        breakdown["visuals_editing"] = max(breakdown["visuals_editing"] - 15.0, 0.0)

    comp_violations = check_composition_variety(scenes)
    if comp_violations:
        violations.extend(f"[P3] {v}" for v in comp_violations)
        breakdown["visuals_editing"] = max(breakdown["visuals_editing"] - 10.0, 0.0)

    dur_violations = check_scene_durations(scenes)
    if dur_violations:
        violations.extend(f"[P2] {v}" for v in dur_violations)
        breakdown["visuals_editing"] = max(breakdown["visuals_editing"] - 10.0, 0.0)

    tier2_violations = check_tier2_overlay_assets(scenes, project_dir)
    if tier2_violations:
        violations.extend(f"[T2] {v}" for v in tier2_violations)
        breakdown["visuals_editing"] = max(breakdown["visuals_editing"] - 15.0, 0.0)

    total = sum(breakdown.values()) / len(breakdown)
    passed = not frame_violations and total >= 85.0

    return RetentionScoreResult(
        total=round(total, 2),
        breakdown=breakdown,
        violations=violations,
        passed=passed,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _linked_segment(scene: Scene, segments: list[ScriptSegment]) -> ScriptSegment | None:
    """
    Resolve the linked ScriptSegment for a scene from its linked_segment dict,
    falling back to position-based matching if no explicit link exists.
    """
    if scene.linked_segment:
        if isinstance(scene.linked_segment, ScriptSegment):
            data = dataclasses.asdict(scene.linked_segment)
        else:
            data = dict(scene.linked_segment)

        valid_fields = {f.name for f in dataclasses.fields(ScriptSegment)}
        data = {k: v for k, v in data.items() if k in valid_fields}

        intensity = data.get("emotional_intensity")
        if isinstance(intensity, str):
            data["emotional_intensity"] = EmotionalIntensity(intensity)
        return ScriptSegment(**data)
    return None


def link_scenes_to_segments(
    scenes: list[dict],
    segments: list[ScriptSegment],
) -> list[dict]:
    """
    Greedy matcher: for each scene dict, find the unmatched segment whose text
    has the highest word overlap with the scene's narration. Stores the linked
    segment as a raw dict under the 'linked_segment' key. Mutates in-place
    and returns the same list.
    """
    used: set[int] = set()

    normalized_segments = [_normalize_script_text(seg.text) for seg in segments]
    segment_word_sets = [set(text.lower().split()) for text in normalized_segments]

    for scene in scenes:
        scene_narration = _normalize_script_text(scene.get("narration", ""))
        scene_words = set(scene_narration.lower().split())
        best_idx = -1
        best_overlap = 0
        for j in range(len(segments)):
            if j in used:
                continue
            seg_words = segment_word_sets[j]
            overlap = len(scene_words & seg_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_idx = j

        if best_idx >= 0:
            used.add(best_idx)
            scene["linked_segment"] = {
                "text": segments[best_idx].text,
                "start_time": segments[best_idx].start_time,
                "end_time": segments[best_idx].end_time,
                "is_hook": segments[best_idx].is_hook,
                "is_rehook": segments[best_idx].is_rehook,
                "is_frame_label": segments[best_idx].is_frame_label,
                "is_bridge": segments[best_idx].is_bridge,
                "resolves_story": segments[best_idx].resolves_story,
                "emotional_intensity": segments[best_idx].emotional_intensity.value,
            }

    return scenes


def check_tier2_overlay_assets(
    scenes: list[Scene],
    project_dir: Path | None = None,
) -> list[str]:
    """
    Flag Tier 2 motion types (fog/dust/particles/light_rays) when the
    corresponding overlay asset file does not exist. This is a cheap
    pre-render check that catches a planning-time metadata mismatch before
    rendering cost is sunk.
    """
    violations: list[str] = []
    if not project_dir:
        return violations

    search_dirs = [
        d
        for d in (
            project_dir / "assets" / "overlays",
            Path(WORKSPACE_DIR) / project_dir.name / "assets" / "overlays",
            project_dir.parent / "assets" / "overlays",
        )
        if d.is_dir()
    ]

    for scene in scenes:
        mtype = scene.motion_type
        if not mtype or mtype not in TIER_2_MOTION_TYPES:
            continue

        asset_name = f"{mtype}.mp4"
        found = any((d / asset_name).is_file() for d in search_dirs)
        if not found:
            violations.append(
                f"Scene {scene.index}: Tier 2 motion_type '{mtype}' requested but "
                f"no overlay asset found ({asset_name}) in assets/overlays/"
            )

    return violations

