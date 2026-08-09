"""S2b — Short Script Validator + QA Engine.

Runs deterministic rule-based checks first.
Only calls the LLM for quality scoring when rule checks pass.
Returns a ValidationReport and the (possibly updated) ShortsScript.

Also provides cross-Short similarity detection via evaluate_cross_short().
"""

from __future__ import annotations

import json
import re

from loguru import logger

from video_core.providers.llm.factory import get_llm_for_role
from ytfactory.config.settings import Settings
from ytfactory.shorts.models import (
    CrossShortQAResult,
    ShortsScript,
    ShortsScriptQAReport,
    ValidationReport,
    ValidationScores,
)

_BANNED_PHRASES = [
    "watch the full video",
    "watch our full video",
    "watch the whole video",
    "subscribe",
    "subscribe for more",
    "follow for more",
    "check out our channel",
    "link in bio",
    "visit our channel",
    "hit the like button",
    "like and subscribe",
    "turn on notifications",
]

_SCORING_SYSTEM_PROMPT = """\
You are a quality evaluator for YouTube Shorts scripts.

Score the following script on each dimension from 0.0 to 10.0.

Be honest and critical. Do not be generous.

Dimensions:
- hook_strength: Does the opening sentence immediately create "wait... what?"? \
(10 = will definitely stop a scroll)
- retention_potential: Will someone watch past the first 3 seconds? (10 = almost certainly)
- clarity: Can a stranger understand this on first listen without re-reading? (10 = perfectly clear)
- emotional_intensity: Does it make someone feel something? (10 = strong feeling)
- philosophical_depth: Is there a real idea here, not filler? (10 = genuinely insightful)
- standalone_value: Is this worthwhile even without the long-form video? \
(10 = completely self-contained)
- curiosity_gap: Does it end with an open, unresolved question? \
(10 = the viewer desperately wants more)
- long_form_bridge: Does it naturally create desire for a parent video? (10 = perfect bridge)
- spoiler_risk: How much does it give away the long-form video's answer? \
(0 = gives nothing away, 10 = spoils everything)
- naturalness: Does it sound like a real person speaking? \
(0 = obvious AI writing, 10 = natural human voice)
- specificity: Are the details concrete and specific, not generic? (10 = very specific)
- generic_ai_language: How much AI/content-creator filler language? \
(0 = none, 10 = very heavy)
- advertising_feel: How much does it feel like an ad for the long video? \
(0 = none, 10 = feels entirely like an ad)
- cliche_density: How many worn-out phrases, metaphors, or ideas? (0 = none, 10 = very high)
- narrative_coherence: Does the script flow naturally from hook → setup → story → \
revelation → open_loop? (10 = perfect progression)
- progression: Does each sentence create a reason to continue watching? \
(10 = every sentence pulls forward)
- ending_strength: Does the open_loop genuinely leave the viewer with an unresolved \
question they care about? (10 = powerful and memorable ending)
- overall: A meaningful weighted score considering all dimensions above (not a simple average)

Output strict JSON only. No markdown. No preamble.
Return exactly the keys listed above as a JSON object with float values.
"""

_CROSS_SHORT_SYSTEM_PROMPT = """\
You are a cross-Short similarity detector.

Your task is to determine whether two YouTube Shorts scripts are near-duplicates
that both rely on the same central story, evidence, characters, or narrative sequence.

Two Shorts from the same parent video SHOULD share the same broad theme —
that is not duplication. But if they retell the same concrete narrative,
use the same characters, setting, and evidence, they are near-duplicates
even if their declared "angle" differs.

Shared theme = acceptable.
Shared story mechanism + evidence = near-duplicate.

Evaluate whether:
1. Both Shorts depend on the same concrete narrative event or story
2. Both Shorts use the same protagonist or key characters
3. Both Shorts use the same setting or scene
4. Both Shorts cite the same specific evidence or example
5. Both Shorts follow the same narrative sequence (even if phrased differently)
6. Both Shorts lead to the same revelation or insight
7. One Short is essentially a paraphrase of the other

If similarity_problem is true, identify:
- Which Short (by short_id) should be recomposed (typically the second one)
- Which sections of that Short to preserve (strong independent sections)
- Which sections to rewrite (the ones with duplicate evidence)
- A specific instruction telling the recomposer what to change

Output strict JSON only. No markdown. No preamble.
"""


