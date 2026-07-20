"""DocumentaryScriptEnhancerPipeline — transform a normalized transcript into a
cinematic documentary narration. Formerly ScriptEnhancerPipeline (renamed per ADR-0010).

Two-pass structure per ADR-0011:
  Pass 1 (temp=0.4): Faithful Enhancement — fidelity gate before any retention work.
  Pass 2 (temp=0.7): Viewer Retention Optimization — cinematic storytelling, Narrative Score loop.

Scripture protection is a hard constraint across both passes.
ScriptEnhancerPipeline is preserved as a backward-compatible alias.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.prompts.branding import (
    get_closing,
    get_closing_brand,
    get_cta,
    get_transition,
    get_welcome,
)
from ytfactory.agents.prompts.script_enhancer import build_pass1_prompt, build_pass2_prompt
from ytfactory.agents.prompts.script_writer import (
    DURATION_TOLERANCE_MINUTES,
    NARRATION_WPM,
    TARGET_IDEAL_MINUTES,
)
from ytfactory.config.settings import Settings
from ytfactory.shared import religion_agnostic
from ytfactory.shared.scripture import (
    check_scripture_verbatim,
    extract_scripture_spans,
    restore_scripture_spans,
)
from ytfactory.shared.script_utils import strip_script_heading
from video_core.providers.llm.factory import get_llm_provider
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shared.pipeline_status import PipelineAbort, get_writer

console = Console()

# Pass 2 Narrative Score parsing
_SCORE_BLOCK_RE = re.compile(
    r"\s*---NARRATIVE SCORE---\n(.*?)\n---END SCORE---\s*$",
    re.DOTALL,
)
_OVERALL_RE = re.compile(r"Overall:\s*(\d+(?:\.\d+)?)/10", re.IGNORECASE)

_MAX_PASS2_ITERATIONS = 2
_NARRATIVE_SCORE_THRESHOLD = 8.5
_COVERAGE_THRESHOLD = 0.80  # Pass 1 and final: output must be ≥ 80% word count of input


def _duration_ok(estimated_minutes: float, target_minutes: int) -> bool:
    return abs(estimated_minutes - target_minutes) <= DURATION_TOLERANCE_MINUTES


def _parse_narrative_score(text: str) -> tuple[str, float | None]:
    """Split the LLM output into (script_text, overall_score).

    The LLM appends a score block at the end of Pass 2 output:
      ---NARRATIVE SCORE---
      Overall: X/10
      ---END SCORE---
    Returns (text_without_block, score) or (text, None) if no block found.
    """
    m = _SCORE_BLOCK_RE.search(text)
    if not m:
        return text, None
    block = m.group(1)
    script = text[: m.start()].rstrip()
    overall_m = _OVERALL_RE.search(block)
    score = float(overall_m.group(1)) if overall_m else None
    return script, score


class DocumentaryEnhancerValidator:
    """Objective validation checks for ADR-0011."""

    def validate_pass1(
        self,
        original_ph_text: str,
        pass1_ph_text: str,
        mode: str = "expand",
    ) -> tuple[bool, list[str]]:
        """Check Pass 1 output for scripture placeholder preservation and coverage.

        In 'shorten' mode the coverage minimum is skipped — fewer words is the goal.
        Returns (ok, errors).
        """
        errors: list[str] = []

        # Scripture placeholder preservation
        for key in re.findall(r"\{\{(SCRIPTURE_\d+)\}\}", original_ph_text):
            if f"{{{{{key}}}}}" not in pass1_ph_text:
                errors.append(f"Pass 1 dropped scripture placeholder: {{{{{key}}}}}")

        # Coverage check — only meaningful when expanding or polishing
        if mode != "shorten":
            orig_words = len(original_ph_text.split())
            pass1_words = len(pass1_ph_text.split())
            coverage = pass1_words / orig_words if orig_words > 0 else 1.0
            if coverage < _COVERAGE_THRESHOLD:
                errors.append(
                    f"Pass 1 coverage too low: {coverage:.0%} "
                    f"({pass1_words} / {orig_words} words). "
                    f"Minimum: {_COVERAGE_THRESHOLD:.0%}"
                )

        return len(errors) == 0, errors

    def validate_final(
        self,
        original_text: str,
        final_text: str,
        placeholders: dict[str, str],
        mode: str = "expand",
    ) -> tuple[bool, list[str], list[str]]:
        """Check final output for scripture verbatim match, coverage, and fabrication signals.

        In 'shorten' mode the coverage minimum is skipped — fewer words is the goal.
        Returns (ok, errors, warnings).
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Scripture verbatim check (hard failure)
        missing = check_scripture_verbatim(original_text, final_text, placeholders)
        for span in missing:
            errors.append(f"Scripture span missing from final output: {span!r}")

        # Coverage check — only meaningful when expanding or polishing
        if mode != "shorten":
            orig_words = len(original_text.split())
            final_words = len(final_text.split())
            coverage = final_words / orig_words if orig_words > 0 else 1.0
            if coverage < _COVERAGE_THRESHOLD:
                errors.append(
                    f"Final coverage too low: {coverage:.0%} "
                    f"({final_words} / {orig_words} words)"
                )

        # Unattributed facts heuristic — years in final not in original
        orig_years = set(re.findall(r"\b(1[0-9]{3}|20[0-2][0-9])\b", original_text))
        final_years = set(re.findall(r"\b(1[0-9]{3}|20[0-2][0-9])\b", final_text))
        new_years = final_years - orig_years
        if new_years:
            warnings.append(
                f"Possible unattributed years introduced: {sorted(new_years)} — "
                f"review for fabricated facts before publishing"
            )

        return len(errors) == 0, errors, warnings


