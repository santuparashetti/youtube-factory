"""Image Prompt QA/Fix Pass — semantic narration-fidelity check before export.

One LLM call reviews all generated-image prompts and repairs only the violating
portions.  The LLM is an EDITOR, not a replacement writer.

Priority hierarchy enforced:
  1. NARRATION (highest)
  2. Scene intent / beat
  3. Visual Bible / dominant visual world
  4. Character + environment metadata
  5. Continuity
  6. Hybrid visual style
  7. Cinematic composition/style

Core rule: image prompts exist to support the narration.  Narration wins every
conflict.  Metadata wins conflicts with the prompt unless doing so would
contradict the narration — then narration + scene intent resolve.

Critical protections (always applied, override other rules):
  1. Never remove required subjects.
  2. Never invent subjects.
  3. Narration semantic fidelity preserved.
  4. Intentional abstraction (CTA, compositor, end-screen) left intact.
  5. Visual Bible architecture never altered.
  6. Subject/action fields never verbatim-duplicated.
  7. Existing prompt preserved unless a concrete violation is found.
  8. Repairs must not create continuity breaks.
  9. Hybrid style (illustrated characters, photorealistic environments) preserved.
  10. Uncertainty = no change (confidence rule).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from video_core.providers.llm.base import LLMProvider


# ---------------------------------------------------------------------------
# Deterministic post-QA field normalization
# ---------------------------------------------------------------------------

# Structural field labels — always kept; never treated as auxiliary duplicates.
_STRUCTURAL_FIELDS: frozenset[str] = frozenset({
    "PRIMARY SUBJECT", "PRIMARY ACTION", "ENVIRONMENT", "COMPOSITION",
    "CAMERA", "STYLE", "LIGHTING", "CONTINUITY", "NEGATIVE",
})

# Matches a labeled field header at the start of a line:
# "UPPER LABEL: " — one or more uppercase words (with digits/underscores/spaces),
# followed by colon+whitespace.
_FIELD_RE = re.compile(r'^([A-Z][A-Z0-9 _]{0,30}?):\s+')


def _field_words(text: str) -> frozenset[str]:
    """Normalize text to a word-set for similarity comparison."""
    return frozenset(re.sub(r'[^\w\s]', ' ', text.lower()).split())


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _fraction_contained(subset: frozenset[str], container: frozenset[str]) -> float:
    """Fraction of *subset*'s words that appear in *container*."""
    if not subset:
        return 0.0
    return len(subset & container) / len(subset)


def normalize_prompt_fields(prompt: str) -> tuple[str, list[str]]:
    """Deterministic post-QA normalization — removes duplicate subject/spec blocks.

    Two rules applied (in order, per line):

    Rule 1 — PRIMARY ACTION verbatim copy:
        If PRIMARY ACTION content is near-identical to PRIMARY SUBJECT
        (Jaccard ≥ 0.95), the PRIMARY ACTION line is dropped.  It adds no
        information beyond restating the subject.

    Rule 2 — Auxiliary field redundancy:
        If an auxiliary (non-structural) field's word-set is ≥ 75% contained
        in either PRIMARY SUBJECT or PRIMARY ACTION, the auxiliary line is
        dropped.  Example: an ``ANT: …`` character block that merely repeats
        what PRIMARY ACTION already says about the ant.

    Returns (normalized_prompt, list_of_changes) where *changes* describes
    each removal.  Returns the original prompt unchanged if no rules fire.
    """
    if not prompt or not prompt.strip():
        return prompt, []

    lines = prompt.splitlines()

    # Collect first-occurrence values for the two reference fields.
    field_values: dict[str, str] = {}
    for line in lines:
        m = _FIELD_RE.match(line)
        if m:
            label = m.group(1)
            if label not in field_values:
                field_values[label] = line[m.end():]

    subj_words = _field_words(field_values.get("PRIMARY SUBJECT", ""))
    action_words = _field_words(field_values.get("PRIMARY ACTION", ""))

    changes: list[str] = []
    lines_out: list[str] = []

    for line in lines:
        m = _FIELD_RE.match(line)
        if not m:
            lines_out.append(line)
            continue

        label = m.group(1)
        value_words = _field_words(line[m.end():])

        # Rule 1: PRIMARY ACTION is a near-verbatim copy of PRIMARY SUBJECT.
        if label == "PRIMARY ACTION" and subj_words:
            sim = _jaccard(subj_words, value_words)
            if sim >= 0.95:
                changes.append(
                    f"Removed PRIMARY ACTION (verbatim copy of PRIMARY SUBJECT,"
                    f" Jaccard={sim:.2f})"
                )
                continue

        # Rule 2: Auxiliary field substantially covered by PRIMARY SUBJECT / ACTION.
        if label not in _STRUCTURAL_FIELDS:
            if subj_words and _fraction_contained(value_words, subj_words) >= 0.75:
                changes.append(
                    f"Removed auxiliary field '{label}'"
                    f" (≥75% of content already in PRIMARY SUBJECT)"
                )
                continue
            if action_words and _fraction_contained(value_words, action_words) >= 0.75:
                changes.append(
                    f"Removed auxiliary field '{label}'"
                    f" (≥75% of content already in PRIMARY ACTION)"
                )
                continue

        lines_out.append(line)

    return "\n".join(lines_out), changes


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PromptQAIssue:
    check: str
    description: str