class ShortScriptValidator:
    def __init__(self, settings: Settings) -> None:
        self._llm = get_llm_for_role(settings, "script")
        self._settings = settings

    def validate(
        self, script: ShortsScript, short_id: str, attempt: int = 1, regenerated: bool = False
    ) -> tuple[ShortsScript, ValidationReport]:
        """Validate a script. Returns (updated_script, report).

        The returned script has validation_passed and scores updated.
        Kept for backwards compatibility — pipeline uses evaluate_with_qa() instead.
        """
        updated, report, _ = self.evaluate_with_qa(
            script, short_id, attempt=attempt, regenerated=regenerated
        )
        return updated, report

    def evaluate_with_qa(
        self,
        script: ShortsScript,
        short_id: str,
        attempt: int = 1,
        regenerated: bool = False,
        cross_short_result: CrossShortQAResult | None = None,
    ) -> tuple[ShortsScript, ValidationReport, ShortsScriptQAReport]:
        """Full QA evaluation returning script, report, and structured QA report.

        Returns (updated_script, validation_report, qa_report).
        The qa_report is used by the recomposer for targeted edits.
        """
        # Step 1: deterministic rule checks (no LLM call on failure)
        rule_checks, rule_failures = self._run_rule_checks(script)

        if rule_failures:
            logger.info(
                "Shorts validator: {} failed rule checks: {}", short_id, rule_failures,
            )
            qa_report = ShortsScriptQAReport(
                short_id=short_id,
                status="FAIL",
                failed_dimensions=rule_failures,
                warning_dimensions=[],
                preserve_sections=["hook"],
                rewrite_sections=_sections_for_rule_failures(rule_failures),
                specific_instruction="; ".join(rule_failures),
                cross_short=cross_short_result,
            )
            report = ValidationReport(
                short_id=short_id,
                validation_passed=False,
                attempts=attempt,
                regenerated=regenerated,
                rule_checks=rule_checks,
                scores=None,
                failure_reasons=rule_failures,
                initial_status="FAIL",
                final_status="FAIL",
            )
            updated = script.model_copy(update={"validation_passed": False, "scores": None})
            return updated, report, qa_report

        # Step 2: LLM quality scoring
        scores = self._score_with_llm(script.full_script)

        # Step 3: determine outcome (PASS / PASS_WITH_WARNING / FAIL)
        hard_failures = self._check_thresholds(scores)
        warnings = self._check_warning_thresholds(scores)
        cross_failures = _cross_short_dimensions(cross_short_result)

        all_failures = hard_failures + cross_failures

        if scores.spoiler_risk > 5.0:
            logger.warning(
                "Shorts validator: {} spoiler_risk={:.1f} (warning threshold: 5.0)",
                short_id, scores.spoiler_risk,
            )

        if all_failures:
            status: str = "FAIL"
        elif warnings:
            status = "PASS_WITH_WARNING"
        else:
            status = "PASS"

        passed = status in ("PASS", "PASS_WITH_WARNING")

        preserve, rewrite = _derive_preserve_rewrite(all_failures, warnings, scores)
        specific_instruction = _build_specific_instruction(
            all_failures, warnings, cross_short_result
        )

        qa_report = ShortsScriptQAReport(
            short_id=short_id,
            status=status,  # type: ignore[arg-type]
            failed_dimensions=all_failures,
            warning_dimensions=warnings,
            preserve_sections=preserve,
            rewrite_sections=rewrite,
            specific_instruction=specific_instruction,
            cross_short=cross_short_result,
        )

        report = ValidationReport(
            short_id=short_id,
            validation_passed=passed,
            attempts=attempt,
            regenerated=regenerated,
            rule_checks=rule_checks,
            scores=scores,
            failure_reasons=all_failures,
            initial_status=status,
            final_status=status,
        )
        updated = script.model_copy(
            update={"validation_passed": passed, "scores": scores}
        )
        return updated, report, qa_report

    def evaluate_cross_short(
        self, script_a: ShortsScript, script_b: ShortsScript
    ) -> CrossShortQAResult:
        """Detect near-duplicate content between two Short scripts.

        Returns a CrossShortQAResult with similarity_problem=True if the two
        Shorts are essentially retellings of the same story/evidence.
        """
        prompt = _build_cross_short_prompt(script_a, script_b)
        response = self._llm.generate(
            prompt,
            system_prompt=_CROSS_SHORT_SYSTEM_PROMPT,
            temperature=0.1,
            json_mode=True,
        )
        text = response.text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        try:
            data = json.loads(text.strip())
        except json.JSONDecodeError:
            logger.warning(
                "Cross-short QA: LLM returned invalid JSON. Assuming no similarity. Preview: {}",
                text[:300],
            )
            return CrossShortQAResult(
                similarity_problem=False,
                overlap_reason="Cross-short QA parse error — assuming acceptable.",
            )

        return CrossShortQAResult(
            similarity_problem=bool(data.get("similarity_problem", False)),
            overlap_reason=data.get("overlap_reason", ""),
            failed_dimensions=data.get("failed_dimensions", []),
            preserve_sections=data.get("preserve_sections", []),
            rewrite_sections=data.get("rewrite_sections", []),
            specific_instruction=data.get("specific_instruction", ""),
        )

    def _run_rule_checks(
        self, script: ShortsScript
    ) -> tuple[dict[str, bool], list[str]]:
        s = self._settings
        failures: list[str] = []

        wc = script.estimated_word_count
        word_count_passed = s.shorts_min_word_count <= wc <= s.shorts_hard_max_word_count
        if not word_count_passed:
            if wc < s.shorts_min_word_count:
                failures.append(
                    f"word_count {wc} is below minimum of {s.shorts_min_word_count}"
                )
            else:
                failures.append(
                    f"word_count {wc} exceeds hard maximum of {s.shorts_hard_max_word_count}"
                )

        duration = (wc / s.shorts_narration_wpm) * 60
        duration_passed = duration <= s.shorts_max_duration_seconds
        if not duration_passed:
            failures.append(
                f"estimated duration {duration:.1f}s exceeds maximum of {s.shorts_max_duration_seconds}s"
            )

        section_failures: list[str] = []
        for section_name in ("hook", "setup", "story", "revelation", "open_loop"):
            if not getattr(script, section_name, "").strip():
                section_failures.append(f"section '{section_name}' is empty")
        sections_passed = len(section_failures) == 0
        failures.extend(section_failures)

        open_loop_lower = script.open_loop.lower()
        full_lower = script.full_script.lower()
        banned_found = [
            phrase
            for phrase in _BANNED_PHRASES
            if phrase in open_loop_lower or phrase in full_lower
        ]
        banned_phrase_passed = len(banned_found) == 0
        if not banned_phrase_passed:
            failures.append(
                f"banned CTA phrase detected: {banned_found[0]!r}"
            )

        rule_checks = {
            "word_count_passed": word_count_passed,
            "duration_passed": duration_passed,
            "sections_complete_passed": sections_passed,
            "banned_phrase_check_passed": banned_phrase_passed,
        }
        return rule_checks, failures

    def _score_with_llm(self, full_script: str) -> ValidationScores:
        prompt = f"Script to evaluate:\n\n{full_script}"
        response = self._llm.generate(
            prompt,
            system_prompt=_SCORING_SYSTEM_PROMPT,
            temperature=0.1,
            json_mode=True,
        )
        text = response.text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        try:
            data = json.loads(text.strip())
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Script validator: LLM returned invalid JSON scores. Preview: {text[:300]}"
            ) from exc
        return ValidationScores.model_validate(data)

    def _check_thresholds(self, scores: ValidationScores) -> list[str]:
        """Return hard failure dimension names."""
        s = self._settings
        failures: list[str] = []
        if scores.hook_strength < s.shorts_validation_hook_threshold:
            failures.append("hook_strength")
        if scores.standalone_value < s.shorts_validation_standalone_threshold:
            failures.append("standalone_value")
        if scores.overall < s.shorts_validation_overall_threshold:
            failures.append("overall")
        if scores.spoiler_risk > s.shorts_validation_spoiler_max:
            failures.append("spoiler_risk")
        if scores.generic_ai_language > s.shorts_validation_generic_ai_max:
            failures.append("generic_ai_language")
        if scores.advertising_feel > s.shorts_validation_advertising_max:
            failures.append("advertising_feel")
        if scores.cliche_density > s.shorts_validation_cliche_max:
            failures.append("cliche_density")
        if scores.naturalness < s.shorts_validation_naturalness_min:
            failures.append("naturalness")
        return failures

    def _check_warning_thresholds(self, scores: ValidationScores) -> list[str]:
        """Return dimension names that are weak but not yet failing.

        Warning = within 1.5 points of the hard threshold.
        These trigger PASS_WITH_WARNING but not recomposition.
        """
        s = self._settings
        warnings: list[str] = []

        def _near_fail(value: float, threshold: float, margin: float = 1.5) -> bool:
            return threshold <= value < threshold + margin

        def _near_fail_max(value: float, threshold: float, margin: float = 1.5) -> bool:
            return threshold - margin < value <= threshold

        if _near_fail(scores.hook_strength, s.shorts_validation_hook_threshold):
            warnings.append("hook_strength")
        if _near_fail(scores.standalone_value, s.shorts_validation_standalone_threshold):
            warnings.append("standalone_value")
        if _near_fail(scores.overall, s.shorts_validation_overall_threshold):
            warnings.append("overall")
        if _near_fail_max(scores.naturalness, s.shorts_validation_naturalness_min):
            warnings.append("naturalness")
        if scores.philosophical_depth < 5.0:
            warnings.append("philosophical_depth")
        if scores.curiosity_gap < 5.0:
            warnings.append("curiosity_gap")
        return warnings


