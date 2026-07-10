from typing import Optional

import typer
from rich.console import Console

from ytfactory.benchmark.cli import benchmark_app
from ytfactory.build.cli import build
from ytfactory.captions.cli import generate_captions
from ytfactory.cta.cli import overlay_cta
from ytfactory.create.cli import create
from ytfactory.doctor.cli import doctor
from ytfactory.images.cli import generate_images
from ytfactory.import_script.cli import import_script
from ytfactory.research.cli import research
from ytfactory.review.cli import review
from ytfactory.publish.cli import publish
from ytfactory.review.remediation.cli import remediate
from ytfactory.scene.cli import scene_app
from ytfactory.scenes.cli import plan_scenes
from ytfactory.video.cli import compare_video, render
from ytfactory.voice.cli import generate_voice

_console = Console()

app = typer.Typer(
    help="YouTube Factory CLI",
    no_args_is_help=False,  # wizard launches instead of help when no args given
)

app.command(name="doctor")(doctor)


@app.command(name="setup")
def setup(
    force: bool = typer.Option(
        False, "--force", help="Re-run even if already bootstrapped"
    ),
) -> None:
    """First-run bootstrap: workspace, config, providers, models. Idempotent."""
    from ytfactory.bootstrap.engine import BootstrapEngine
    from ytfactory.bootstrap.models import CheckStatus
    from rich.table import Table

    engine = BootstrapEngine()
    _console.print("\n[bold]YouTube Factory — Setup[/bold]\n")
    result = engine.setup(force=force)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Status", width=8)
    table.add_column("Check", min_width=30)
    table.add_column("Message")

    _STATUS = {
        CheckStatus.OK: "[green]✓[/green]",
        CheckStatus.WARNING: "[yellow]⚠[/yellow]",
        CheckStatus.ERROR: "[red]✗[/red]",
        CheckStatus.REPAIRED: "[cyan]↻[/cyan]",
        CheckStatus.SKIPPED: "[dim]−[/dim]",
    }
    for check in result.checks:
        table.add_row(_STATUS.get(check.status, "?"), check.name, check.message)
    _console.print(table)

    if result.repairs:
        _console.print(f"\n[cyan]Auto-repaired {len(result.repairs)} issue(s):[/cyan]")
        for r in result.repairs:
            _console.print(f"  ↻ {r}")

    if result.errors:
        _console.print(
            f"\n[red]✗ Setup completed with {len(result.errors)} error(s)[/red]"
        )
        for e in result.errors:
            _console.print(f"  ✗ {e.name}: {e.message}")
            if e.detail:
                _console.print(f"    {e.detail}")
        raise typer.Exit(1)
    elif result.warnings:
        _console.print(
            f"\n[yellow]⚠ Setup complete — {len(result.warnings)} warning(s)[/yellow]"
        )
    else:
        _console.print("\n[green]✓ Setup complete — environment ready[/green]")


@app.command(name="validate")
def validate() -> None:
    """Validate configuration and provider connectivity (lightweight, no setup)."""
    from ytfactory.bootstrap.engine import BootstrapEngine

    engine = BootstrapEngine()
    _console.print("\n[bold]YouTube Factory — Validate[/bold]\n")
    result = engine.validate()

    for check in result.checks:
        icon = {
            "ok": "✓",
            "warning": "⚠",
            "error": "✗",
            "repaired": "↻",
            "skipped": "−",
        }.get(check.status.value, "?")
        color = {
            "ok": "green",
            "warning": "yellow",
            "error": "red",
            "repaired": "cyan",
            "skipped": "dim",
        }.get(check.status.value, "white")
        _console.print(f"  [{color}]{icon}[/{color}] {check.name}: {check.message}")
        if check.detail:
            _console.print(f"    [dim]{check.detail}[/dim]")

    if result.errors:
        _console.print(f"\n[red]✗ {len(result.errors)} validation error(s)[/red]")
        raise typer.Exit(1)
    elif result.warnings:
        _console.print(f"\n[yellow]⚠ {len(result.warnings)} warning(s)[/yellow]")
    else:
        _console.print("\n[green]✓ Configuration valid[/green]")


