"""CLI commands for the Shorts pipeline (Phase 1A + 1B)."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from ytfactory.config.settings import Settings

console = Console()


def generate_shorts(
    project_id: str = typer.Argument(help="Project ID (directory name in workspace/jobs/)"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Regenerate all artifacts even if they already exist.",
    ),
) -> None:
    """Generate two curiosity-driven YouTube Shorts from an existing long-form script.

    Runs S1 (opportunity extraction) → S2 (script generation) × 2 →
    S2b (validation) × 2 → S3 (scene planning) → S4 (image prompts).
    """
    from ytfactory.shorts.pipeline import ShortsPipeline

    try:
        ShortsPipeline(Settings()).run(project_id, force=force)
    except FileNotFoundError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]✗ Shorts generation failed: {exc}[/red]")
        raise typer.Exit(1)


def shorts_extract(
    project_id: str = typer.Argument(help="Project ID"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Regenerate even if opportunities.json already exists.",
    ),
) -> None:
    """S1 only: extract Short opportunities from the long-form script.

    Useful for inspecting opportunities before committing to full generation.
    """
    from ytfactory.shorts.pipeline import ShortsPipeline

    try:
        ShortsPipeline(Settings()).run_extract_only(project_id, force=force)
    except FileNotFoundError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1)


def generate_shorts_video(
    project_id: str = typer.Argument(help="Project ID (directory name in workspace/jobs/)"),
    short_id: Optional[str] = typer.Option(
        None,
        "--short-id",
        help="Run only the specified short (e.g. short-001). Default: run all shorts.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Regenerate all media stages even if outputs already exist.",
    ),
) -> None:
    """Phase 1B: generate TTS, subtitles, and render video for user-supplied images.

    After dropping PNG images into shorts/<short_id>/images/ (from Phase 1A
    image-prompts.json), run this command to produce a finished final.mp4.

    Pipeline per Short:
        images (user-supplied) → TTS → subtitles → render → assemble → BGM
    """
    from ytfactory.shorts.media_pipeline import ShortsMediaPipeline

    try:
        ShortsMediaPipeline(Settings()).run_all(
            project_id,
            short_id_filter=short_id,
            force=force,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]✗ Shorts video generation failed: {exc}[/red]")
        raise typer.Exit(1)


def shorts_plan(
    project_id: str = typer.Argument(help="Project ID"),
    short_id: str = typer.Argument(help="Short ID, e.g. short-001"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Regenerate even if scene-plan.json already exists.",
    ),
) -> None:
    """S3 only: re-run scene planning for one valid Short.

    Requires an existing validated short-script.json.
    """
    from ytfactory.shorts.pipeline import ShortsPipeline

    try:
        ShortsPipeline(Settings()).run_plan_only(project_id, short_id, force=force)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1)
