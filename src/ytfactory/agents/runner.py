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
    script_path: str | None = None,
    style: str | None = None,
    no_images: bool = False,
    target_minutes: int = 7,
) -> str:
    """
    Run the full agentic video production pipeline.

    Args:
        topic:       Video topic / title.
        project_id:  Resume an existing project (skips create step).
        language:    BCP-47 language code for TTS voice selection.
        auto:        If True, skip all human-review gates.
        script_path: Path to a pre-written script file. When provided, the
                     research and script-writer stages are skipped entirely.
        style:       Visual style hint — "spiritual", "documentary", etc.
        no_images:   Skip image generation entirely. Use IMAGE_PROMPTS.md to
                     generate images manually, then re-run for video.

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

    # ── Load pre-written script if provided ──────────────────────────────
    script_md: str = ""
    if script_path:
        src = Path(script_path)
        if not src.exists():
            raise FileNotFoundError(f"Script file not found: {script_path}")
        script_md = src.read_text(encoding="utf-8")

        # Write to workspace so other commands can find it too
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_dir.mkdir(parents=True, exist_ok=True)
        (script_dir / "script.md").write_text(script_md, encoding="utf-8")

        word_count = len(script_md.split())
        console.print(
            f"[green]✓[/green] Script loaded: [bold]{word_count} words[/bold] "
            f"(~{word_count / 130:.1f} min at 130 wpm)"
        )
        if style:
            console.print(f"[green]✓[/green] Style: [bold]{style}[/bold]")

    if no_images:
        console.print(
            "[yellow]⚡ --no-images mode[/yellow]: image generation skipped. "
            "Generate images from [bold]images/IMAGE_PROMPTS.md[/bold] and re-run."
        )

    console.print()

    # ── Build initial state ───────────────────────────────────────────────
    initial_state: VideoState = {
        "project_id": project_id,
        "topic": topic,
        "language": language,
        "topic_category": "other",
        "style": style,
        "target_minutes": max(5, min(10, target_minutes)),
        "auto_mode": auto,
        "skip_images": no_images,
        "script_md": script_md,
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

    # Estimate video duration from scene plan
    scene_plan = final_state.get("scene_plan", [])
    estimated_video_str = ""
    if scene_plan:
        raw_secs = sum(s.get("duration_seconds", 0) for s in scene_plan)
        # Spiritual uses -20% TTS rate → audio takes ~1.25× longer than 130wpm estimate
        actual_secs = raw_secs / 0.8 if style == "spiritual" else raw_secs
        vm, vs = divmod(int(actual_secs), 60)
        narration_words = sum(len(s.get("narration", "").split()) for s in scene_plan)
        estimated_video_str = (
            f"\n[bold]Estimated video:[/bold] ~{vm}m {vs}s "
            f"({len(scene_plan)} scenes, {narration_words} words)"
        )

    console.print()
    console.print(Rule("[bold green]Pipeline Complete[/bold green]"))
    console.print()
    console.print(
        Panel(
            f"[bold]Topic:[/bold] {topic}\n"
            f"[bold]Project:[/bold] {project_id}\n"
            f"[bold]Pipeline ran in:[/bold] {minutes}m {seconds}s"
            + estimated_video_str
            + f"\n[bold]Final video:[/bold] {final_video or 'not produced'}\n"
            f"[bold]Errors:[/bold] {len(errors)} non-fatal"
            + (
                "\n\n[yellow]Warnings:[/yellow]\n"
                + "\n".join(f"  • {e}" for e in errors)
                if errors
                else ""
            ),
            title="Summary",
            border_style="green" if not errors else "yellow",
        )
    )

    return project_id
