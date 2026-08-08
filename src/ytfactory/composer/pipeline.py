"""ComposerPipeline — single whole-cloth composition of the documentary
narration from a base script, per ATMA_THEORY_COMPOSER.md.

Replaces the retired transform-based enhancer (Pass 1/2/3 — mode selection,
coverage floor, no-reorder ban) and the Structural Retention Pass. Both are
kept archived, not deleted, until this composer is proven — see
src/ytfactory/script_enhancer/pipeline.py and src/ytfactory/structural_retention/.

One LLM call composes the whole piece. Scripture protection is carried over
as a hard constraint (unrelated to the retired transform-model mechanics).
Length is steered by the framework's LENGTH section, not a word-count mode;
if a recompose-on-out-of-range fallback proves necessary it will re-compose
whole (never surgically trim) — see build_recompose_directive in
agents/prompts/composer.py, wired in once real output shows it's needed.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.prompts.composer import (
    build_composer_system_prompt,
    build_composer_user_prompt,
    build_trim_system_prompt,
)
from ytfactory.agents.prompts.script_writer import NARRATION_WPM
from ytfactory.config.settings import Settings
from ytfactory.validators.kai_firewall import check_artifact
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shared.pipeline_status import get_writer
from ytfactory.shared.scripture import (
    check_scripture_verbatim,
    extract_scripture_spans,
    restore_scripture_spans,
)
from video_core.providers.llm.factory import get_llm_for_role

console = Console()

TARGET_MIN_MINUTES = 7
TARGET_MAX_MINUTES = 9


class ComposerRehookMissingError(RuntimeError):
    """Raised when the composed script has no closing echo of the opening hook."""


_REHOOK_STOP = frozenset({
    "that", "this", "with", "from", "have", "their", "there",
    "where", "which", "about", "would", "could", "should",
})


def _validate_rehook_present(script_text: str) -> bool:
    """
    Heuristic: rehook exists if any line in the final 25% of the script
    echoes a key noun/phrase from the first 15% of the script.
    Fails fast rather than false-passing.
    """
    lines = [line.strip() for line in script_text.splitlines() if line.strip()]
    if len(lines) < 8:
        return False  # empty or too short — no rehook by definition
    opening_window = " ".join(lines[:max(3, len(lines) // 7)]).lower()
    closing_window = " ".join(lines[int(len(lines) * 0.75):]).lower()
    opening_nouns = {w for w in opening_window.split() if len(w) > 4 and w not in _REHOOK_STOP}
    return any(noun in closing_window for noun in opening_nouns)


class ComposerPipeline:
    """Whole-cloth composition — no mode selection, no coverage floor, no
    no-reorder ban. Those belonged to the retired transform model."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = get_llm_for_role(settings, "script")

    @property
    def provider(self):
        return self._llm

    def run(
        self,
        project_id: str,
        script_text: str | None = None,
        *,
        temperature: float | None = None,
    ) -> str:
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_dir.mkdir(parents=True, exist_ok=True)

        if script_text is None:
            script_file = script_dir / "script.md"
            if not script_file.exists():
                raise FileNotFoundError(f"ComposerPipeline: no base script found at {script_file}")
            script_text = script_file.read_text(encoding="utf-8")

        console.print(
            "\n[bold magenta]✍  Composer[/bold magenta] — composing the documentary whole..."
        )

        placeholder_text, placeholders = extract_scripture_spans(script_text)
        if placeholders:
            console.print(
                f"  [dim]Scripture protection: {len(placeholders)} span(s) extracted[/dim]"
            )

        system_prompt = build_composer_system_prompt(placeholders)

        _w = get_writer()
        if _w:
            _w.stage_start("composer")

        composed_ph = self._compose(system_prompt, placeholder_text, temperature=temperature)
        composed = restore_scripture_spans(composed_ph, placeholders)

        # Anchor character firewall — the pipeline-internal name "Kai" must never
        # reach viewer-facing output. Fail loud here rather than ship it downstream.
        check_artifact(composed, "script.md")

        # Rehook gate — structural check before scene planning.
        if not _validate_rehook_present(composed):
            opening_lines = [line for line in composed.splitlines() if line.strip()][:3]
            closing_lines = [line for line in composed.splitlines() if line.strip()][-3:]
            raise ComposerRehookMissingError(
                "Composer output missing rehook. Aborting before scene planning. "
                "Re-run to regenerate, or add a rehook manually and resume.\n"
                f"Opening: {opening_lines}\n"
                f"Closing: {closing_lines}"
            )

        words = len(composed.split())
        minutes = words / NARRATION_WPM
        in_range = TARGET_MIN_MINUTES <= minutes <= TARGET_MAX_MINUTES
        console.print(
            f"  [dim]Composed:[/dim] {words} words (~{minutes:.1f} min) — "
            f"target {TARGET_MIN_MINUTES}-{TARGET_MAX_MINUTES} min"
        )
        if not in_range and minutes > TARGET_MAX_MINUTES:
            logger.warning(
                "Composer: {:.1f} min outside {}-{} min target ({} words) — attempting trim pass",
                minutes, TARGET_MIN_MINUTES, TARGET_MAX_MINUTES, words,
            )
            console.print("  [yellow]⚠ Too long — running surgical trim pass...[/yellow]")
            trimmed = self._trim_to_range(composed)
            if trimmed is not None:
                composed = trimmed
                words = len(composed.split())
                minutes = words / NARRATION_WPM
                in_range = TARGET_MIN_MINUTES <= minutes <= TARGET_MAX_MINUTES
                console.print(
                    f"  [dim]After trim:[/dim] {words} words (~{minutes:.1f} min)"
                )
                if not in_range:
                    logger.warning(
                        "Trim pass: still outside range at {:.1f} min ({} words)",
                        minutes, words,
                    )
                    console.print("  [yellow]⚠ Trim pass did not reach target (keeping trimmed version)[/yellow]")
            else:
                logger.warning("Trim pass failed — keeping original composed output")
                console.print("  [yellow]⚠ Trim pass failed — keeping original[/yellow]")
        elif not in_range:
            logger.warning(
                "Composer: {:.1f} min outside {}-{} min target ({} words)",
                minutes, TARGET_MIN_MINUTES, TARGET_MAX_MINUTES, words,
            )
            console.print("  [yellow]⚠ Outside target range[/yellow]")

        missing = check_scripture_verbatim(script_text, composed, placeholders)
        if missing:
            logger.warning("Composer: scripture span(s) missing from output: {}", missing)
            console.print(f"  [red]⚠ {len(missing)} scripture span(s) missing from output[/red]")

        if _w:
            _w.stage_complete()

        (script_dir / "script_pre_composer.md").write_text(script_text, encoding="utf-8")
        (script_dir / "script.md").write_text(composed, encoding="utf-8")

        status_color = "green" if in_range else "yellow"
        console.print(
            Panel(
                f"[{status_color}]Composed[/{status_color}] — {words} words, ~{minutes:.1f} min "
                f"(target {TARGET_MIN_MINUTES}-{TARGET_MAX_MINUTES} min)\n"
                f"[dim]Base -> script_pre_composer.md | Final -> script.md[/dim]",
                title="Composer",
                border_style="magenta",
            )
        )

        return composed

    def _compose(
        self,
        system_prompt: str,
        base_script_ph: str,
        recompose_directive: str = "",
        *,
        temperature: float | None = None,
    ) -> str:
        prompt = build_composer_user_prompt(base_script_ph, recompose_directive)
        response = self._llm.generate(
            prompt,
            system_prompt=system_prompt,
            temperature=0.6 if temperature is None else temperature,
        )
        return response.text.strip()

    def _trim_to_range(self, script: str) -> str | None:
        """Surgical trim pass: remove filler/restatements to reach word target.

        Takes the placeholder-restored script (scripture already back in place).
        Returns the trimmed text on success, None if the LLM call fails or the
        output is clearly corrupt (empty, lost rehook).
        """
        target_min_words = int(TARGET_MIN_MINUTES * NARRATION_WPM)
        target_max_words = int(TARGET_MAX_MINUTES * NARRATION_WPM)
        current_words = len(script.split())
        system_prompt = build_trim_system_prompt(
            current_words, target_min_words, target_max_words
        )
        try:
            response = self._llm.generate(
                script,
                system_prompt=system_prompt,
                temperature=0.3,
            )
            trimmed = response.text.strip()
        except Exception as exc:
            logger.warning("Trim pass LLM call failed: {}", exc)
            return None

        if not trimmed:
            logger.warning("Trim pass returned empty output")
            return None

        trimmed_words = len(trimmed.split())
        if trimmed_words >= current_words:
            logger.warning(
                "Trim pass added words ({} → {}) — discarding",
                current_words, trimmed_words,
            )
            return None

        if not _validate_rehook_present(trimmed):
            logger.warning("Trim pass output failed rehook validation — discarding")
            return None

        return trimmed
