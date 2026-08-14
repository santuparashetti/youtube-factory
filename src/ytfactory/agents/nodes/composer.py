"""Composer node — delegates to ComposerPipeline.

Replaces script_enhancer_node + structural_retention_node in the active
graph. Both remain importable (archived, not deleted) but are no longer
wired into build_graph() — see agents/graph.py.
"""

from __future__ import annotations

from rich.console import Console

from ytfactory.agents.state import VideoState
from ytfactory.composer.pipeline import ComposerPipeline
from ytfactory.composer.selection import run_composer_with_ab_selection
from ytfactory.config.settings import Settings

console = Console()


def composer_node(state: VideoState) -> dict:
    """Compose the documentary narration from the base script.

    Two selection mechanisms, flag-gated (see `_route_after_composer` in
    agents/graph.py for how the graph routes on the outcome):

    1. `ab_script_selection=True` → interactive HUMAN A/B pick. Blocking terminal
       prompt; opt-in via its own wizard question, independent of auto_mode.
       Generates two variants internally and the user picks — sets `script_md`
       directly, so the graph routes straight to human_review_final_script (the
       LLM polisher is skipped).
    2. Otherwise (default) → produce TWO variants (`script_a`/`script_b`) at the
       configured temperatures and hand them to the script_selector_polisher node,
       which picks the stronger and lightly polishes it. This is the standard,
       non-interactive path and never blocks.
    """
    from pathlib import Path
    from ytfactory.shared.constants import WORKSPACE_DIR

    project_id = state["project_id"]
    script_file = Path(WORKSPACE_DIR) / project_id / "script" / "script.md"

    if script_file.exists() and not state.get("ab_script_selection", False):
        console.print(
            "\n[dim]Composer skipped — finalized script.md already exists.[/dim]"
        )
        return {"script_md": script_file.read_text(encoding="utf-8")}

    settings = Settings()
    pipeline = ComposerPipeline(settings)
    base_script = state.get("script_md", "")
    beats = state.get("beats") or []
    target_minutes = state.get("target_minutes", 5)

    if state.get("ab_script_selection", False):
        composed = run_composer_with_ab_selection(
            pipeline, project_id, base_script_text=base_script, beats=beats,
            target_minutes=target_minutes,
        )
        return {"script_md": composed}

    # Two composes on the same source using distinct variant prompts (A / B),
    # each owning different narrative strengths. The polisher node picks between them.
    topic = state.get("topic", "")
    script_a = pipeline.run(
        project_id,
        script_text=base_script,
        temperature=settings.composer_variant_temp_a,
        topic=topic,
        variant="A",
        beats=beats,
        target_minutes=target_minutes,
    )
    script_b = pipeline.run(
        project_id,
        script_text=base_script,
        temperature=settings.composer_variant_temp_b,
        topic=topic,
        variant="B",
        beats=beats,
        target_minutes=target_minutes,
    )
    return {"script_a": script_a, "script_b": script_b}