@dataclass
class PromptQASceneResult:
    scene_index: int
    original_prompt: str
    repaired_prompt: str
    issues: list[PromptQAIssue] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    unresolved: list[PromptQAIssue] = field(default_factory=list)


@dataclass
class PromptQAReport:
    status: str  # "PASS" | "REVIEW_REQUIRED"
    scenes_checked: int
    issues_found: int
    issues_fixed: int
    repairs_applied: int  # actual prompt mutations written to scenes
    unresolved: list[dict]
    scene_results: list[PromptQASceneResult] = field(default_factory=list)
    normalization_applied: int = 0  # prompts changed by post-QA deterministic normalization

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "scenes_checked": self.scenes_checked,
            "issues_found": self.issues_found,
            "issues_fixed": self.issues_fixed,
            "repairs_applied": self.repairs_applied,
            "normalization_applied": self.normalization_applied,
            "unresolved": self.unresolved,
            "scene_results": [
                {
                    "scene_index": r.scene_index,
                    "original_prompt": r.original_prompt,
                    "repaired_prompt": r.repaired_prompt,
                    "issues": [
                        {"check": i.check, "description": i.description}
                        for i in r.issues
                    ],
                    "fixes": r.fixes,
                    "unresolved": [
                        {"check": i.check, "description": i.description}
                        for i in r.unresolved
                    ],
                }
                for r in self.scene_results
            ],
        }


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_QA_SYSTEM_PROMPT = """\
You are a strict semantic-consistency editor for documentary video production.

Your job: find missing required elements, contradictions, and impossible instructions.
Repair ONLY the violating portions.  You are an EDITOR, not a replacement writer.
Do NOT rewrite or improve a prompt merely because you would phrase it differently.

PRIORITY HIERARCHY — enforce in this order:
  1. NARRATION — highest priority
  2. Scene intent / beat
  3. Visual Bible / dominant visual world
  4. Character + environment metadata
  5. Continuity
  6. Hybrid visual style
  7. Cinematic composition/style

CORE RULE: Image prompts exist to visually support the narration.  If a prompt conflicts
with the narration, fix the prompt.  Never sacrifice narration fidelity for visual novelty.

NARRATION means semantic fidelity, NOT literal word matching.

CRITICAL PROTECTIONS — these override every other instruction:

  1. NEVER REMOVE REQUIRED SUBJECTS
     If narration, [Visual:], PRIMARY SUBJECT, scene_analysis, or explicit metadata
     requires a person, host, animal, bird, ant, or other character — preserve that subject
     and repair the prompt around it.  NEVER convert the scene to environment-only.  NEVER
     remove a subject merely because the environment prompt can stand without it.
     Only remove a subject when authoritative metadata explicitly forbids it
     (e.g. CHARACTER_PRESENCE: [] and ANCHOR_ROLE: absent and no narration mention).

  2. NEVER INVENT SUBJECTS
     Do not add people, animals, props, locations, or actions not supported by narration,
     scene analysis, beat purpose, Visual Bible, or the existing prompt.  Do not invent
     visual content merely to make narration "more visual."

  3. NARRATION SEMANTIC FIDELITY
     Every important concrete element in narration must remain visually represented when
     appropriate.  Do not replace a specific narrated action/object/person with a generic
     symbolic scene unless the existing scene architecture explicitly calls for symbolic
     treatment.

  4. PRESERVE INTENTIONAL ABSTRACTION
     Do NOT force literal visuals for: philosophical statements, abstract concepts,
     CTA/engagement narration, compositor-owned text, end-screen elements, [Text Overlay],
     or [End Screen] scenes.  For compositor-owned elements, reserve clean visual space but
     do not generate text, logos, or buttons in the prompt.

  5. DO NOT ALTER VISUAL BIBLE ARCHITECTURE
     Do not introduce a competing visual world, recurring character, environment, palette, or
     metaphor.  Do not remove an established visual motif merely because the current narration
     is abstract.

  6. SUBJECT/ACTION FIELD RULES
     PRIMARY SUBJECT identifies WHO/WHAT is present.
     PRIMARY ACTION describes what that subject is doing — it must not be a verbatim copy of
     PRIMARY SUBJECT.
     Do not create duplicate character blocks (ANT:, BIRD:, PERSON:, etc.) when the same
     specification already exists in PRIMARY SUBJECT.
     Preserve useful existing detail; normalize duplication rather than rewriting the scene.

  7. EXISTING PROMPT PRESERVATION
     If a prompt is already faithful and valid, return it UNCHANGED.
     Prefer the smallest repair possible.
     Explicitly forbidden: rewriting prose for style, changing camera without evidence,
     changing composition without evidence, changing era without evidence, changing
     environment without evidence, replacing a character with an environment, adding
     decorative details, introducing new metaphors.

  8. CONTINUITY PROTECTION
     A repair must not create: character disappearance, character duplication, environment
     contradiction, era contradiction, Visual Bible contradiction, an impossible action, or
     conflict with adjacent-scene continuity.

  9. HYBRID STYLE PRESERVATION
     Environments = photorealistic.
     Humans / animals / birds = illustrated storybook style.
     Never render characters in a photorealistic style.

  10. CONFIDENCE RULE
      If uncertain whether something is a violation — DO NOT CHANGE IT.
      Return the original prompt.  Only repair when there is clear evidence of a concrete
      violation.

QA CHECKS — for EVERY scene verify:
  A. Prompt accurately represents the narration's important subjects, actions, relationships,
     meaning and emotion.  Narration is the highest-priority source — every important subject,
     action and relationship required by the narration must be visually present in the prompt.
  B. Prompt fulfills the scene/beat purpose.
  C. No unrelated story, metaphor, character, setting or action is invented.
  D. Character presence exactly matches scene metadata.
     "CHARACTER_PRESENCE: []" (NONE) means no human, animal, bird or character appears.
     Never say "no character present" when an animal or bird is visible — they are subjects.
     Animals count as visual subjects.
  E. Human characters follow the required illustrated style.  Animal subjects also follow the
     required illustrated style — never treat an animal as a background environment-only element.
  F. Environments remain photorealistic.
  G. Dominant visual world remains coherent with the VISUAL BIBLE provided.
     Do not introduce an unrelated visual world, setting, era or recurring subject.
  H. Character/environment continuity is preserved where required.
  I. No contradictory composition or camera instructions exist inside the prompt.
     Examples of contradictions: extreme macro AND wide establishing shot; side profile AND
     frontal portrait; tiny subject AND frame-filling subject.
     Preserve the intended composition and make the smallest correction.
  J. No readable text, titles, quotes, UI, logos or branding unless explicitly designated as
     a compositor/branding scene.  Preserve scenes explicitly designed for text overlay.
     Use clean space for compositor overlays when not a designated branding scene.
  K. Props/objects are supported by narration or scene intent.
  L. Spatial and action feasibility: subjects, actions and environments must physically make
     sense together.  Catch impossible scale, placement or interaction (e.g. a person standing
     inside a microscopic space; objects in physically impossible positions or relationships).
  M. Duplicate or contradictory subject fields: detect duplicated subject blocks or conflicting
     descriptions (e.g. "PRIMARY SUBJECT: Ant …" plus a redundant "ANT: …" block).
     Consolidate and reconcile without losing valid information.

REPAIR RULES:
  - Fix ONLY the violating portion.  Do NOT rewrite or improve a prompt merely because you
    would phrase it differently.
  - Preserve all valid visual details.
  - Preserve the intended scene concept and visual architecture.
  - Preserve narration meaning.  Never change narration.
  - Do not add creative elements just to make the image more interesting.
  - When a scene has no concrete violation: return the original prompt UNCHANGED.
  - NARRATION WINS every conflict with the prompt (highest priority).
  - METADATA WINS conflicts with the prompt unless it contradicts the narration; \
then resolve using narration + scene intent.
  - FORBIDDEN_CHARACTERS must never appear in the repaired prompt.
  - Apply Critical Protections 1–10 before emitting any repaired_prompt.

OUTPUT FORMAT — return ONLY valid JSON (no markdown fences), exactly this shape:
{
  "status": "PASS",
  "scenes_checked": <int>,
  "issues_found": <int>,
  "issues_fixed": <int>,
  "unresolved": [],
  "scene_results": [
    {
      "scene_index": <int>,
      "issues": [{"check": "<letter A-M>", "description": "<what is wrong>"}],
      "fixes": ["<description of what was changed>"],
      "repaired_prompt": "<full repaired prompt or original if no changes>",
      "unresolved": [{"check": "<letter A-M>", "description": "<why it cannot be fixed>"}]
    }
  ]
}

If a scene has no issues, set "issues": [], "fixes": [], "unresolved": [] and \
"repaired_prompt" equal to the original prompt.
If ANY scene has unresolved issues, set top-level "status": "REVIEW_REQUIRED".
Do NOT change narration, scene count, or the Visual Bible architecture.
Do NOT emit markdown fences.  Raw JSON only.\
"""


