"""A/B script selection — run the composer twice on the same base script,
let the user pick a winner via an interactive terminal prompt, then rename
the chosen file to what the next pipeline stage expects.

Composer logic itself (ComposerPipeline.run) is untouched — this only calls
it twice and adds the pause/selector/rename around it.
"""

from __future__ import annotations

from pathlib import Path

import questionary
from rich.console import Console

from ytfactory.composer.pipeline import ComposerPipeline
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shared.pipeline_status import PipelineAbort

console = Console()

DIVIDER = "━" * 40
WORDS_PER_MINUTE = 140  # display estimate only — independent of composer's own target WPM


def run_composer_with_ab_selection(composer: ComposerPipeline, project_id: str) -> None:
    """Run the composer twice on the same input, save script-a.md/script-b.md,
    pause for the user to pick one, then rename it to script.md (and the
    rejected one to script-rejected.md) before the pipeline continues."""
    script_dir = Path(WORKSPACE_DIR) / project_id / "script"
    script_file = script_dir / "script.md"
    base_script_text = script_file.read_text(encoding="utf-8")

    composer.run(project_id, script_text=base_script_text)
    script_a = script_dir / "script-a.md"
    script_a.write_text(script_file.read_text(encoding="utf-8"), encoding="utf-8")

    composer.run(project_id, script_text=base_script_text)
    script_b = script_dir / "script-b.md"
    script_b.write_text(script_file.read_text(encoding="utf-8"), encoding="utf-8")

    words_a = len(script_a.read_text(encoding="utf-8").split())
    words_b = len(script_b.read_text(encoding="utf-8").split())
    minutes_a = words_a / WORDS_PER_MINUTE
    minutes_b = words_b / WORDS_PER_MINUTE

    console.print(f"\n{DIVIDER}")
    console.print("  TWO SCRIPTS GENERATED — EDITORIAL REVIEW")
    console.print(f"{DIVIDER}\n")
    console.print(f"  script-a.md   →   {words_a} words  (~{minutes_a:.0f} min)")
    console.print(f"  script-b.md   →   {words_b} words  (~{minutes_b:.0f} min)\n")
    console.print("  Review both files, then return here to select.\n")
    console.print(DIVIDER)
    console.print("  Use ↑ ↓ to select, Enter to confirm")
    console.print(f"{DIVIDER}\n")

    choice = questionary.select(
        "",
        choices=["script-a", "script-b"],
        qmark="",
        pointer="▶",
        instruction="(word count and estimated duration at 140 words per minute)",
    ).ask()

    if choice is None:
        raise PipelineAbort(
            stage="script_selection", reason="No script selected (prompt cancelled)"
        )

    chosen_path = script_a if choice == "script-a" else script_b
    rejected_path = script_b if choice == "script-a" else script_a
    chosen_name = f"{choice}.md"
    rejected_name = "script-b.md" if choice == "script-a" else "script-a.md"

    console.print(f"\n✓ {choice} selected")
    console.print(f"Renaming {chosen_name}       → script.md")
    console.print(f"Renaming {rejected_name}       → script-rejected.md")

    chosen_path.replace(script_file)
    rejected_path.replace(script_dir / "script-rejected.md")

    console.print("Continuing pipeline...\n")
