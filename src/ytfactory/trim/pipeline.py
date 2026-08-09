"""SurgicalTrimPipeline — standalone trim pass on a composed script.

Reads script/script.md, applies SURGICAL_TRIM_PROMPT.md to reach the
6-8 min word target (780–1040 words at 130 wpm), backs up the original
to script_pre_trim.md, writes the trimmed version in place.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from video_core.providers.llm.factory import get_llm_for_role
from ytfactory.agents.prompts.composer import build_trim_system_prompt
from ytfactory.agents.prompts.script_writer import NARRATION_WPM
from ytfactory.composer.pipeline import _validate_rehook_present
from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()

TARGET_MIN_MINUTES = 6
TARGET_MAX_MINUTES = 8


class SurgicalTrimPipeline:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = get_llm_for_role(settings, "script")

    def run(self, project_id: str) -> str:
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_file = script_dir / "script.md"

        if not script_file.exists():
            raise FileNotFoundError(
                f"SurgicalTrim: no script found at {script_file}."
            )

        script = script_file.read_text(encoding="utf-8")
        current_words = len(script.split())
        current_minutes = current_words / NARRATION_WPM

        target_min_words = int(TARGET_MIN_MINUTES * NARRATION_WPM)
        target_max_words = int(TARGET_MAX_MINUTES * NARRATION_WPM)

        console.print(
            "\n[bold yellow]✂  Surgical Trim[/bold yellow] — compressing to target length..."
        )
        console.print(
            f"  [dim]Input: {current_words} words (~{current_minutes:.1f} min) "
            f"→ target {TARGET_MIN_MINUTES}-{TARGET_MAX_MINUTES} min "
            f"({target_min_words}-{target_max_words} words)[/dim]"
        )

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
            logger.error("SurgicalTrim: LLM call failed — {}", exc)
            raise

        if not trimmed:
            raise RuntimeError("SurgicalTrim: LLM returned empty output.")

        trimmed_words = len(trimmed.split())
        if trimmed_words >= current_words:
            raise RuntimeError(
                f"SurgicalTrim: output ({trimmed_words} words) is not shorter "
                f"than input ({current_words} words) — no trim occurred."
            )

        if not _validate_rehook_present(trimmed):
            raise RuntimeError(
                "SurgicalTrim: trimmed output failed rehook validation. "
                "Run the trim pass again or restore from script_pre_trim.md."
            )

        trimmed_minutes = trimmed_words / NARRATION_WPM
        in_range = TARGET_MIN_MINUTES <= trimmed_minutes <= TARGET_MAX_MINUTES

        backup_path = script_dir / "script_pre_trim.md"
        backup_path.write_text(script, encoding="utf-8")
        script_file.write_text(trimmed, encoding="utf-8")

        delta = trimmed_words - current_words
        status_color = "green" if in_range else "yellow"
        range_note = "" if in_range else " ⚠ still outside target"

        logger.info(
            "SurgicalTrim: {} → {} words ({:+d}) | {:.1f} min{}",
            current_words, trimmed_words, delta, trimmed_minutes, range_note,
        )
        console.print(
            Panel(
                f"[{status_color}]Trimmed[/{status_color}] — "
                f"{current_words} → {trimmed_words} words ({delta:+d}), "
                f"~{trimmed_minutes:.1f} min{range_note}\n"
                f"[dim]Original → script_pre_trim.md | Trimmed → script.md[/dim]",
                title="Surgical Trim",
                border_style="yellow",
            )
        )

        return trimmed
