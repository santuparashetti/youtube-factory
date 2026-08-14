"""SourceRefinerPipeline — two-job editorial pass on the base source script.

Job 1: Universalize — strip culturally specific language, replace with
       universal principles in plain English.
Job 2: Distill — 550-650 words, protect dynamically extracted beats.

Runs before ComposerPipeline. Reads script/script.md, applies the
SOURCE_REFINER_PROMPT (with beats injected at runtime), backs up the
original to script_pre_refiner.md, writes the refined text in place.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from video_core.providers.llm.factory import get_llm_for_role
from ytfactory.beats_extractor.pipeline import format_beats_list
from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "SOURCE_REFINER_PROMPT.md"
_MAX_RETRIES = 3
_NARRATION_WPM = 130

# Matches any line that contains at least one LLM verification footer token.
_FOOTER_TOKEN_RE = re.compile(
    r"\[(?:WORD COUNT|BEATS PRESERVED)[^\]]*\]",
    re.IGNORECASE,
)


def _strip_llm_footer(text: str) -> str:
    """Remove lines that contain [WORD COUNT: ...] or [BEATS PRESERVED: ...] tokens."""
    lines = text.splitlines()
    clean = [l for l in lines if not _FOOTER_TOKEN_RE.search(l)]
    return "\n".join(clean).strip()


@functools.lru_cache(maxsize=1)
def _load_prompt_template() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _word_targets(target_minutes: int) -> tuple[int, int]:
    """Compute (word_min, word_max) for the refiner from the target duration.

    The refiner produces a distilled seed that the composer will expand.
    Target ≈ 65% of the composer's final word count, ±5%.
    """
    center = target_minutes * _NARRATION_WPM
    return int(center * 0.60), int(center * 0.70)


def _build_prompt(beats: list[dict], word_min: int, word_max: int) -> str:
    """Inject the dynamic beat list and word targets into the prompt template."""
    beats_text = format_beats_list(beats) if beats else "(No beats extracted for this script.)"
    return _load_prompt_template().format(
        beats_list=beats_text, word_min=word_min, word_max=word_max
    )


class SourceRefinerPipeline:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = get_llm_for_role(settings, "source_refiner")

    def run(self, project_id: str, beats: list[dict] | None = None, target_minutes: int = 5) -> str:
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_file = script_dir / "script.md"

        if not script_file.exists():
            raise FileNotFoundError(
                f"SourceRefiner: no source found at {script_file}. "
                "Run import-script first."
            )

        source = script_file.read_text(encoding="utf-8")
        original_words = len(source.split())

        word_min, word_max = _word_targets(target_minutes)
        min_word_count = int(word_min * 0.9)  # floor for retry guard (90% of lower bound)

        console.print(
            "\n[bold cyan]✎  Source Refiner[/bold cyan] — editorial pass on source material..."
        )
        console.print(
            f"  [dim]Input: {original_words} words | Target: {word_min}–{word_max} words "
            f"(~{target_minutes} min)[/dim]"
        )

        system_prompt = _build_prompt(beats or [], word_min, word_max)

        refined = ""
        refined_words = 0
        for attempt in range(1, _MAX_RETRIES + 1):
            if attempt == 1:
                user_message = source
            else:
                user_message = (
                    f"{source}\n\n"
                    f"[REVISION REQUEST — attempt {attempt}]\n"
                    f"Your previous output was only {refined_words} words. "
                    f"The requirement is 550–600 words. "
                    f"You must expand every beat to its fuller form. "
                    f"Do not summarise — write each scene and teaching in full sentences. "
                    f"Recount the story with more detail. Target 570 words minimum."
                )
            try:
                response = self._llm.generate(
                    user_message,
                    system_prompt=system_prompt,
                    temperature=0.2,
                )
                refined = response.text.strip()
            except Exception as exc:
                logger.error("SourceRefiner: LLM call failed (attempt {}) — {}", attempt, exc)
                raise

            if not refined:
                raise RuntimeError("SourceRefiner: LLM returned empty output.")

            refined = _strip_llm_footer(refined)
            refined_words = len(refined.split())
            if refined_words >= min_word_count:
                break

            logger.warning(
                "SourceRefiner: output too short ({} words) on attempt {}/{}; retrying with feedback.",
                refined_words, attempt, _MAX_RETRIES,
            )

        if refined_words < min_word_count:
            backup_path = script_dir / "script_pre_refiner.md"
            backup_path.write_text(source, encoding="utf-8")
            (script_dir / "script_refiner_too_short.md").write_text(refined, encoding="utf-8")
            logger.error(
                "SourceRefiner: output too short ({} words, minimum {}) after {} attempts. "
                "Pipeline halted. Review script_pre_refiner.md and beats.json, then re-run.",
                refined_words, min_word_count, _MAX_RETRIES,
            )
            raise RuntimeError(
                f"SourceRefiner output too short ({refined_words} words, minimum {min_word_count}) "
                f"after {_MAX_RETRIES} attempts. "
                "Pipeline halted. Review script_pre_refiner.md and beats.json, then re-run."
            )

        word_delta = refined_words - original_words

        backup_path = script_dir / "script_pre_refiner.md"
        backup_path.write_text(source, encoding="utf-8")
        script_file.write_text(refined, encoding="utf-8")

        delta_str = f"+{word_delta}" if word_delta > 0 else str(word_delta)
        logger.info(
            "SourceRefiner: {} → {} words ({}) | original backed up to script_pre_refiner.md",
            original_words, refined_words, delta_str,
        )
        console.print(
            Panel(
                f"[green]Refined[/green] — {original_words} → {refined_words} words ({delta_str})\n"
                f"[dim]Original → script_pre_refiner.md | Refined → script.md[/dim]",
                title="Source Refiner",
                border_style="cyan",
            )
        )

        return refined
