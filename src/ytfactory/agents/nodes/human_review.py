"""Human-in-the-loop review gate nodes."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.editorial_qa.review_gate import FinalScriptReviewGate

console = Console()


def human_review_script_node(state: VideoState) -> dict:
    """
    Gate: show the generated script and let the user approve, skip, or edit.
    In auto_mode this is a no-op pass-through.
    """
    if state.get("auto_mode", False):
        return {}

    script = state.get("script_md", "")
    word_count = len(script.split())

    console.print(
        Panel(
            f"[bold]Script Review[/bold]\n"
            f"Words: {word_count} (~{word_count // 130} min)",
            title="Human Review Gate",
            border_style="yellow",
        )
    )
    console.print(
        Markdown(
            script[:3000]
            + ("\n\n*[...truncated for review]*" if len(script) > 3000 else "")
        )
    )
    console.print()

    action = (
        typer.prompt(
            "Action? [a]pprove / [s]kip and continue / [q]uit",
            default="a",
        )
        .strip()
        .lower()
    )

    if action.startswith("q"):
        raise typer.Abort()

    return {}


def human_review_base_script_node(state: VideoState) -> dict:
    """
    Gate: show the translated base script (from YouTube ingestion) and let
    the user approve, skip, or edit before script_enhancer runs.
    Only reached via the source_url entry route. In auto_mode this is a
    no-op pass-through, same as the other review gates.
    """
    if state.get("auto_mode", False):
        return {}

    script = state.get("script_md", "")
    word_count = len(script.split())

    console.print(
        Panel(
            f"[bold]Base Script Review[/bold] (translated from source discourse)\n"
            f"Words: {word_count}",
            title="Human Review Gate",
            border_style="yellow",
        )
    )
    console.print(
        Markdown(
            script[:3000]
            + ("\n\n*[...truncated for review]*" if len(script) > 3000 else "")
        )
    )
    console.print()

    action = (
        typer.prompt(
            "Action? [a]pprove / [s]kip and continue / [q]uit",
            default="a",
        )
        .strip()
        .lower()
    )

    if action.startswith("q"):
        raise typer.Abort()

    return {}


def human_review_scenes_node(state: VideoState) -> dict:
    """
    Gate: show the scene plan and let the user approve or abort.
    In auto_mode this is a no-op pass-through.
    """
    if state.get("auto_mode", False):
        return {}

    scenes = state.get("scene_plan", [])

    table = Table(title="Scene Plan Review", show_lines=True)
    table.add_column("#", style="cyan", width=4)
    table.add_column("Title", style="bold")
    table.add_column("Sec", width=5)
    table.add_column("Narration", max_width=55)
    table.add_column("Visual prompt", max_width=40)

    for s in scenes:
        narration = (
            s["narration"][:80] + "…" if len(s["narration"]) > 80 else s["narration"]
        )
        visual = (
            s["visual_prompt"][:50] + "…"
            if len(s["visual_prompt"]) > 50
            else s["visual_prompt"]
        )
        table.add_row(
            str(s["index"]), s["title"], str(s["duration_seconds"]), narration, visual
        )

    console.print(table)
    console.print()

    action = (
        typer.prompt(
            "Action? [a]pprove / [s]kip and continue / [q]uit",
            default="a",
        )
        .strip()
        .lower()
    )

    if action.startswith("q"):
        raise typer.Abort()

    return {}


def human_review_final_script_node(state: VideoState) -> dict:
    """
    Gate: present the finalized script (post Editorial QA) alongside its QA
    report, between structural retention / editorial_qa and scene_planner.

    Named "final_script" (not "script") to avoid colliding with
    human_review_script_node above, which reviews the pre-enhancement draft —
    a different checkpoint entirely.

    Delegates to FinalScriptReviewGate, which hash-guards script.md: unchanged
    since the last review -> skip straight through (QA already valid);
    changed (hand-edited during the pause) -> re-run Editorial QA on the edit
    first (report-only), then present the new report. Never rewrites the
    script itself.
    """
    FinalScriptReviewGate(Settings()).run(
        state["project_id"],
        state.get("script_md", ""),
        auto_mode=state.get("auto_mode", False),
    )
    return {}
