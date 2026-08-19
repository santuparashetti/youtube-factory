"""ScriptJudge — LLM-based semantic beat evaluation for the 7-Beat pipeline.

Separation of responsibilities:
  LLM:  semantic judgment — does each beat fulfill its narrative function?
  Code: word-count enforcement, schema validation, retry counting, overall_status.

The judge never trusts the LLM's self-reported word count. It computes the
spoken-word count programmatically from the script text before any LLM call,
and embeds that count in the returned result regardless of what the LLM says.

Retry contract:
  - Up to MAX_JUDGE_RETRIES=2 retries on JSON parse or schema validation failure.
  - On permanent failure: returns a JudgeFailure (not fabricated beat results).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

from video_core.providers.llm.base import LLMProvider
from video_core.providers.llm.tasks import LLMTask  # noqa: F401 (re-exported for callers)

# ── Constants ─────────────────────────────────────────────────────────────────

WORD_COUNT_MIN = 600
WORD_COUNT_MAX = 750
PREFERRED_MIN = 680
PREFERRED_MAX = 720
MAX_JUDGE_RETRIES = 2

BEAT_NAMES = ("DISRUPT", "CHALLENGE", "PROVE", "REVEAL", "FRAME", "APPLY", "TRANSFORM")

# Hard structural requirements — must survive every refinement pass.
# Absence of any of these causes overall_status = NEEDS_REFINEMENT regardless
# of beat scores or word count.
REQUIRED_ENGAGEMENT_MARKERS = (
    "journey_invitation",
    "subscribe_promise",
    "branding_end",
)

_SCORE_FAIL_MAX = 4   # 0–4 → FAIL
_SCORE_WEAK_MAX = 7   # 5–7 → WEAK
# 8–10 → PASS


# ── Enums ─────────────────────────────────────────────────────────────────────


class BeatStatus(str, Enum):
    PASS = "pass"
    WEAK = "weak"
    FAIL = "fail"


class WordCountStatus(str, Enum):
    PASS = "pass"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"


class OverallStatus(str, Enum):
    PASS = "pass"
    NEEDS_REFINEMENT = "needs_refinement"


# ── Pydantic models (structured judge output) ─────────────────────────────────


class EvidenceItem(BaseModel):
    quote: str = Field(..., description="Verbatim excerpt from the script")
    reason: str = Field(..., description="Brief explanation ≤20 words")


class BeatEvaluation(BaseModel):
    status: BeatStatus
    score: int = Field(..., ge=0, le=10)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    missing_function: Optional[str] = None
    refinement_instruction: Optional[str] = None

    @field_validator("status", mode="before")
    @classmethod
    def _infer_status(cls, v: object, info: object) -> object:
        return v

    def model_post_init(self, __context: object) -> None:
        # Enforce: status must agree with score range
        score = self.score
        if score <= _SCORE_FAIL_MAX:
            object.__setattr__(self, "status", BeatStatus.FAIL)
        elif score <= _SCORE_WEAK_MAX:
            object.__setattr__(self, "status", BeatStatus.WEAK)
        else:
            object.__setattr__(self, "status", BeatStatus.PASS)


class WordCountResult(BaseModel):
    min: int = WORD_COUNT_MIN
    max: int = WORD_COUNT_MAX
    status: WordCountStatus


class ScriptJudgeResult(BaseModel):
    overall_status: OverallStatus
    spoken_word_count: int
    word_count: WordCountResult
    beats: dict[str, BeatEvaluation]
    engagement_markers: dict[str, bool] = Field(default_factory=dict)

    def engagement_complete(self) -> bool:
        """True only when all three hard-structural engagement markers are present."""
        return all(self.engagement_markers.get(m, False) for m in REQUIRED_ENGAGEMENT_MARKERS)

    def pass_count(self) -> int:
        return sum(1 for b in self.beats.values() if b.status == BeatStatus.PASS)

    def weak_count(self) -> int:
        return sum(1 for b in self.beats.values() if b.status == BeatStatus.WEAK)

    def fail_count(self) -> int:
        return sum(1 for b in self.beats.values() if b.status == BeatStatus.FAIL)

    def beat_score_sum(self) -> int:
        return sum(b.score for b in self.beats.values())

    def refinement_instructions(self) -> dict[str, str]:
        """Return {beat_name: refinement_instruction} for non-PASS beats."""
        return {
            name: (b.refinement_instruction or f"Strengthen the {name} beat.")
            for name, b in self.beats.items()
            if b.status != BeatStatus.PASS and b.refinement_instruction
        }


@dataclass
class JudgeFailure:
    """Returned when all retries are exhausted and no valid result can be produced."""

    reason: str
    attempt_count: int
    raw_responses: list[str] = field(default_factory=list)


# ── Word-count utilities ──────────────────────────────────────────────────────


def _strip_brackets(text: str) -> str:
    return re.sub(r"\[[^\]]*\]", "", text)


def count_spoken_words(script_text: str) -> int:
    """Programmatic spoken-word count. Never trust LLM self-report."""
    return len(_strip_brackets(script_text).split())


def _word_count_status(count: int) -> WordCountStatus:
    if count < WORD_COUNT_MIN:
        return WordCountStatus.TOO_SHORT
    if count > WORD_COUNT_MAX:
        return WordCountStatus.TOO_LONG
    return WordCountStatus.PASS


def check_engagement_markers(script_text: str) -> dict[str, bool]:
    """Programmatic presence check for the three required engagement markers."""
    return {
        name: f"[ENGAGEMENT: {name}]" in script_text
        for name in REQUIRED_ENGAGEMENT_MARKERS
    }


# Private alias used inside this module
_check_engagement_markers = check_engagement_markers


# ── Judge prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a semantic script evaluator for the Atma Theory 7-Beat narrative framework.

SCORING:
  0–4  = FAIL  (narrative function absent or completely ineffective)
  5–7  = WEAK  (narrative function present but underdeveloped or implicit)
  8–10 = PASS  (narrative function clearly and effectively fulfilled)

BEAT DEFINITIONS:

DISRUPT  — Break the viewer's existing assumption about the problem. PASS: a common
  assumption is disrupted and a new framing introduced. WEAK: topic introduced without
  strong assumption challenge. FAIL: describes topic only.

CHALLENGE — Put the viewer into meaningful personal tension, question, or contradiction.
  PASS: viewer confronted with something personally relevant; creates forward pressure.
  WEAK: a problem is described but viewer not personally challenged. FAIL: topic described
  without confronting the viewer. A challenge can be a statement, not only a question.

PROVE — Demonstrate the central claim through concrete evidence, story, or example.
  PASS: at least one concrete mechanism/example with recognizable cause→consequence.
  WEAK: example exists but relationship to thesis unclear or superficial.
  FAIL: claims made without meaningful demonstration. One strong proof is sufficient.

REVEAL — Deliver the central intellectual or emotional realization.
  Generic structure: OLD BELIEF → new reasoning/observation → NEW UNDERSTANDING →
  central insight → solution/principle.
  PASS: clear conceptual shift; viewer can articulate what they understand differently.
  WEAK: solution stated but conceptual shift mostly implicit.
  FAIL: problem directly to advice with no realization.

FRAME — Convert the reveal into a memorable mental model, framework, or set of principles.
  PASS: at least two distinct, distinguishable principles/models explaining HOW to use
  the revealed insight. WEAK: advice exists but not organized into a memorable framework.
  FAIL: no usable framework follows the reveal. Two to four principles acceptable.

APPLY — Give the viewer a concrete, immediately executable action.
  PASS: specific action with enough constraints/detail to execute; connects to framework.
  WEAK: actionable in theory but lacks specificity. FAIL: no concrete action provided.

TRANSFORM — Show the viewer's internal state or perspective transformation.
  Required: BEFORE (what viewer was/believed/did), AFTER (what viewer becomes/does),
  CONSEQUENCE (meaningful emotional or philosophical payoff).
  PASS: before→after relationship clear; meaningful consequence exists. Can be explicit
  or metaphorical as long as both components are clear.
  WEAK: poetic conclusion exists but before→after mostly implied.
  FAIL: script ends without showing what changes in the viewer.

RULES:
- Evaluate narrative FUNCTION, not topic keywords.
- Evidence is REQUIRED for every beat, including PASS.
- missing_function: null for PASS beats; a brief description for WEAK/FAIL.
- refinement_instruction: null for PASS beats; a specific, compression-first instruction
  for WEAK/FAIL. Never instruct the refiner to add paragraphs if the script is near
  the word limit.
- Do not hard-code any specific script's content into your evaluation.

OUTPUT: valid JSON matching this schema exactly, nothing else:
{
  "beats": {
    "DISRUPT":   {"score": 0-10, "evidence": [{"quote": "...", "reason": "..."}], "missing_function": null, "refinement_instruction": null},
    "CHALLENGE": {"score": 0-10, "evidence": [...], "missing_function": null, "refinement_instruction": null},
    "PROVE":     {"score": 0-10, "evidence": [...], "missing_function": null, "refinement_instruction": null},
    "REVEAL":    {"score": 0-10, "evidence": [...], "missing_function": null, "refinement_instruction": null},
    "FRAME":     {"score": 0-10, "evidence": [...], "missing_function": null, "refinement_instruction": null},
    "APPLY":     {"score": 0-10, "evidence": [...], "missing_function": null, "refinement_instruction": null},
    "TRANSFORM": {"score": 0-10, "evidence": [...], "missing_function": null, "refinement_instruction": null}
  }
}
"""