@app.command(name="repair")
def repair() -> None:
    """Self-healing: fix missing directories, permissions, broken symlinks."""
    from ytfactory.bootstrap.engine import BootstrapEngine

    engine = BootstrapEngine()
    _console.print("\n[bold]YouTube Factory — Repair[/bold]\n")
    result = engine.repair()

    if not result.repairs and not result.errors:
        _console.print("[green]✓ Nothing to repair — environment is healthy[/green]")
        return

    for check in result.checks:
        if check.repaired:
            _console.print(f"  [cyan]↻ {check.message}[/cyan]")
        elif check.status.value == "error":
            _console.print(f"  [red]✗ {check.name}: {check.message}[/red]")
            if check.detail:
                _console.print(f"    {check.detail}")

    if result.repairs:
        _console.print(f"\n[cyan]Repaired {len(result.repairs)} issue(s)[/cyan]")
    if result.errors:
        _console.print(
            f"\n[red]✗ {len(result.errors)} issue(s) could not be auto-repaired — manual intervention needed[/red]"
        )
        raise typer.Exit(1)


@app.command(name="clean")
def clean(
    temp: bool = typer.Option(True, "--temp/--no-temp", help="Clean temp/ directory"),
    logs: bool = typer.Option(False, "--logs", help="Also clean logs/ directory"),
    cache: bool = typer.Option(
        False, "--cache", help="Also clean cache/ directory (keeps models)"
    ),
) -> None:
    """Clean temporary files. Safe — never touches workspace/jobs or models."""
    import shutil
    from pathlib import Path

    root = Path.cwd()
    cleaned: list[str] = []

    def _clean_dir(rel: str) -> None:
        target = root / rel
        if target.exists():
            shutil.rmtree(target)
            target.mkdir(parents=True, exist_ok=True)
            cleaned.append(rel)

    _console.print("\n[bold]YouTube Factory — Clean[/bold]\n")

    if temp:
        _clean_dir("temp")
    if logs:
        _clean_dir("logs")
    if cache:
        _clean_dir("cache")

    if cleaned:
        _console.print(f"[green]✓ Cleaned: {', '.join(cleaned)}[/green]")
    else:
        _console.print("[dim]Nothing to clean (use --logs or --cache for more)[/dim]")


@app.command(name="reset")
def reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    workspace: bool = typer.Option(
        False, "--workspace", help="Also delete workspace/jobs (DESTRUCTIVE)"
    ),
) -> None:
    """Reset bootstrap state. Re-run 'ytfactory setup' after this."""
    import shutil
    from pathlib import Path

    root = Path.cwd()

    if not yes:
        msg = "This will delete bootstrap-manifest.json and environment-report.json."
        if workspace:
            msg += " [red]Also deletes workspace/jobs/ — all project data will be lost![/red]"
        _console.print(f"\n[yellow]{msg}[/yellow]")
        confirm = typer.confirm("Continue?", default=False)
        if not confirm:
            _console.print("Reset cancelled.")
            raise typer.Exit(0)

    removed: list[str] = []
    for fname in ["bootstrap-manifest.json", "environment-report.json"]:
        p = root / fname
        if p.exists():
            p.unlink()
            removed.append(fname)

    if workspace:
        jobs = root / "workspace" / "jobs"
        if jobs.exists():
            shutil.rmtree(jobs)
            jobs.mkdir(parents=True, exist_ok=True)
            removed.append("workspace/jobs/")

    if removed:
        _console.print(f"[yellow]Removed: {', '.join(removed)}[/yellow]")
        _console.print("Run [bold]ytfactory setup[/bold] to re-bootstrap.")
    else:
        _console.print("[dim]Nothing to reset.[/dim]")


@app.command(name="update")
def update() -> None:
    """Re-validate environment after code/dependency updates."""
    from ytfactory.bootstrap.engine import BootstrapEngine

    engine = BootstrapEngine()
    _console.print("\n[bold]YouTube Factory — Update[/bold]\n")

    result = engine.setup(force=True)

    if result.success:
        _console.print("[green]✓ Environment re-validated and manifest updated[/green]")
    else:
        _console.print(
            f"[red]✗ Re-validation found {len(result.errors)} error(s)[/red]"
        )
        raise typer.Exit(1)


