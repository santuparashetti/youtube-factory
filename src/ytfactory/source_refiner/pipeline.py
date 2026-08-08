"""SourceRefinerPipeline — conservative editorial pass on the base source script.

Runs before compose. Reads script/script.md, applies the SOURCE_REFINER_PROMPT
(universalise examples, improve clarity/flow, never rewrite what's already strong),
backs up the original to script_pre_refiner.md, writes the refined text in place.
"""

from __future__ import annotations

import functools
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from video_core.providers.llm.factory import get_llm_for_role
from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "SOURCE_REFINER_PROMPT.md"


@functools.lru_cache(maxsize=1)
def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


class SourceRefinerPipeline:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = get_llm_for_role(settings, "source_refiner")

    def run(self, project_id: str) -> str:
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_file = script_dir / "script.md"

        if not script_file.exists():
            raise FileNotFoundError(
                f"SourceRefiner: no source found at {script_file}. "
                "Run import-script first."
            )

        source = script_file.read_text(encoding="utf-8")
        original_words = len(source.split())

        console.print(
            "\n[bold cyan]✎  Source Refiner[/bold cyan] — editorial pass on source material..."
        )
        console.print(f"  [dim]Input: {original_words} words[/dim]")

        try:
            response = self._llm.generate(
                source,
                system_prompt=_load_prompt(),
                temperature=0.2,
            )
            refined = response.text.strip()
        except Exception as exc:
            logger.error("SourceRefiner: LLM call failed — {}", exc)
            raise

        if not refined:
            raise RuntimeError("SourceRefiner: LLM returned empty output.")

        refined_words = len(refined.split())
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
