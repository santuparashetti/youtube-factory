"""RefinementLoop — programmatically-driven script refinement with hard constraints.

Separation of responsibilities:
  Application code: word-count enforcement, iteration cap, candidate tracking,
    rejection logic, retry-feedback escalation, best-candidate selection.
  LLM (via AtmaRefinerPipeline): semantic rewriting and compression.
  LLM (via ScriptJudge): narrative beat quality evaluation.

Hard constraints:
  MAX_REFINEMENT_ITERATIONS = 3
  WORD_COUNT_MAX = 750  (any candidate > 750 is rejected immediately)
  If input > 750, any candidate >= input word count is also rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from loguru import logger

from ytfactory.atma_refiner.judge import (
    BeatStatus,
    check_engagement_markers,
    JudgeFailure,
    OverallStatus,
    PREFERRED_MAX,
    PREFERRED_MIN,
    REQUIRED_ENGAGEMENT_MARKERS,
    ScriptJudge,
    ScriptJudgeResult,
    WORD_COUNT_MAX,
    WORD_COUNT_MIN,
    count_spoken_words,
)
from ytfactory.domain.script_revision import ScriptIdentity

MAX_REFINEMENT_ITERATIONS = 3


# ── Candidate scoring ─────────────────────────────────────────────────────────


@dataclass
class Candidate:
    """One refinement attempt that passed the word-count gate."""

    script: str
    spoken_wc: int
    judge_result: ScriptJudgeResult
    attempt: int

    # Computed fields
    pass_count: int = field(init=False)
    weak_count: int = field(init=False)
    fail_count: int = field(init=False)
    beat_score: int = field(init=False)
    wc_compliant: bool = field(init=False)
    markers_complete: bool = field(init=False)

    def __post_init__(self) -> None:
        self.pass_count = self.judge_result.pass_count()
        self.weak_count = self.judge_result.weak_count()
        self.fail_count = self.judge_result.fail_count()
        self.beat_score = self.judge_result.beat_score_sum()
        self.wc_compliant = WORD_COUNT_MIN <= self.spoken_wc <= WORD_COUNT_MAX
        self.markers_complete = self.judge_result.engagement_complete()


def _is_better(challenger: Candidate, champion: Candidate) -> bool:
    """Return True if challenger is strictly better than champion.

    Priority order (highest to lowest):
    1. Hard word-count compliance (600–750)
    2. All required engagement markers present
    3. Fewer FAIL beats
    4. More PASS beats
    5. Fewer WEAK beats
    6. Higher beat score sum
    7. Shorter (tiebreaker — prefer shorter compliant candidate)
    """
    # Compliance wins unconditionally
    if challenger.wc_compliant and not champion.wc_compliant:
        return True
    if champion.wc_compliant and not challenger.wc_compliant:
        return False

    # Required engagement markers are the second priority
    if challenger.markers_complete and not champion.markers_complete:
        return True
    if champion.markers_complete and not challenger.markers_complete:
        return False

    # Both same marker status — compare beat quality
    if challenger.fail_count < champion.fail_count:
        return True
    if challenger.fail_count > champion.fail_count:
        return False

    if challenger.pass_count > champion.pass_count:
        return True
    if challenger.pass_count < champion.pass_count:
        return False

    if challenger.weak_count < champion.weak_count:
        return True
    if challenger.weak_count > champion.weak_count:
        return False

    if challenger.beat_score > champion.beat_score:
        return True
    if challenger.beat_score < champion.beat_score:
        return False

    # Tiebreaker: shorter is better
    return challenger.spoken_wc < champion.spoken_wc


# ── Refinement feedback builder ───────────────────────────────────────────────


# Estimated words added per missing engagement element (midpoint of 15–30 preferred range).
_EST_WORDS_PER_MISSING_MARKER = 22


def _build_refinement_feedback(
    judge_result: ScriptJudgeResult,
    current_script: str,
    current_wc: int,
    input_wc: int,
    attempt: int,
    concepts_to_preserve: list[str],
) -> str:
    """Build a targeted refinement instruction for the next LLM call.

    Markers are checked directly from current_script (not from judge_result) so
    that word-count-rejected candidates — which may have had markers inserted but
    whose judge_result carries stale marker data — are handled correctly.

    Priority order follows the design contract:
    1. Required engagement marker insertion (when missing)
    2. Word-count reduction (mandatory if over limit)
    3. Fix FAIL beats (compression/replacement first)
    4. Fix WEAK beats (compression/replacement first)
    5. Preserve PASS beats, present markers, and required concepts
    """
    lines: list[str] = []

    # ── Engagement markers — check current_script directly ───────────────────
    marker_presence = check_engagement_markers(current_script)
    missing_markers = [m for m, present in marker_presence.items() if not present]
    present_markers = [m for m, present in marker_presence.items() if present]

    # ── Compression-first pass (attempt 1, script over limit) ────────────────
    # Asking the model to simultaneously insert markers AND cut 200+ words in one
    # pass consistently fails — it adds markers but ignores the compression
    # instruction. Split the work: compress first, then add markers + fix beats.
    if attempt == 1 and current_wc > WORD_COUNT_MAX:
        engagement_words_to_add = len(missing_markers) * _EST_WORDS_PER_MISSING_MARKER
        # Target below WORD_COUNT_MAX to leave headroom for marker insertion next pass.
        compression_target = max(PREFERRED_MIN, WORD_COUNT_MAX - engagement_words_to_add)
        words_to_cut = current_wc - compression_target
        return (
            f"HARD WORD LIMIT VIOLATED: {current_wc} spoken words (hard max: {WORD_COUNT_MAX}).\n"
            f"THIS PASS: COMPRESSION ONLY. Do NOT add engagement markers. Do NOT fix beats.\n"
            f"TARGET: {compression_target} spoken words "
            f"(leaves headroom for {len(missing_markers)} marker(s) in the next pass).\n"
            f"Cut {words_to_cut} words by removing: repeated phrases, redundant transitions, "
            f"verbose filler, over-explained metaphors. Remove whole sentences where needed.\n"
            f"Do NOT rewrite narrative beats. Do NOT add any new content.\n"
            f"Return the script word-for-word except for what you remove.\n"
            f"Your output MUST be strictly shorter than {current_wc} words. "
            f"Equal is rejected. Longer is rejected."
        )

    if missing_markers:
        marker_list = ", ".join(f"[ENGAGEMENT: {m}]" for m in missing_markers)
        lines.append(
            f"CRITICAL — MISSING REQUIRED MARKERS: {marker_list}. "
            "INSERT each at its correct position (see system prompt for placement rules). "
            "Use 15–30 spoken words per element. "
            "These are pipeline structure — they CANNOT be omitted."
        )

    if present_markers:
        marker_list = ", ".join(f"[ENGAGEMENT: {m}]" for m in present_markers)
        lines.append(
            f"PRESERVE: {marker_list} are already in the script — do NOT remove them. "
            "To reduce word count, compress narrative beats, not engagement elements."
        )

    all_beats_pass = judge_result.fail_count() == 0 and judge_result.weak_count() == 0

    # ── All beats pass: format-only path ─────────────────────────────────────
    # Script is well-written. The only issues are missing markers and/or word count.
    # Do NOT rewrite beat content — only insert markers and trim clear redundancy.
    if all_beats_pass:
        if current_wc > WORD_COUNT_MAX:
            engagement_words_to_add = len(missing_markers) * _EST_WORDS_PER_MISSING_MARKER
            total_cut = (current_wc - WORD_COUNT_MAX) + engagement_words_to_add
            task1 = (
                "  1. INSERT the missing engagement markers listed above at their correct positions "
                f"(adds ~{engagement_words_to_add} words — you must cut that much MORE from narrative).\n"
                if missing_markers
                else "  1. Keep the engagement markers already present exactly where they are.\n"
            )
            lines.append(
                f"ALL NARRATIVE BEATS ARE CORRECT — do NOT rewrite beat content.\n"
                f"HARD WORD LIMIT VIOLATED: {current_wc} words → must reach ≤{WORD_COUNT_MAX}.\n"
                f"Your output MUST be strictly shorter than {current_wc} words. "
                f"Equal is rejected. Longer is rejected.\n"
                f"NEVER ACCEPTABLE: {current_wc} → {current_wc} | "
                f"{current_wc} → {current_wc + 10} | "
                f"{current_wc} → {WORD_COUNT_MAX + 10}\n"
                f"ONLY ACCEPTABLE: output ≤{WORD_COUNT_MAX} words "
                f"(preferred {PREFERRED_MIN}–{PREFERRED_MAX}).\n"
                f"Your ONLY tasks:\n"
                f"{task1}"
                f"  2. Cut exactly {total_cut} words from: repeated phrases, redundant transitions, "
                f"verbose filler, over-explained metaphors. Remove whole sentences if needed.\n"
                f"  3. Do NOT add any other content. "
                f"Return every story, example, and philosophical moment intact."
            )
        elif missing_markers:
            lines.append(
                f"ALL NARRATIVE BEATS ARE CORRECT — do NOT rewrite any content.\n"
                f"Your ONLY task: INSERT the missing engagement markers listed above "
                f"at their correct positions. Return the rest of the script word-for-word."
            )
        # (If all beats pass, no markers missing, wc in range → overall_status = PASS;
        #  this branch is unreachable in normal flow.)
        return "\n".join(lines)

    # ── Beat diagnostics (only reached when beats need work) ─────────────────
    fail_beats = [
        (name, b)
        for name, b in judge_result.beats.items()
        if b.status == BeatStatus.FAIL
    ]
    weak_beats = [
        (name, b)
        for name, b in judge_result.beats.items()
        if b.status == BeatStatus.WEAK
    ]
    pass_beats = [
        name for name, b in judge_result.beats.items() if b.status == BeatStatus.PASS
    ]

    # ── Word count (when beats also need fixing) ──────────────────────────────
    if current_wc > WORD_COUNT_MAX:
        engagement_words_to_add = len(missing_markers) * _EST_WORDS_PER_MISSING_MARKER
        total_cut_needed = (current_wc - WORD_COUNT_MAX) + engagement_words_to_add
        lines.append(
            f"HARD WORD LIMIT VIOLATED: {current_wc} spoken words (hard max: {WORD_COUNT_MAX}).\n"
            f"Your output MUST be strictly shorter than {current_wc} words. "
            f"Equal is rejected. Longer is rejected.\n"
            f"NEVER ACCEPTABLE: {current_wc} → {current_wc} | "
            f"{current_wc} → {current_wc + 10} | "
            f"{current_wc} → {WORD_COUNT_MAX + 10}\n"
            f"ONLY ACCEPTABLE: output < {WORD_COUNT_MAX} words "
            f"(preferred {PREFERRED_MIN}–{PREFERRED_MAX}).\n"
            f"Required: cut ≥{total_cut_needed} words of narrative "
            f"(includes ~{engagement_words_to_add} reserved for missing markers if any).\n"
            "Fix beats WITHIN the word budget — compress the weak section, do NOT expand it. "
            "Every word you add to fix a beat requires removing a word elsewhere."
        )
    elif current_wc < WORD_COUNT_MIN:
        deficit = WORD_COUNT_MIN - current_wc
        lines.append(
            f"Script is {deficit} words short of the 600-word minimum "
            f"(current: {current_wc}). Add only what serves a weak or missing beat."
        )

    if pass_beats:
        lines.append(f"PRESERVE (do not alter): {', '.join(pass_beats)} beats.")

    for name, beat in fail_beats:
        instr = beat.refinement_instruction or f"Rewrite {name} to fulfill its narrative function."
        missing = beat.missing_function or ""
        lines.append(
            f"FAIL — {name}: Replace or compress existing content. "
            f"DO NOT add new paragraphs. Every word you add requires removing a word elsewhere.\n"
            f"  Missing: {missing}\n"
            f"  Instruction: {instr}"
        )

    for name, beat in weak_beats:
        instr = beat.refinement_instruction or f"Strengthen {name}."
        missing = beat.missing_function or ""
        if name == "REVEAL":
            lines.append(
                f"WEAK — REVEAL: DO NOT add new paragraphs. DO NOT increase script length.\n"
                f"SURGICAL REWRITE ONLY: Replace or compress existing REVEAL sentences "
                f"so they explicitly communicate this structure:\n"
                f"  1. OLD ASSUMPTION — what the viewer believed before\n"
                f"  2. NEW UNDERSTANDING — the reframe that contradicts it\n"
                f"  3. CORE INSIGHT — the key truth this reveal unlocks\n"
                f"  4. SOLUTION — what the viewer should now do or see\n"
                f"If you add any words here, cut the same number elsewhere. Net zero or net negative.\n"
                f"  Judge note: {missing} {instr}"
            )
        elif name == "TRANSFORM":
            lines.append(
                f"WEAK — TRANSFORM: DO NOT add new paragraphs. DO NOT increase script length.\n"
                f"SURGICAL REWRITE ONLY: Replace or compress existing TRANSFORM sentences "
                f"so they explicitly communicate this structure:\n"
                f"  1. BEFORE STATE — who the viewer was (restless, searching, switching)\n"
                f"  2. AFTER STATE — who they become (steadier, able to stay)\n"
                f"  3. CONSEQUENCE / EMOTIONAL PAYOFF — what is now different\n"
                f"If you add any words here, cut the same number elsewhere. Net zero or net negative.\n"
                f"  Judge note: {missing} {instr}"
            )
        else:
            lines.append(
                f"WEAK — {name}: DO NOT add new paragraphs. DO NOT increase script length.\n"
                f"Rewrite existing {name} sentences to make the narrative function explicit. "
                f"If you add any words here, cut the same number elsewhere.\n"
                f"  Judge note: {missing} {instr}"
            )

    # ── Preservation ─────────────────────────────────────────────────────────
    if concepts_to_preserve:
        lines.append(
            "PRESERVE these concepts (not necessarily verbatim): "
            + "; ".join(concepts_to_preserve[:10])
        )

    allowed_new = (
        "The only new content allowed is the missing engagement markers listed above."
        if missing_markers
        else "Do NOT add new CTAs, metaphors, statistics, or unrelated ideas."
    )
    lines.append(
        f"{allowed_new} "
        f"Hard limit: ≤{WORD_COUNT_MAX} spoken words (preferred {PREFERRED_MIN}–{PREFERRED_MAX})."
    )

    return "\n".join(lines)


# ── RefinementResult ──────────────────────────────────────────────────────────


@dataclass
class RefinementResult:
    """Output of a RefinementLoop.run() call."""

    script: str
    spoken_wc: int
    judge_result: Optional[ScriptJudgeResult]
    iterations_used: int
    accepted_attempt: int  # 0 = original input accepted (already passing)
    overall_status: str  # "pass" | "needs_refinement" | "judge_failure" | "no_valid_candidate"
    attempt_wcs: list[int] = None  # type: ignore[assignment]  # per-attempt spoken WC

    def __post_init__(self) -> None:
        if self.attempt_wcs is None:
            self.attempt_wcs = []

    def to_dict(self) -> dict:
        return {
            "spoken_wc": self.spoken_wc,
            "iterations_used": self.iterations_used,
            "accepted_attempt": self.accepted_attempt,
            "overall_status": self.overall_status,
            "attempt_wcs": self.attempt_wcs,
            "beat_pass_count": self.judge_result.pass_count() if self.judge_result else None,
            "beat_weak_count": self.judge_result.weak_count() if self.judge_result else None,
            "beat_fail_count": self.judge_result.fail_count() if self.judge_result else None,
        }


# ── RefinementLoop ────────────────────────────────────────────────────────────


class RefinementLoop:
    """Application-code-driven refinement loop.

    The loop owns:
    - Iteration cap enforcement (MAX_REFINEMENT_ITERATIONS = 3)
    - Word-count rejection (> 750 is always rejected)
    - Best-candidate tracking (a later worse candidate never replaces a better one)
    - Retry feedback escalation (quantified reduction targets)
    - Controlled fallback when no valid candidate is found

    The LLM owns:
    - Semantic rewriting, compression, beat strengthening (via refiner_fn)
    - Narrative beat quality evaluation (via ScriptJudge)
    """

    def __init__(
        self,
        judge: ScriptJudge,
        refiner_fn: "Callable[[str, str], str]",
    ) -> None:
        """
        Args:
            judge: ScriptJudge instance.
            refiner_fn: Callable(current_script, feedback) -> refined_script.
                The loop passes targeted feedback on each iteration. The callable
                is responsible for its own LLM call (via AtmaRefinerPipeline or
                equivalent).
        """
        self._judge = judge
        self._refiner_fn = refiner_fn

    def run(
        self,
        script: str,
        identity: ScriptIdentity,
        concepts_to_preserve: list[str] | None = None,
    ) -> RefinementResult:
        """Run the refinement loop.

        1. Judge the input script first.
        2. If already passing, return immediately.
        3. Otherwise run up to MAX_REFINEMENT_ITERATIONS refinement attempts.
        4. Return the best valid candidate found.
        """
        _concepts = concepts_to_preserve or []
        input_wc = count_spoken_words(script)

        # ── Judge the input ───────────────────────────────────────────────────
        logger.info("RefinementLoop: evaluating input script ({} spoken words)", input_wc)
        initial_judge = self._judge.evaluate(script, attempt_label="input")

        if isinstance(initial_judge, JudgeFailure):
            logger.error(
                "RefinementLoop: initial judge failed — {}; returning input unchanged",
                initial_judge.reason,
            )
            return RefinementResult(
                script=script,
                spoken_wc=input_wc,
                judge_result=None,
                iterations_used=0,
                accepted_attempt=0,
                overall_status="judge_failure",
                attempt_wcs=[],
            )

        if initial_judge.overall_status == OverallStatus.PASS:
            logger.info("RefinementLoop: input already passes — no refinement needed")
            return RefinementResult(
                script=script,
                spoken_wc=input_wc,
                judge_result=initial_judge,
                iterations_used=0,
                accepted_attempt=0,
                overall_status="pass",
                attempt_wcs=[],
            )

        # ── Refinement loop ───────────────────────────────────────────────────
        best: Optional[Candidate] = None
        # Track the wc-rejected candidate with the lowest word count as a fallback.
        # This ensures that if all attempts exceed 750 words we still return the
        # closest-to-compliant attempt (with markers inserted) rather than the
        # original unchanged input.
        best_wc_rejected: Optional[tuple[str, int]] = None
        _attempt_wcs: list[int] = []
        current_script = script
        current_wc = input_wc
        current_judge = initial_judge

        for iteration in range(1, MAX_REFINEMENT_ITERATIONS + 1):
            feedback = _build_refinement_feedback(
                current_judge,
                current_script=current_script,
                current_wc=current_wc,
                input_wc=input_wc,
                attempt=iteration,
                concepts_to_preserve=_concepts,
            )

            logger.info(
                "RefinementLoop: refinement-attempt={} (current_wc={}, input_wc={})",
                iteration,
                current_wc,
                input_wc,
            )

            try:
                refined = self._refiner_fn(current_script, feedback)
            except Exception as exc:
                logger.error("RefinementLoop: refiner_fn failed on attempt {} — {}", iteration, exc)
                break

            candidate_wc = count_spoken_words(refined)
            _attempt_wcs.append(candidate_wc)
            logger.info(
                "RefinementLoop: attempt={} candidate_wc={}",
                iteration,
                candidate_wc,
            )

            # ── Hard word-count gate ──────────────────────────────────────────
            reject_reason: Optional[str] = None
            if candidate_wc > WORD_COUNT_MAX:
                reject_reason = f"candidate_wc={candidate_wc} exceeds hard max={WORD_COUNT_MAX}"
            elif input_wc > WORD_COUNT_MAX and candidate_wc >= input_wc:
                reject_reason = (
                    f"input was over-limit ({input_wc}w) and candidate ({candidate_wc}w) "
                    "is not shorter — rejected"
                )

            if reject_reason:
                logger.warning(
                    "RefinementLoop: attempt={} REJECTED — {}",
                    iteration,
                    reject_reason,
                )
                # Keep the closest-to-compliant rejected candidate so we have something
                # better than the original input to fall back to.
                if best_wc_rejected is None or candidate_wc < best_wc_rejected[1]:
                    best_wc_rejected = (refined, candidate_wc)
                # Escalate feedback for the next iteration using the *candidate* as base
                current_script = refined
                current_wc = candidate_wc
                # Build a fresh "word count only" judge result to drive escalated feedback
                # We don't call the real judge on a rejected candidate — just set a synthetic one
                current_judge = _synthetic_wc_judge(current_judge, candidate_wc)
                continue

            # ── Evaluate accepted candidate ───────────────────────────────────
            judge_result = self._judge.evaluate(
                refined, attempt_label=f"refinement-attempt={iteration}"
            )
            if isinstance(judge_result, JudgeFailure):
                logger.warning(
                    "RefinementLoop: judge failed on attempt={} — skipping candidate",
                    iteration,
                )
                # Use this script as the base for next iteration but don't accept it as best
                current_script = refined
                current_wc = candidate_wc
                continue

            candidate = Candidate(
                script=refined,
                spoken_wc=candidate_wc,
                judge_result=judge_result,
                attempt=iteration,
            )

            logger.info(
                "RefinementLoop: attempt={} wc={} pass={} weak={} fail={} score={}",
                iteration,
                candidate_wc,
                candidate.pass_count,
                candidate.weak_count,
                candidate.fail_count,
                candidate.beat_score,
            )

            if best is None or _is_better(candidate, best):
                logger.info(
                    "RefinementLoop: attempt={} is new best candidate (replaced attempt={})",
                    iteration,
                    best.attempt if best else "none",
                )
                best = candidate

            if judge_result.overall_status == OverallStatus.PASS:
                logger.info("RefinementLoop: attempt={} is PASS — stopping early", iteration)
                break

            # Prepare next iteration from the current candidate
            current_script = refined
            current_wc = candidate_wc
            current_judge = judge_result

        # ── Select result ─────────────────────────────────────────────────────
        if best is not None:
            overall = best.judge_result.overall_status.value
            logger.info(
                "RefinementLoop: final — accepted attempt={} wc={} status={}",
                best.attempt,
                best.spoken_wc,
                overall,
            )
            return RefinementResult(
                script=best.script,
                spoken_wc=best.spoken_wc,
                judge_result=best.judge_result,
                iterations_used=MAX_REFINEMENT_ITERATIONS,
                accepted_attempt=best.attempt,
                overall_status=overall,
                attempt_wcs=_attempt_wcs,
            )

        # No accepted candidate — use the best wc-rejected attempt if one exists.
        # A wc-rejected attempt with markers (e.g. 952 words) is better than the original
        # input without markers (889 words) even when the rejected attempt is longer, because
        # it satisfies the marker requirement and leaves only the WC flag to fix.
        if best_wc_rejected is not None:
            bwc_script, bwc_wc = best_wc_rejected
            logger.warning(
                "RefinementLoop: no valid candidate; using best wc-rejected attempt "
                "(wc={}) over original input (wc={}) — markers present but WC too high",
                bwc_wc,
                input_wc,
            )
            return RefinementResult(
                script=bwc_script,
                spoken_wc=bwc_wc,
                judge_result=None,
                iterations_used=MAX_REFINEMENT_ITERATIONS,
                accepted_attempt=0,
                overall_status="no_valid_candidate",
                attempt_wcs=_attempt_wcs,
            )

        # Absolute fallback — return the original script unchanged
        logger.error(
            "RefinementLoop: no valid candidate produced after {} iterations — "
            "returning original input",
            MAX_REFINEMENT_ITERATIONS,
        )
        return RefinementResult(
            script=script,
            spoken_wc=input_wc,
            judge_result=initial_judge,
            iterations_used=MAX_REFINEMENT_ITERATIONS,
            accepted_attempt=0,
            overall_status="no_valid_candidate",
            attempt_wcs=_attempt_wcs,
        )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _synthetic_wc_judge(
    prior_judge: ScriptJudgeResult, new_wc: int
) -> ScriptJudgeResult:
    """Return a copy of prior_judge with updated word count (for feedback escalation).

    Used when a candidate is rejected on word count alone, so we can build
    meaningful escalated feedback for the next iteration without an LLM call.
    """
    from ytfactory.atma_refiner.judge import WordCountResult, WordCountStatus, OverallStatus

    wc_status = (
        WordCountStatus.TOO_LONG if new_wc > WORD_COUNT_MAX
        else (WordCountStatus.TOO_SHORT if new_wc < WORD_COUNT_MIN else WordCountStatus.PASS)
    )
    return ScriptJudgeResult(
        overall_status=OverallStatus.NEEDS_REFINEMENT,
        spoken_word_count=new_wc,
        word_count=WordCountResult(status=wc_status),
        beats=prior_judge.beats,  # Carry forward beat scores for compression-first feedback
        engagement_markers=prior_judge.engagement_markers,  # Carry forward marker status
    )