def _format_visual_bible_section(visual_bible: dict) -> str:
    """Format visual_bible fields into a readable constraint block."""
    lines = ["PROJECT VISUAL BIBLE (project-level visual constraints — enforce check G):"]
    dm = visual_bible.get("dominant_metaphor", "")
    if dm:
        lines.append(f"  DOMINANT_METAPHOR: {dm}")
    ae = visual_bible.get("anchor_environments", "")
    if ae:
        lines.append(f"  ANCHOR_ENVIRONMENTS: {ae}")
    ca = visual_bible.get("color_arc", "")
    if ca:
        lines.append(f"  COLOR_ARC: {ca}")
    vm = visual_bible.get("visual_motifs", "")
    if vm:
        lines.append(f"  VISUAL_MOTIFS: {vm}")
    return "\n".join(lines)


def _format_visual_metadata(vm: Any) -> str:
    """Format visual_metadata into a compact string."""
    if not vm:
        return ""
    if not isinstance(vm, dict):
        try:
            vm = vm.model_dump()
        except AttributeError:
            return ""
    parts = []
    for key in ("era", "narrative_role", "environment", "mood", "visual_style"):
        val = vm.get(key, "")
        if val:
            parts.append(f"{key}={val}")
    return " ".join(parts)


def _format_scene_analysis(sa: Any) -> str:
    """Format scene_analysis into a compact string for the QA prompt."""
    if not sa:
        return ""
    if not isinstance(sa, dict):
        try:
            sa = sa.model_dump()
        except AttributeError:
            return ""
    parts = []
    subj = sa.get("primary_subject", "")
    if subj:
        parts.append(f"subject={subj}")
    allowed = sa.get("allowed_characters", [])
    if allowed:
        parts.append(f"allowed_chars={allowed}")
    forbidden = sa.get("forbidden_characters", [])
    if forbidden:
        parts.append(f"forbidden_chars={forbidden}")
    goal = sa.get("story_goal", "")
    if goal:
        parts.append(f"goal={goal}")
    beat = sa.get("emotional_beat", "")
    if beat:
        parts.append(f"emotional_beat={beat}")
    return " ".join(parts)