def _build_judge_prompt(script_text: str, spoken_wc: int) -> str:
    return (
        f"Evaluate this script ({spoken_wc} spoken words). "
        "Score all seven beats and return the JSON object described in the system prompt.\n\n"
        f"=== SCRIPT ===\n{script_text}\n\n"
        "Return ONLY the JSON object. No preamble, no explanation."
    )


# ── JSON / schema parsing ─────────────────────────────────────────────────────


def _extract_json(text: str) -> str:
    """Strip markdown fences and extract the first {...} block."""
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text.strip(), flags=re.MULTILINE)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return m.group(0)
    return text.strip()


def _parse_judge_response(
    raw: str, spoken_wc: int, script_text: str
) -> ScriptJudgeResult | None:
    """Parse and validate LLM output. Returns None on any failure."""
    try:
        blob = json.loads(_extract_json(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.debug("ScriptJudge: JSON parse failed — {}", exc)
        return None

    raw_beats = blob.get("beats")
    if not isinstance(raw_beats, dict):
        logger.debug("ScriptJudge: 'beats' key missing or not a dict")
        return None

    beats: dict[str, BeatEvaluation] = {}
    for name in BEAT_NAMES:
        beat_data = raw_beats.get(name)
        if not isinstance(beat_data, dict):
            logger.debug("ScriptJudge: beat {} missing from response", name)
            return None
        # Inject a status derived from score for the validator
        score = beat_data.get("score", 0)
        if score <= _SCORE_FAIL_MAX:
            beat_data["status"] = "fail"
        elif score <= _SCORE_WEAK_MAX:
            beat_data["status"] = "weak"
        else:
            beat_data["status"] = "pass"
        try:
            beats[name] = BeatEvaluation.model_validate(beat_data)
        except ValidationError as exc:
            logger.debug("ScriptJudge: BeatEvaluation validation failed for {} — {}", name, exc)
            return None

    # All three deterministic checks: word count, beats, and engagement markers.
    # The LLM is never trusted for any of these; the judge only asks LLM about
    # narrative semantic quality.
    engagement_markers = _check_engagement_markers(script_text)
    wc_status = _word_count_status(spoken_wc)
    all_pass = all(b.status == BeatStatus.PASS for b in beats.values())
    all_markers = all(engagement_markers.values())
    overall = (
        OverallStatus.PASS
        if (wc_status == WordCountStatus.PASS and all_pass and all_markers)
        else OverallStatus.NEEDS_REFINEMENT
    )

    return ScriptJudgeResult(
        overall_status=overall,
        spoken_word_count=spoken_wc,
        word_count=WordCountResult(status=wc_status),
        beats=beats,
        engagement_markers=engagement_markers,
    )


# ── ScriptJudge ───────────────────────────────────────────────────────────────


class ScriptJudge:
    """Semantic beat evaluator. Uses an LLM for narrative judgment;
    application code handles all deterministic decisions."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def evaluate(
        self,
        script_text: str,
        attempt_label: str = "",
    ) -> ScriptJudgeResult | JudgeFailure:
        """Evaluate a script. Returns ScriptJudgeResult or JudgeFailure.

        Word count is always computed programmatically — the LLM is only
        asked about narrative/semantic function, never word count.
        """
        spoken_wc = count_spoken_words(script_text)
        prompt = _build_judge_prompt(script_text, spoken_wc)
        raw_responses: list[str] = []

        for attempt in range(MAX_JUDGE_RETRIES + 1):
            label = f"{attempt_label} judge-attempt={attempt + 1}" if attempt_label else f"judge-attempt={attempt + 1}"
            logger.info("ScriptJudge: {} spoken_words={}", label, spoken_wc)
            try:
                response = self._llm.generate(
                    prompt,
                    system_prompt=_SYSTEM_PROMPT,
                    temperature=0.1,
                )
                raw = response.text.strip()
            except Exception as exc:
                logger.warning("ScriptJudge: LLM call failed on {} — {}", label, exc)
                raw_responses.append(f"<LLM ERROR: {exc}>")
                continue

            raw_responses.append(raw)
            result = _parse_judge_response(raw, spoken_wc, script_text)
            if result is not None:
                logger.info(
                    "ScriptJudge: {} → overall={} wc={} pass={} weak={} fail={} markers_ok={}",
                    label,
                    result.overall_status.value,
                    spoken_wc,
                    result.pass_count(),
                    result.weak_count(),
                    result.fail_count(),
                    result.engagement_complete(),
                )
                return result

            logger.warning(
                "ScriptJudge: parse/validation failure on {} (attempt {}/{})",
                label,
                attempt + 1,
                MAX_JUDGE_RETRIES + 1,
            )

        logger.error(
            "ScriptJudge: all {} retries exhausted for {} — returning JudgeFailure",
            MAX_JUDGE_RETRIES + 1,
            attempt_label or "evaluation",
        )
        return JudgeFailure(
            reason=f"JSON parse/validation failed after {MAX_JUDGE_RETRIES + 1} attempts",
            attempt_count=MAX_JUDGE_RETRIES + 1,
            raw_responses=raw_responses,
        )