@app.command(name="version")
def version() -> None:
    """Print version info and bootstrap manifest."""
    from ytfactory.bootstrap.engine import BootstrapEngine

    engine = BootstrapEngine()
    info = engine.version_info()

    current = info["current"]
    manifest = info["manifest"]

    _console.print(
        f"\n[bold]YouTube Factory[/bold]  v{current.get('project_version', '?')}"
    )
    _console.print(f"  Python:   {current.get('python_version', '?')}")
    _console.print(f"  FFmpeg:   {current.get('ffmpeg_version', '?')[:60]}")
    _console.print(f"  Torch:    {current.get('torch_version', '?')}")
    providers = current.get("providers", {})
    if providers:
        _console.print(f"  LLM:      {providers.get('llm', '?')}")
        _console.print(f"  Search:   {providers.get('search', '?')}")
        _console.print(f"  Image:    {providers.get('image', '?')}")
        _console.print(f"  TTS:      {providers.get('tts', '?')}")

    if manifest:
        _console.print(
            f"\n  Bootstrap: v{manifest.get('bootstrap_version', '?')} "
            f"({'current' if info['manifest_current'] else 'outdated'})"
        )
        _console.print(
            f"  Validated: {manifest.get('validated_at', '?')[:19].replace('T', ' ')}"
        )
    else:
        _console.print("\n  [dim]No bootstrap manifest — run 'ytfactory setup'[/dim]")


app.command(name="create")(create)
app.command(name="research")(research)
app.command(name="import-script")(import_script)
app.command(name="plan-scenes")(plan_scenes)
app.command(name="generate-images")(generate_images)
app.command(name="generate-voice")(generate_voice)
app.command(name="generate-captions")(generate_captions)
app.command(name="render")(render)
app.command(name="compare-video")(compare_video)
app.command(name="overlay-cta")(overlay_cta)
app.command(name="review")(review)
app.command(name="remediate")(remediate)
app.command(name="publish")(publish)
app.command(name="build")(build)
app.add_typer(scene_app, name="scene")
app.add_typer(benchmark_app, name="benchmark")


@app.command(name="mix-bgm")
def mix_bgm(
    project_id: str = typer.Argument(..., help="Project ID to apply BGM to"),
    video: Optional[str] = typer.Option(
        None, "--video", "-v", help="Path to video file (default: video/final.mp4)"
    ),
) -> None:
    """Re-apply background music to an already-rendered final.mp4.

    This is the standalone BGM re-apply path. BGM is normally embedded
    automatically during `ytfactory render` / `ytfactory build` via the
    video pipeline. Use this command only when BGM was disabled during the
    original render, or after adding new tracks to the BGM library.
    """
    from pathlib import Path
    from ytfactory.bgm.pipeline import BGMPipeline

    pipeline = BGMPipeline()
    video_path = Path(video) if video else None
    result = pipeline.run(project_id, video_path=video_path)
    if result is None:
        _console.print("[yellow]BGM skipped (disabled or no matching tracks).[/yellow]")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """YouTube Factory — run without arguments to open the interactive wizard."""
    if ctx.invoked_subcommand is None:
        from ytfactory.cli.wizard import run_wizard

        run_wizard()