# ── Helpers ────────────────────────────────────────────────────────────────────

def _cross_short_dimensions(result: CrossShortQAResult | None) -> list[str]:
    if result is None or not result.similarity_problem:
        return []
    dims = ["cross_short_similarity"]
    dims.extend(result.failed_dimensions)
    return dims


def _sections_for_rule_failures(rule_failures: list[str]) -> list[str]:
    """Map rule failure messages to the sections most likely responsible."""
    rewrite: set[str] = set()
    for f in rule_failures:
        if "word_count" in f or "duration" in f:
            rewrite.add("story")
            rewrite.add("setup")
        if "banned" in f or "phrase" in f:
            rewrite.add("open_loop")
        if "section" in f and "empty" in f:
            # Extract section name from message
            for s in ("hook", "setup", "story", "revelation", "open_loop"):
                if s in f:
                    rewrite.add(s)
    return list(rewrite) if rewrite else ["story", "open_loop"]


def _derive_preserve_rewrite(
    failures: list[str],
    warnings: list[str],
    scores: ValidationScores,
) -> tuple[list[str], list[str]]:
    """Determine which sections to preserve and which to rewrite based on QA results."""
    all_problem_dims = set(failures)

    # Map failing dimensions to the sections responsible
    dim_to_section: dict[str, list[str]] = {
        "hook_strength": ["hook"],
        "naturalness": ["hook", "setup", "story", "revelation", "open_loop"],
        "generic_ai_language": ["hook", "setup", "story", "revelation", "open_loop"],
        "advertising_feel": ["open_loop"],
        "cliche_density": ["story", "revelation"],
        "standalone_value": ["setup", "story"],
        "overall": ["story", "revelation"],
        "spoiler_risk": ["revelation", "open_loop"],
        "cross_short_similarity": ["story"],
        "curiosity_gap": ["open_loop"],
        "retention_potential": ["setup", "story"],
    }

    rewrite_sections: set[str] = set()
    for dim in all_problem_dims:
        for section in dim_to_section.get(dim, []):
            rewrite_sections.add(section)

    # Sections that scored well are candidates for preservation
    strong_sections: set[str] = set()
    if scores.hook_strength >= 7.0 and "hook" not in rewrite_sections:
        strong_sections.add("hook")
    if scores.standalone_value >= 7.0 and "setup" not in rewrite_sections:
        strong_sections.add("setup")
    if scores.philosophical_depth >= 7.0 and "revelation" not in rewrite_sections:
        strong_sections.add("revelation")

    # Everything not being rewritten and that scored well is preserved
    all_sections = {"hook", "setup", "story", "revelation", "open_loop"}
    preserve_sections = list(all_sections - rewrite_sections)

    return sorted(preserve_sections), sorted(rewrite_sections)