class DocumentaryScriptEnhancerPipeline:
    """Transform a normalized transcript into a cinematic YouTube documentary narration.

    Two-pass structure per ADR-0011:
    - Pass 1 (fidelity gate): preserves philosophy, stories, emotional intent
    - Pass 2 (retention loop): cinematic storytelling, Narrative Score self-assessment
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = get_llm_provider(settings)
        self._validator = DocumentaryEnhancerValidator()

    def _should_abort(self) -> bool:
        return getattr(self._settings, "stop_on_quality_gate_failure", True)

    def _abort(self, stage: str, reason: str) -> None:
        if self._should_abort():
            raise PipelineAbort(stage=stage, reason=reason)

    def run(
        self,
        project_id: str,
        *,
        topic: str,
        style: str | None = None,
        target_minutes: int = TARGET_IDEAL_MINUTES,
        script_text: str | None = None,
    ) -> str:
        """Enhance a script via two-pass documentary writing and return the final text.

        Args:
            project_id: Project identifier used to locate / write workspace files.
            topic: Video topic — passed to prompts and brand elements.
            style: Narrative style hint ("spiritual", "documentary", etc.).
            target_minutes: Target narration duration in minutes.
            script_text: Raw script text. When None, read from
                ``workspace/jobs/<id>/script/script.md``.
        """
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_dir.mkdir(parents=True, exist_ok=True)

        if script_text is None:
            script_file = script_dir / "script.md"
            if not script_file.exists():
                raise FileNotFoundError(
                    f"DocumentaryScriptEnhancerPipeline: no script found at {script_file}"
                )
            script_text = script_file.read_text(encoding="utf-8")

        # Strip any leading H1 title heading — it is a structural label, not spoken narration.
        script_text, _script_heading = strip_script_heading(script_text)

        raw_words = len(script_text.split())
        target_words = target_minutes * NARRATION_WPM
        min_minutes = target_minutes - DURATION_TOLERANCE_MINUTES
        max_minutes = target_minutes + DURATION_TOLERANCE_MINUTES
        raw_est = raw_words / NARRATION_WPM

        if raw_est > max_minutes:
            mode = "shorten"
            mode_label = "shortening to target"
        elif _duration_ok(raw_est, target_minutes):
            mode = "polish"
            mode_label = "already in range — polishing"
        else:
            mode = "expand"
            mode_label = "expanding to target"

        style_label = f" [{style}]" if style else ""
        console.print(
            f"\n[bold magenta]✍  Documentary Script Enhancer[/bold magenta]{style_label} — "
            f"{mode_label} "
            f"(target: {target_minutes} min ±{DURATION_TOLERANCE_MINUTES} min)..."
        )
        console.print(
            f"  [dim]Input:[/dim] {raw_words} words (~{raw_est:.1f} min) → "
            f"target {target_minutes} min (~{target_words} words, "
            f"range {min_minutes}–{max_minutes} min)"
        )

        # ── Scripture extraction ────────────────────────────────────────────────
        placeholder_text, placeholders = extract_scripture_spans(script_text)
        if placeholders:
            console.print(
                f"  [dim]Scripture protection: {len(placeholders)} span(s) extracted[/dim]"
            )

        # ── Pass 1: Faithful Enhancement ───────────────────────────────────────
        _w = get_writer()
        if _w:
            _w.stage_start("documentary_enhancer_pass1")
        console.print("  [cyan]Pass 1:[/cyan] Faithful Enhancement (temp=0.4)...")
        pass1_prompt = build_pass1_prompt(
            topic=topic,
            script=placeholder_text,
            style=style,
            target_minutes=target_minutes,
            mode=mode,
            raw_words=raw_words,
            placeholders=placeholders,
        )
        pass1_response = self._llm.generate(pass1_prompt, temperature=0.4)
        pass1_ph_text = pass1_response.text.strip()

        pass1_ok, pass1_errors = self._validator.validate_pass1(
            placeholder_text, pass1_ph_text, mode=mode
        )
        pass1_fallback = False

        if not pass1_ok:
            logger.warning(
                "Documentary enhancer Pass 1 validation failed: {}", pass1_errors
            )
            console.print(
                "  [yellow]⚠ Pass 1 validation failed — using normalized input as fallback[/yellow]"
            )
            for err in pass1_errors:
                console.print(f"    [dim red]{err}[/dim red]")
            pass1_ph_text = placeholder_text
            pass1_fallback = True
        else:
            console.print("  [green]✓ Pass 1 validation passed[/green]")

        pass1_restored = restore_scripture_spans(pass1_ph_text, placeholders)
        (script_dir / "script_pass1.md").write_text(pass1_restored, encoding="utf-8")
        if _w:
            _w.stage_complete()

        # ── Pass 2: Viewer Retention Optimization ──────────────────────────────
        if _w:
            _w.stage_start("documentary_enhancer_pass2")
        console.print(
            f"  [cyan]Pass 2:[/cyan] Viewer Retention Optimization "
            f"(temp=0.7, max {_MAX_PASS2_ITERATIONS} iterations)..."
        )
        pass2_ph_text = pass1_ph_text
        narrative_score: float | None = None
        pass2_iterations = 0

        for iteration in range(_MAX_PASS2_ITERATIONS):
            pass2_iterations = iteration + 1
            pass2_prompt = build_pass2_prompt(
                topic=topic,
                script=pass2_ph_text,
                style=style,
                target_minutes=target_minutes,
                placeholders=placeholders,
                welcome=get_welcome(),
                closing=get_closing(),
                topic_transition=get_transition(),
                cta=get_cta(),
                closing_brand=get_closing_brand(),
            )
            pass2_response = self._llm.generate(pass2_prompt, temperature=0.7)
            raw_output = pass2_response.text.strip()

            pass2_ph_text, narrative_score = _parse_narrative_score(raw_output)
            pass2_ph_text = pass2_ph_text.strip()

            score_label = f"{narrative_score:.1f}/10" if narrative_score is not None else "no score"
            console.print(
                f"    Iteration {pass2_iterations}: Narrative Score = {score_label}"
            )

            if narrative_score is not None and narrative_score >= _NARRATIVE_SCORE_THRESHOLD:
                break

            if _w:
                _w.stage_retry(pass2_iterations, _MAX_PASS2_ITERATIONS, score=narrative_score)

        if _w:
            _w.stage_complete()

        if narrative_score is not None and narrative_score < _NARRATIVE_SCORE_THRESHOLD:
            console.print(
                f"  [yellow]⚠ Narrative Score {narrative_score:.1f} below threshold "
                f"{_NARRATIVE_SCORE_THRESHOLD} after {_MAX_PASS2_ITERATIONS} iterations — "
                f"using best attempt[/yellow]"
            )
            self._abort(
                stage="documentary_enhancer_pass2",
                reason=(
                    f"Narrative Score {narrative_score:.1f} below threshold "
                    f"{_NARRATIVE_SCORE_THRESHOLD} after {_MAX_PASS2_ITERATIONS} iterations"
                ),
            )

        # ── Final validation ────────────────────────────────────────────────────
        final_restored = restore_scripture_spans(pass2_ph_text, placeholders)
        final_ok, final_errors, final_warnings = self._validator.validate_final(
            script_text, final_restored, placeholders, mode=mode
        )

        if not final_ok:
            logger.warning(
                "Documentary enhancer final validation failed: {}", final_errors
            )
            console.print(
                "  [yellow]⚠ Final validation failed — falling back to Pass 1 output[/yellow]"
            )
            for err in final_errors:
                console.print(f"    [dim red]{err}[/dim red]")
            self._abort(
                stage="documentary_enhancer_final",
                reason=f"Final validation failed: {'; '.join(final_errors)}",
            )
            final_restored = pass1_restored

        for warn in final_warnings:
            logger.warning("Documentary enhancer: {}", warn)
            console.print(f"  [yellow]⚠ {warn}[/yellow]")

        if final_ok:
            console.print("  [green]✓ Final validation passed[/green]")

        # ── ADR-0012: religion-agnostic presentation check ──────────────────────
        ra_warnings = religion_agnostic.check(final_restored)
        if ra_warnings:
            console.print(
                f"  [yellow]⚠ ADR-0012 presentation flags ({len(ra_warnings)}) — "
                f"review before publishing:[/yellow]"
            )
            for w in ra_warnings:
                logger.warning(w)
                console.print(f"    [dim yellow]{w}[/dim yellow]")

        # ── Metrics and output ──────────────────────────────────────────────────
        enhanced_words = len(final_restored.split())
        enhanced_est = enhanced_words / NARRATION_WPM
        ok = _duration_ok(enhanced_est, target_minutes)
        gap = enhanced_est - target_minutes

        if ok:
            console.print(
                f"  [green]✓ DURATION PASS[/green] — "
                f"{enhanced_est:.1f} min (target {target_minutes} min, gap {gap:+.1f} min)"
            )
        else:
            direction = "over" if gap > 0 else "under"
            console.print(
                f"  [yellow]⚠ DURATION WARN[/yellow] — "
                f"{enhanced_est:.1f} min is {abs(gap):.1f} min {direction} target "
                f"(tolerance ±{DURATION_TOLERANCE_MINUTES} min)"
            )

        # ── Pass 3 (correction): one targeted length-adjustment if out of tolerance ──
        correction_pass_data: dict = {"attempted": False}
        if not ok:
            correction_mode = "expand" if gap < 0 else "shorten"
            correction_label = "expanding" if gap < 0 else "trimming"
            console.print(
                f"  [cyan]Pass 3:[/cyan] Duration correction — {correction_label} "
                f"({enhanced_est:.1f} min → target {target_minutes} min, temp=0.4)..."
            )
            corr_ph_text, corr_placeholders = extract_scripture_spans(final_restored)
            corr_prompt = build_pass1_prompt(
                topic=topic,
                script=corr_ph_text,
                style=style,
                target_minutes=target_minutes,
                mode=correction_mode,
                raw_words=enhanced_words,
                placeholders=corr_placeholders,
            )
            corr_response = self._llm.generate(corr_prompt, temperature=0.4)
            corr_ph_out = corr_response.text.strip()
            corr_restored = restore_scripture_spans(corr_ph_out, corr_placeholders)

            corr_words = len(corr_restored.split())
            corr_est = corr_words / NARRATION_WPM
            correction_ok = _duration_ok(corr_est, target_minutes)
            corr_gap = corr_est - target_minutes

            correction_pass_data = {
                "attempted": True,
                "mode": correction_mode,
                "input_minutes": round(enhanced_est, 2),
                "output_minutes": round(corr_est, 2),
                "output_words": corr_words,
                "correction_ok": correction_ok,
            }

            if correction_ok:
                console.print(
                    f"  [green]✓ DURATION PASS (after correction)[/green] — "
                    f"{corr_est:.1f} min (gap {corr_gap:+.1f} min)"
                )
                final_restored = corr_restored
                enhanced_words = corr_words
                enhanced_est = corr_est
                ok = True
                gap = corr_gap
            else:
                corr_direction = "over" if corr_gap > 0 else "under"
                logger.error(
                    "Duration correction failed: {:.1f} min is {:.1f} min {} target after "
                    "Pass 3 — script accepted out-of-tolerance; manual review recommended",
                    corr_est,
                    abs(corr_gap),
                    corr_direction,
                )
                console.print(
                    f"  [red]✗ DURATION FAIL (after correction)[/red] — "
                    f"{corr_est:.1f} min still {abs(corr_gap):.1f} min {corr_direction} target. "
                    f"Script accepted out-of-tolerance — manual review recommended."
                )
                self._abort(
                    stage="documentary_enhancer_duration",
                    reason=(
                        f"Duration {corr_est:.1f} min is {abs(corr_gap):.1f} min "
                        f"{corr_direction} target after correction "
                        f"(tolerance ±{DURATION_TOLERANCE_MINUTES} min)"
                    ),
                )

        logger.info(
            "Documentary enhancer: {} → {} words (~{:.1f} min), target {} min, "
            "ok={}, narrative_score={}, pass1_fallback={}, final_ok={}",
            raw_words,
            enhanced_words,
            enhanced_est,
            target_minutes,
            ok,
            narrative_score,
            pass1_fallback,
            final_ok,
        )

        (script_dir / "script_original.md").write_text(script_text, encoding="utf-8")
        (script_dir / "script.md").write_text(final_restored, encoding="utf-8")
        (script_dir / "script.json").write_text(
            json.dumps(
                {
                    "topic": topic,
                    "word_count": enhanced_words,
                    "estimated_minutes": round(enhanced_est, 2),
                    "target_minutes": target_minutes,
                    "tolerance_minutes": DURATION_TOLERANCE_MINUTES,
                    "duration_ok": ok,
                    "gap_minutes": round(gap, 2),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (script_dir / "enhancement-report.json").write_text(
            json.dumps(
                {
                    "topic": topic,
                    "mode": mode,
                    "scripture_spans": len(placeholders),
                    "pass1": {
                        "validation_passed": pass1_ok,
                        "errors": pass1_errors,
                        "fallback_used": pass1_fallback,
                    },
                    "pass2": {
                        "iterations": pass2_iterations,
                        "narrative_score": narrative_score,
                        "score_threshold": _NARRATIVE_SCORE_THRESHOLD,
                    },
                    "final": {
                        "validation_passed": final_ok,
                        "errors": final_errors,
                        "warnings": final_warnings,
                        "fallback_to_pass1": not final_ok,
                    },
                    "adr_0012_flags": ra_warnings,
                    "correction_pass": correction_pass_data,
                    "word_count": {
                        "input": raw_words,
                        "output": enhanced_words,
                        "estimated_minutes": round(enhanced_est, 2),
                        "target_minutes": target_minutes,
                        "duration_ok": ok,
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        status_color = "green" if ok else "yellow"
        console.print(
            Panel(
                f"[{status_color}]Script ready[/{status_color}] — {enhanced_words} words, "
                f"~{enhanced_est:.1f} min (target {target_minutes} min)\n"
                f"[dim]Pass 1 → script_pass1.md | Final → script.md | "
                f"Report → enhancement-report.json[/dim]",
                title="Documentary Script Enhancer",
                border_style="magenta",
            )
        )

        return final_restored


# Backward-compatible alias — existing callers and test patches continue to work
ScriptEnhancerPipeline = DocumentaryScriptEnhancerPipeline