def _build_qa_prompt(
    scenes: list[dict],
    visual_bible: dict | None = None,
    scene_analysis_map: dict | None = None,
) -> str:
    """Build the single batch QA prompt for all generated-image scenes."""
    scene_blocks: list[str] = []
    for s in scenes:
        if s.get("scene_type", "generated_image") != "generated_image":
            continue
        idx = s["index"]
        narration = s.get("narration", "").strip()
        visual_prompt = s.get("visual_prompt", "").strip()
        character_presence = s.get("character_presence") or []
        anchor_role = s.get("anchor_role", "absent")
        beat = s.get("assigned_beat", "")
        narrative_purpose = s.get("narrative_purpose", "")

        block = (
            f"SCENE {idx}:\n"
            f"  NARRATION: {narration}\n"
            f"  CHARACTER_PRESENCE: {character_presence if character_presence else []}\n"
            f"  ANCHOR_ROLE: {anchor_role}\n"
        )
        if beat:
            block += f"  BEAT: {beat}\n"
        if narrative_purpose:
            block += f"  BEAT_PURPOSE: {narrative_purpose}\n"

        vm_str = _format_visual_metadata(s.get("visual_metadata"))
        if vm_str:
            block += f"  VISUAL_METADATA: {vm_str}\n"

        sa = (scene_analysis_map or {}).get(idx) if scene_analysis_map else s.get("scene_analysis")
        sa_str = _format_scene_analysis(sa)
        if sa_str:
            block += f"  SCENE_ANALYSIS: {sa_str}\n"

        block += f"  VISUAL_PROMPT: {visual_prompt}"
        scene_blocks.append(block)

    if not scene_blocks:
        return ""

    scenes_text = "\n\n".join(scene_blocks)

    parts = [_QA_SYSTEM_PROMPT, ""]
    if visual_bible:
        parts.append(_format_visual_bible_section(visual_bible))
        parts.append("")
    parts.append("SCENES TO REVIEW:\n")
    parts.append(scenes_text)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


