"""DocumentaryScriptEnhancerPipeline — transform a normalized transcript into a
cinematic documentary narration. Formerly ScriptEnhancerPipeline (renamed per ADR-0010).

ScriptEnhancerPipeline is preserved as a backward-compatible alias.
"""

from __future__ import annotations

import json
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
from ytfactory.agents.prompts.script_enhancer import build_enhance_script_prompt
from ytfactory.agents.prompts.script_writer import (
    DURATION_TOLERANCE_MINUTES,
    NARRATION_WPM,
    TARGET_IDEAL_MINUTES,
)
from ytfactory.config.settings import Settings
from video_core.providers.llm.factory import get_llm_provider
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()


def _duration_ok(estimated_minutes: float, target_minutes: int) -> bool:
    return abs(estimated_minutes - target_minutes) <= DURATION_TOLERANCE_MINUTES


class DocumentaryScriptEnhancerPipeline:
    """Transform a normalized transcript into a cinematic YouTube documentary narration.

    This stage assumes its input has already been cleaned by LightNormalizationPipeline.
    Its sole responsibility is narrative optimization — not artifact cleanup.

    Enhancement priority order (applied by the LLM prompt):
      1. Preserve meaning, philosophy, and emotional intent
      2. Improve narrative flow for a documentary audience
      3. Increase viewer retention through storytelling
      4. Improve cinematic pacing and rhythm
      5. Produce memorable shareable lines
    """

    def __init__(self, settings: Settings) -> None:
        self._llm = get_llm_provider(settings)

    def run(
        self,
        project_id: str,
        *,
        topic: str,
        style: str | None = None,
        target_minutes: int = TARGET_IDEAL_MINUTES,
        script_text: str | None = None,
    ) -> str:
        """Enhance a script and return the enhanced text.

        Args:
            project_id: Project identifier used to locate / write workspace files.
            topic: Video topic — passed to brand prompts.
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
                    f"ScriptEnhancerPipeline: no script found at {script_file}"
                )
            script_text = script_file.read_text(encoding="utf-8")

        raw_words = len(script_text.split())
        target_words = target_minutes * NARRATION_WPM
        min_minutes = target_minutes - DURATION_TOLERANCE_MINUTES
        max_minutes = target_minutes + DURATION_TOLERANCE_MINUTES
        raw_est = raw_words / NARRATION_WPM

        # Determine direction: only shorten when over target, expand when under.
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
            f"\n[bold magenta]✍  Script Enhancer[/bold magenta]{style_label} — "
            f"{mode_label} "
            f"(target: {target_minutes} min ±{DURATION_TOLERANCE_MINUTES} min)..."
        )
        console.print(
            f"  [dim]Input:[/dim] {raw_words} words (~{raw_est:.1f} min) → "
            f"target {target_minutes} min (~{target_words} words, range {min_minutes}–{max_minutes} min)"
        )

        prompt = build_enhance_script_prompt(
            topic,
            script_text,
            style,
            target_minutes=target_minutes,
            welcome=get_welcome(),
            closing=get_closing(),
            topic_transition=get_transition(),
            cta=get_cta(),
            closing_brand=get_closing_brand(),
            mode=mode,
            raw_words=raw_words,
        )
        response = self._llm.generate(prompt, temperature=0.6)
        enhanced = response.text.strip()

        enhanced_words = len(enhanced.split())
        enhanced_est = enhanced_words / NARRATION_WPM
        console.print(
            f"  [green]✓[/green] Enhanced: {enhanced_words} words "
            f"(~{enhanced_est:.1f} min at {NARRATION_WPM} wpm)"
        )

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

        logger.info(
            "Script enhanced: {} → {} words (~{:.1f} min), target {} min, ok={}",
            raw_words,
            enhanced_words,
            enhanced_est,
            target_minutes,
            ok,
        )

        (script_dir / "script_original.md").write_text(script_text, encoding="utf-8")
        (script_dir / "script.md").write_text(enhanced, encoding="utf-8")
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

        status_color = "green" if ok else "yellow"
        console.print(
            Panel(
                f"[{status_color}]Script ready[/{status_color}] — {enhanced_words} words, "
                f"~{enhanced_est:.1f} min (target {target_minutes} min)\n"
                f"[dim]Original saved to script_original.md[/dim]",
                title="Script Enhancer",
                border_style="magenta",
            )
        )

        return enhanced


# Backward-compatible alias — existing callers and test patches continue to work
ScriptEnhancerPipeline = DocumentaryScriptEnhancerPipeline
