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
from ytfactory.shared.pipeline_status import PipelineAbort

console = Console()


def run_pipeline(
    topic: str,
    *,
    project_id: str | None = None,
    language: str = "en",
    auto: bool = False,
    script_path: str | None = None,
    source_url: str | None = None,
    style: str | None = None,
    no_images: bool = False,
    target_minutes: int = 8,
    incremental: bool = False,
    force_stages: set[str] | None = None,
    scene_filter: int | None = None,
    force_scene: int | None = None,
    pipeline_mode: str = "default",
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
        source_url:  A YouTube URL. When provided, the ingestion chain
                     (acquire_audio → transcribe → translate → human review)
                     produces the base script instead of a script file or
                     AI research. Mutually exclusive with script_path.
        style:       Visual style hint — "spiritual", "documentary", etc.
        no_images:   Skip image generation entirely. Use IMAGE_PROMPTS.md to
                     generate images manually, then re-run for video.
        target_minutes: Target narration duration in minutes (1-10).
        incremental: Skip unchanged stages (incremental mode).
        force_stages: Stages to forcibly rebuild.
        scene_filter: Only process this scene index.
        force_scene:  Force-regenerate one specific scene.
        pipeline_mode: "default" | "prep_only" | "resume".
                       prep_only: run Phase 1, halt after voice/captions with manifest.
                       resume: validate images, then run remaining stages.

    Returns:
        The project_id of the produced video.
    """
    # ── Incremental / resume mode ─────────────────────────────────────────
    # When --resume (or force-* flags) are requested with an existing project,
    # route to BuildPipeline's incremental engine instead of re-running the
    # full agentic graph.  A fresh `ytfactory run <topic>` always uses the
    # agentic graph regardless of flags.
    if (incremental or force_stages) and project_id is not None:
        return _run_incremental(
            project_id=project_id,
            force_stages=force_stages or set(),
            scene_filter=scene_filter,
            force_scene=force_scene,
        )

    # ── Two-phase mode ─────────────────────────────────────────────────────
    if pipeline_mode == "resume" and project_id is None:
        raise ValueError("--phase=resume requires --project <id>")

    if script_path and source_url:
        raise ValueError("script_path and source_url are mutually exclusive — pick one source")

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

    if source_url:
        console.print(f"[green]✓[/green] YouTube source: [bold]{source_url}[/bold]")
        console.print(
            "  [dim]Ingestion chain will run: acquire audio → transcribe → "
            "translate → review[/dim]"
        )

    if no_images or pipeline_mode == "prep_only":
        console.print(
            "[yellow]⚡ Image generation skipped[/yellow]: "
            "Generate images from [bold]images/IMAGE_PROMPTS.md[/bold] and re-run."
        )

    console.print()

    # ── Build initial state ───────────────────────────────────────────────
    skip_images = no_images or pipeline_mode == "prep_only"
    skip_thumbnail = pipeline_mode == "resume"

    initial_state: VideoState = {
        "project_id": project_id,
        "topic": topic,
        "language": language,
        "topic_category": "other",
        "style": style,
        "target_minutes": max(1, min(10, target_minutes)),
        "auto_mode": auto,
        "skip_images": skip_images,
        "skip_thumbnail": skip_thumbnail,
        "script_md": script_md,
        "source_url": source_url,
        "scene_plan": [],
        "image_paths": {},
        "audio_paths": {},
        "srt_paths": {},
        "scene_video_paths": {},
        "stage_errors": [],
    }

    # ── Two-phase: Phase 2 validation ────────────────────────────────────
    if pipeline_mode == "resume":
        from ytfactory.two_phase.pipeline import TwoPhasePipeline

        missing = TwoPhasePipeline()._validate_images(project_id)
        if missing:
            console.print(
                f"[red]✗ Phase 2 validation failed — {len(missing)} missing image(s):[/red]"
            )
            for scene_id, filename in missing:
                console.print(f"  [red]•[/red] Scene {scene_id}: {filename}")
            console.print(
                "\n[yellow]Place the missing images in the images folder and re-run.[/yellow]"
            )
            raise RuntimeError(
                f"Phase 2 validation failed: {len(missing)} missing images."
            )
        console.print("[green]✓[/green] All expected images present\n")

    # ── Run the graph ─────────────────────────────────────────────────────
    config = {"configurable": {"thread_id": project_id}}

    try:
        final_state = graph.invoke(initial_state, config=config)
    except PipelineAbort as exc:
        console.print()
        console.print(Rule("[bold red]PIPELINE ABORTED[/bold red]"))
        console.print()
        console.print(f"[bold]Stage:[/bold] {exc.stage}")
        console.print(f"[bold]Reason:[/bold] {exc.reason}")
        console.print()
        console.print("[bold]Downstream stages skipped:[/bold]")
        for name in [
            "Scene Planning",
            "Image Generation",
            "Vision QA",
            "TTS",
            "Rendering",
            "Publishing",
        ]:
            console.print(f"  [yellow]✓ {name}[/yellow]")
        console.print()
        return project_id

    # ── Two-phase: Phase 1 post-processing ───────────────────────────────
    if pipeline_mode == "prep_only":
        from ytfactory.two_phase.pipeline import TwoPhasePipeline

        two_phase = TwoPhasePipeline()
        manifest_path = two_phase._write_image_prompts_manifest(project_id)
        two_phase._write_phase1_report(project_id, manifest_path)

        console.print()
        console.print(Rule("[bold green]Phase 1 Complete[/bold green]"))
        console.print(
            Panel(
                f"[bold]Project:[/bold] {project_id}\n"
                f"[bold]Image prompts manifest:[/bold] {manifest_path}\n"
                f"[bold]Phase 1 report:[/bold] {Path(WORKSPACE_DIR) / project_id / 'phase1_report.md'}\n\n"
                "[yellow]Generate images externally, place them in the images folder, "
                "then run Phase 2 to continue.[/yellow]",
                title="Phase 1 Stop",
                border_style="green",
            )
        )
        console.print()
        return project_id

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


def _run_incremental(
    project_id: str,
    force_stages: set[str],
    scene_filter: int | None,
    force_scene: int | None,
) -> str:
    """Route incremental / force-rebuild requests through BuildPipeline."""
    from ytfactory.build.pipeline import BuildPipeline

    console.print(Rule("[bold cyan]YouTube Factory — Incremental Build[/bold cyan]"))
    console.print(f"[cyan]Project:[/cyan] [bold]{project_id}[/bold]")

    all_force = set(force_stages)
    if force_scene is not None:
        # force-scene bypasses locked state for one specific scene
        all_force |= {"images", "voice", "captions", "video"}

    BuildPipeline().run_incremental(
        project_id,
        force_stages=all_force,
        scene_filter=scene_filter or force_scene,
        force_scene=force_scene,
    )
    console.print("[bold green]✓ Incremental build complete[/bold green]")
    return project_id