def _parse_qa_response(text: str, scenes: list[dict]) -> PromptQAReport | None:
    """Parse the LLM JSON response into a PromptQAReport."""
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Prompt QA: JSON parse failed — {}", exc)
        return None

    if not isinstance(data, dict):
        return None

    scene_results: list[PromptQASceneResult] = []
    # Build a fast lookup for original prompts
    prompt_by_index: dict[int, str] = {
        s["index"]: s.get("visual_prompt", "")
        for s in scenes
        if s.get("scene_type", "generated_image") == "generated_image"
    }

    for sr in data.get("scene_results", []):
        if not isinstance(sr, dict):
            continue
        idx = sr.get("scene_index")
        if not isinstance(idx, int):
            continue
        original = prompt_by_index.get(idx, "")
        repaired = sr.get("repaired_prompt") or original

        issues = [
            PromptQAIssue(
                check=i.get("check", ""),
                description=i.get("description", ""),
            )
            for i in (sr.get("issues") or [])
            if isinstance(i, dict)
        ]
        unresolved = [
            PromptQAIssue(
                check=i.get("check", ""),
                description=i.get("description", ""),
            )
            for i in (sr.get("unresolved") or [])
            if isinstance(i, dict)
        ]
        fixes = [str(f) for f in (sr.get("fixes") or [])]

        scene_results.append(
            PromptQASceneResult(
                scene_index=idx,
                original_prompt=original,
                repaired_prompt=repaired,
                issues=issues,
                fixes=fixes,
                unresolved=unresolved,
            )
        )

    # Derive unresolved authoritatively from per-scene data.  The LLM's top-level
    # "unresolved" field is advisory; use it only when per-scene results are absent.
    per_scene_unresolved: list[dict] = [
        {"check": issue.check, "description": issue.description}
        for r in scene_results
        for issue in r.unresolved
    ]
    unresolved_list = per_scene_unresolved if per_scene_unresolved else (
        data.get("unresolved", []) or []
    )
    # Status must be REVIEW_REQUIRED whenever any unresolved item exists, even if
    # the LLM incorrectly reported PASS at the top level.
    status = "REVIEW_REQUIRED" if unresolved_list else data.get("status", "PASS")

    scenes_checked = data.get("scenes_checked", len(scene_results))
    issues_found = data.get("issues_found", sum(len(r.issues) for r in scene_results))
    issues_fixed = data.get("issues_fixed", sum(len(r.fixes) for r in scene_results))

    return PromptQAReport(
        status=status,
        scenes_checked=scenes_checked,
        issues_found=issues_found,
        issues_fixed=issues_fixed,
        repairs_applied=0,  # filled in after apply step
        unresolved=unresolved_list,
        scene_results=scene_results,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_prompt_qa_pass(
    scenes: list[dict],
    llm: LLMProvider,
    *,
    visual_bible: dict | None = None,
    scene_analysis_map: dict | None = None,
    model_override: str = "",
) -> PromptQAReport | None:
    """Run one LLM QA/fix pass over all generated-image prompts.

    Applies repaired prompts to ``scenes`` in place.
    Returns a ``PromptQAReport`` or ``None`` if the LLM call fails or returns
    unparseable output (caller should log and continue without blocking).

    Args:
        scenes:             The scene list; generated_image scenes are checked.
        llm:                An LLMProvider instance to use for the call.
        visual_bible:       Optional project-level Visual Bible dict (dominant_metaphor,
                            anchor_environments, color_arc, visual_motifs).  When
                            provided, QA can enforce visual-world coherence (check G).
        scene_analysis_map: Optional mapping of scene_index → analysis dict
                            (primary_subject, allowed/forbidden characters, story_goal,
                            emotional_beat).  When provided, QA has authoritative
                            character/context data for checks C and D.
        model_override:     If non-empty, overrides the model on the provider call
                            (not supported by all providers; silently ignored).
    """
    gen_scenes = [
        s for s in scenes
        if s.get("scene_type", "generated_image") == "generated_image"
    ]
    if not gen_scenes:
        logger.info("Prompt QA: no generated-image scenes — skipping")
        return None

    prompt = _build_qa_prompt(scenes, visual_bible=visual_bible, scene_analysis_map=scene_analysis_map)
    if not prompt:
        return None

    try:
        response = llm.generate(prompt, temperature=0.0)
        response_text = response.text if hasattr(response, "text") else str(response)
    except Exception as exc:
        logger.warning("Prompt QA: LLM call failed — {}", exc)
        return None

    report = _parse_qa_response(response_text, scenes)
    if report is None:
        logger.warning("Prompt QA: could not parse LLM response — pass skipped")
        return None

    # Apply repairs in place
    repairs_applied = 0
    repair_by_index: dict[int, PromptQASceneResult] = {
        r.scene_index: r for r in report.scene_results
    }
    for scene in scenes:
        if scene.get("scene_type", "generated_image") != "generated_image":
            continue
        idx = scene["index"]
        result = repair_by_index.get(idx)
        if result is None:
            continue
        if result.repaired_prompt and result.repaired_prompt != result.original_prompt:
            scene["visual_prompt"] = result.repaired_prompt
            # Also update compiled_prompt inside structured_prompt if present
            sp = scene.get("structured_prompt")
            if isinstance(sp, dict) and sp.get("compiled_prompt"):
                sp["compiled_prompt"] = result.repaired_prompt
            repairs_applied += 1
            logger.info(
                "Prompt QA: scene {} repaired ({} fix(es))",
                idx,
                len(result.fixes),
            )

    report.repairs_applied = repairs_applied

    # Apply deterministic post-QA normalization (no LLM call).
    normalization_applied = 0
    for scene in scenes:
        if scene.get("scene_type", "generated_image") != "generated_image":
            continue
        normalized, changes = normalize_prompt_fields(scene.get("visual_prompt", ""))
        if changes:
            scene["visual_prompt"] = normalized
            sp = scene.get("structured_prompt")
            if isinstance(sp, dict) and sp.get("compiled_prompt"):
                sp["compiled_prompt"] = normalized
            normalization_applied += 1
            logger.info(
                "Prompt QA: scene {} normalized ({} change(s)): {}",
                scene["index"],
                len(changes),
                "; ".join(changes),
            )

    report.normalization_applied = normalization_applied
    if normalization_applied:
        logger.info("Prompt QA: {} prompt(s) normalized in place", normalization_applied)

    logger.info(
        "Prompt QA: {} — {}/{} scenes checked, {} issues found, {} fixed, {} unresolved",
        report.status,
        report.scenes_checked,
        len(gen_scenes),
        report.issues_found,
        report.issues_fixed,
        len(report.unresolved),
    )
    if repairs_applied:
        logger.info("Prompt QA: {} prompt(s) repaired in place", repairs_applied)

    return report
