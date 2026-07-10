from typing import Optional

import typer
from rich.console import Console

from .pipeline import BuildPipeline

_STYLE_CHOICES = ["spiritual", "documentary", "history", "educational"]

console = Console()


def build(
    project_id: str = typer.Argument(..., help="Project ID to build"),
    skip_script: bool = typer.Option(False, "--skip-script", help="Skip script enhancement (use script.md as-is)"),
    skip_scenes: bool = typer.Option(False, "--skip-scenes", help="Skip scene planning (use existing scene-plan.json)"),
    skip_images: bool = typer.Option(False, "--skip-images", help="Skip image generation (use existing images)"),
    no_remediate: bool = typer.Option(False, "--no-remediate", help="Skip auto-remediation even if review fails"),
    style: Optional[str] = typer.Option(None, "--style", help=f"Narrative style hint for script enhancement ({', '.join(_STYLE_CHOICES)})"),
    target_minutes: int = typer.Option(7, "--target-minutes", help="Target narration duration in minutes (5-10)"),
    remediation_threshold: float = typer.Option(70.0, "--remediation-threshold", help="Quality score threshold for auto-remediation (0-100)"),
    remediation_retries: int = typer.Option(3, "--remediation-retries", help="Max auto-remediation retry cycles"),
    # ── Incremental / resume flags ─────────────────────────────────────────
    resume: bool = typer.Option(False, "--resume", help="Skip stages whose outputs are unchanged"),
    reuse_assets: bool = typer.Option(False, "--reuse-assets", help="Alias for --resume"),
    force_images: bool = typer.Option(False, "--force-images", help="Force image regeneration"),
    force_narration: bool = typer.Option(False, "--force-narration", help="Force voice regeneration"),
    force_subtitles: bool = typer.Option(False, "--force-subtitles", help="Force caption regeneration"),
    force_video: bool = typer.Option(False, "--force-video", help="Force video render"),
    force_bgm: bool = typer.Option(False, "--force-bgm", help="Force BGM re-mix (implies --force-video)"),
    force_cta: bool = typer.Option(False, "--force-cta", help="Force CTA overlay re-render + downstream"),
    force_publish: bool = typer.Option(False, "--force-publish", help="Force publish package regeneration"),
    scene: Optional[int] = typer.Option(None, "--scene", help="Only process this scene index"),
    force_scene: Optional[int] = typer.Option(None, "--force-scene", help="Force-regenerate one specific scene"),
    debug_incremental: bool = typer.Option(False, "--debug-incremental", help="Print per-asset change debug output"),
):
    """Build the complete video production pipeline end-to-end.

    Runs: scenes → images → voice → captions → video → review →
    [auto-remediation if FAIL] → publish

    \b
    INCREMENTAL MODE (--resume / --force-*)
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    --resume             Skip unchanged stages (SHA-256 checksum detection).
    --force-images       Force image regeneration + all downstream stages.
    --force-narration    Force voice/TTS regeneration + downstream.
    --force-subtitles    Force caption regeneration + downstream.
    --force-video        Force full video re-render + downstream.
    --force-bgm          Force BGM re-mix (implies --force-video).
    --force-publish      Force publish package only.
    --scene N            Scope detection to scene N (combine with --force-*).
    --force-scene N      Force-regenerate scene N entirely.
    --debug-incremental  Print per-stage ✓ reused / ⚠ rebuilt table.

    \b
    EXAMPLES
    ━━━━━━━━
    # Incremental build — only re-run what changed
    ytfactory build abc123 --resume

    # Replace an image and rebuild downstream automatically
    cp better.png workspace/jobs/abc123/images/scene-008.png
    ytfactory build abc123 --resume

    # Force images (video → review → publish follow automatically)
    ytfactory build abc123 --force-images

    # Force-regenerate scene 5 entirely
    ytfactory build abc123 --force-scene 5

    # Force just the video for scene 3
    ytfactory build abc123 --scene 3 --force-video

    # Debug: see exactly which stages ran vs were reused
    ytfactory build abc123 --resume --debug-incremental
    """
    incremental = resume or reuse_assets or any([
        force_images, force_narration, force_subtitles, force_video, force_bgm,
        force_cta, force_publish, scene is not None, force_scene is not None,
    ])

    if incremental:
        from ytfactory.incremental.deps import FORCE_FLAG_TO_STAGE
        force_stages: set[str] = set()
        if force_images:
            force_stages.add(FORCE_FLAG_TO_STAGE["images"])
        if force_narration:
            force_stages.add(FORCE_FLAG_TO_STAGE["narration"])
        if force_subtitles:
            force_stages.add(FORCE_FLAG_TO_STAGE["subtitles"])
        if force_video:
            force_stages.add(FORCE_FLAG_TO_STAGE["video"])
        if force_bgm:
            force_stages.add(FORCE_FLAG_TO_STAGE["bgm"])
        if force_cta:
            force_stages.add(FORCE_FLAG_TO_STAGE["cta"])
        if force_publish:
            force_stages.add(FORCE_FLAG_TO_STAGE["publish"])

        BuildPipeline().run_incremental(
            project_id,
            force_stages=force_stages,
            scene_filter=scene,
            force_scene=force_scene,
            debug=debug_incremental,
        )
    else:
        BuildPipeline().run(
            project_id,
            skip_script=skip_script,
            skip_scenes=skip_scenes,
            skip_images=skip_images,
            auto_remediate=not no_remediate,
            remediation_threshold=remediation_threshold,
            remediation_max_retries=remediation_retries,
            style=style,
            target_minutes=target_minutes,
        )

    console.print("[bold green]✓ Build completed[/bold green]")
