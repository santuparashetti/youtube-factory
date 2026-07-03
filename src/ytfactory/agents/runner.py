"""CLI-facing runner: invoke the agentic LangGraph pipeline."""

from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from ytfactory.agents.graph import graph
from ytfactory.agents.state import VideoState
from ytfactory.create.pipeline import CreatePipeline
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()


def run_pipeline(
    topic: str,
    *,
    project_id: str | None = None,
    language: str = "en",
    auto: bool = False,
) -> str:
    """
    Run the full agentic video production pipeline.

    Args:
        topic:      Video topic / title.
        project_id: Resume an existing project (skips create step).
        language:   BCP-47 language code for TTS voice selection.
        auto:       If True, skip all human-review gates.

    Returns:
        The project_id of the produced video.
    """
    start_time = time.perf_counter()

    console.print(Rule("[bold cyan]YouTube Factory — Agentic Pipeline[/bold cyan]"))
    console.print()

    # ── Create project if not resuming ───────────────────────────────────
    if project_id is None:
        project = CreatePipeline().run(topic)
        project_id = project.id
        console.print(
            Panel(
                f"[green]✓[/green] Project created: [bold]{project_id}[/bold]\n"
                f"Workspace: {Path(WORKSPACE_DIR) / project_id}",
                title="Project",
                border_style="cyan",
            )
        )
    else:
        console.print(f"[cyan]Resuming project:[/cyan] [bold]{project_id}[/bold]")

    console.print()

    # ── Build initial state ───────────────────────────────────────────────
    initial_state: VideoState = {
        "project_id": project_id,
        "topic": topic,
        "language": language,
        "topic_category": "other",
        "auto_mode": auto,
        "scene_plan": [],
        "image_paths": {},
        "audio_paths": {},
        "audio_durations": {},
        "srt_paths": {},
        "scene_video_paths": {},
        "stage_errors": [],
    }

    # ── Run the graph ─────────────────────────────────────────────────────
    config = {"configurable": {"thread_id": project_id}}

    final_state = graph.invoke(initial_state, config=config)

    # ── Summary ───────────────────────────────────────────────────────────
    elapsed = time.perf_counter() - start_time
    minutes, seconds = divmod(int(elapsed), 60)

    errors = final_state.get("stage_errors", [])
    final_video = final_state.get("final_video_path", "")

    console.print()
    console.print(Rule("[bold green]Pipeline Complete[/bold green]"))
    console.print()
    console.print(Panel(
        f"[bold]Topic:[/bold] {topic}\n"
        f"[bold]Project:[/bold] {project_id}\n"
        f"[bold]Final video:[/bold] {final_video or 'not produced'}\n"
        f"[bold]Time:[/bold] {minutes}m {seconds}s\n"
        f"[bold]Errors:[/bold] {len(errors)} non-fatal"
        + ("\n\n[yellow]Warnings:[/yellow]\n" + "\n".join(f"  • {e}" for e in errors) if errors else ""),
        title="Summary",
        border_style="green" if not errors else "yellow",
    ))

    return project_id