@app.command(name="run")
def run(
    topic: str = typer.Argument(..., help="Video topic or title"),
    project_id: Optional[str] = typer.Option(
        None, "--project", "-p", help="Resume an existing project by ID"
    ),
    language: str = typer.Option(
        "en", "--language", "-l", help="BCP-47 language code for TTS"
    ),
    auto: bool = typer.Option(
        False, "--auto", help="Skip human-review gates (fully autonomous)"
    ),
    script: Optional[str] = typer.Option(
        None,
        "--script",
        "-s",
        help="Path to a pre-written script file. Skips research and script-writer stages.",
    ),
    style: Optional[str] = typer.Option(
        None,
        "--style",
        help="Visual style: spiritual | documentary | educational | history (affects image prompts)",
    ),
    no_images: bool = typer.Option(
        False,
        "--no-images",
        help="Skip image generation. Review IMAGE_PROMPTS.md, generate images manually, then re-run.",
    ),
    target_minutes: int = typer.Option(
        7,
        "--target-minutes",
        "-t",
        help="Target narration duration in minutes (5-10). Drives script enhancer word count.",
    ),
    # ── Incremental / resume flags ────────────────────────────────────────────
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Skip stages whose outputs are unchanged (incremental mode)",
    ),
    reuse_assets: bool = typer.Option(
        False, "--reuse-assets", help="Alias for --resume"
    ),
    force_images: bool = typer.Option(
        False, "--force-images", help="Force image regeneration"
    ),
    force_narration: bool = typer.Option(
        False, "--force-narration", help="Force voice regeneration"
    ),
    force_subtitles: bool = typer.Option(
        False, "--force-subtitles", help="Force caption regeneration"
    ),
    force_motion: bool = typer.Option(
        False, "--force-motion", help="Force motion/video regeneration"
    ),
    force_video: bool = typer.Option(False, "--force-video", help="Force video render"),
    force_bgm: bool = typer.Option(
        False, "--force-bgm", help="Force BGM re-mix (implies --force-video)"
    ),
    force_publish: bool = typer.Option(
        False, "--force-publish", help="Force publish package regeneration"
    ),
    scene: Optional[int] = typer.Option(
        None, "--scene", help="Only process this scene index"
    ),
    force_scene: Optional[int] = typer.Option(
        None,
        "--force-scene",
        help="Force-regenerate one specific scene (overrides locked state)",
    ),
):
    """Run the full agentic video production pipeline.

    Research → Script → Scenes → Images + Voice (parallel) → Video → final.mp4

    Pass --script to skip research and use your own script directly.
    Pass --no-images to skip image generation; place images manually then re-run.
    Pass --resume with --project for incremental builds — only changed stages re-run.

    \b
    INCREMENTAL MODE (requires --project)
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    --resume             Skip unchanged stages (SHA-256 checksum detection).
    --reuse-assets       Alias for --resume.
    --force-images       Force image regeneration + all downstream stages.
    --force-narration    Force voice/TTS regeneration + downstream.
    --force-subtitles    Force caption regeneration + downstream.
    --force-motion       Force motion re-planning + video render.
    --force-video        Force full video re-render + downstream.
    --force-bgm          Force BGM re-mix (implies --force-video).
    --force-publish      Force publish package only.
    --scene N            Scope detection to scene N (combine with --force-*).
    --force-scene N      Force-regenerate scene N entirely (overrides lock).

    \b
    EXAMPLES
    ━━━━━━━━
    # Full pipeline from scratch
    ytfactory run "History of Shivaji" --auto

    # Pre-written script, spiritual style, 8-minute target
    ytfactory run "The Silent Force" --script script.md --style spiritual --target-minutes 8 --auto

    # Skip images — place manually later, then re-run
    ytfactory run "Topic" --script script.md --no-images --auto

    # Resume a failed run (agentic graph checkpointing)
    ytfactory run "Topic" --project abc123 --auto

    # Incremental: only rebuild what changed
    ytfactory run "Topic" --project abc123 --resume

    # Replace one image, then auto-detect and rebuild downstream
    cp better.png workspace/jobs/abc123/images/scene-008.png
    ytfactory run "Topic" --project abc123 --resume

    # Force images only
    ytfactory run "Topic" --project abc123 --force-images

    # Force-regenerate scene 8 entirely
    ytfactory run "Topic" --project abc123 --force-scene 8

    # Force just the video for scene 3
    ytfactory run "Topic" --project abc123 --scene 3 --force-video
    """
    from ytfactory.agents.runner import run_pipeline
    from ytfactory.incremental.deps import FORCE_FLAG_TO_STAGE

    force_stages: set[str] = set()
    if force_images:
        force_stages.add(FORCE_FLAG_TO_STAGE["images"])
    if force_narration:
        force_stages.add(FORCE_FLAG_TO_STAGE["narration"])
    if force_subtitles:
        force_stages.add(FORCE_FLAG_TO_STAGE["subtitles"])
    if force_motion or force_video:
        force_stages.add(FORCE_FLAG_TO_STAGE["video"])
    if force_bgm:
        force_stages.add(FORCE_FLAG_TO_STAGE["bgm"])
    if force_publish:
        force_stages.add(FORCE_FLAG_TO_STAGE["publish"])

    run_pipeline(
        topic,
        project_id=project_id,
        language=language,
        auto=auto,
        script_path=script,
        style=style,
        no_images=no_images,
        target_minutes=target_minutes,
        incremental=resume or reuse_assets,
        force_stages=force_stages if force_stages else None,
        scene_filter=scene,
        force_scene=force_scene,
    )


if __name__ == "__main__":
    app()