def _build_specific_instruction(
    failures: list[str],
    warnings: list[str],
    cross_short_result: CrossShortQAResult | None,
) -> str:
    parts: list[str] = []
    if cross_short_result and cross_short_result.similarity_problem:
        parts.append(cross_short_result.specific_instruction or
                     "Avoid retelling the same story used by the sibling Short.")
    if "hook_strength" in failures:
        parts.append("Rewrite the hook to create immediate 'wait... what?' tension.")
    if "spoiler_risk" in failures:
        parts.append("Remove content that reveals the long-form video's complete answer.")
    if "advertising_feel" in failures:
        parts.append("Remove any promotional or CTA language from the open_loop.")
    if "generic_ai_language" in failures:
        parts.append("Replace generic AI language with specific, natural human expression.")
    if "cliche_density" in failures:
        parts.append("Replace worn-out phrases and clichés with concrete, specific language.")
    return " ".join(parts)


def _build_cross_short_prompt(script_a: ShortsScript, script_b: ShortsScript) -> str:
    return f"""\
Compare these two YouTube Shorts scripts from the same parent video.

SHORT A ({script_a.short_id}):
{script_a.full_script}

SHORT B ({script_b.short_id}):
{script_b.full_script}

---

Evaluate whether these two Shorts are near-duplicates that both rely on the same
central story, evidence, characters, setting, or narrative sequence.

Remember: sharing the same broad THEME is acceptable.
Near-duplication = same MECHANISM + same EVIDENCE + same STORY used in both.

Return JSON:
{{
  "similarity_problem": true or false,
  "overlap_reason": "Clear explanation of what specifically overlaps, or 'none' if no problem",
  "failed_dimensions": ["list", "of", "specific", "overlapping", "elements"],
  "recompose_short_id": "{script_b.short_id}",
  "preserve_sections": ["sections", "to", "keep", "unchanged"],
  "rewrite_sections": ["sections", "that", "need", "new", "evidence"],
  "specific_instruction": "Exact actionable instruction for the recomposer"
}}
"""
