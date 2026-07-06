from typing import Optional

import typer

from ytfactory.build.cli import build
from ytfactory.captions.cli import generate_captions
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

app = typer.Typer(
    help="YouTube Factory CLI",
    no_args_is_help=False,  # wizard launches instead of help when no args given
)

app.command(name="doctor")(doctor)
app.command(name="create")(create)
app.command(name="research")(research)
app.command(name="import-script")(import_script)
app.command(name="plan-scenes")(plan_scenes)
app.command(name="generate-images")(generate_images)
app.command(name="generate-voice")(generate_voice)
app.command(name="generate-captions")(generate_captions)
app.command(name="render")(render)
app.command(name="compare-video")(compare_video)
app.command(name="review")(review)
app.command(name="remediate")(remediate)
app.command(name="publish")(publish)
app.command(name="build")(build)
app.add_typer(scene_app, name="scene")


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
        False, "--resume", help="Skip stages whose outputs are unchanged (incremental mode)"
    ),
    reuse_assets: bool = typer.Option(
        False, "--reuse-assets", help="Alias for --resume"
    ),
    force_images: bool = typer.Option(False, "--force-images", help="Force image regeneration"),
    force_narration: bool = typer.Option(False, "--force-narration", help="Force voice regeneration"),
    force_subtitles: bool = typer.Option(False, "--force-subtitles", help="Force caption regeneration"),
    force_motion: bool = typer.Option(False, "--force-motion", help="Force motion/video regeneration"),
    force_video: bool = typer.Option(False, "--force-video", help="Force video render"),
    force_bgm: bool = typer.Option(False, "--force-bgm", help="Force BGM re-mix (implies --force-video)"),
    force_publish: bool = typer.Option(False, "--force-publish", help="Force publish package regeneration"),
    scene: Optional[int] = typer.Option(
        None, "--scene", help="Only process this scene index"
    ),
    force_scene: Optional[int] = typer.Option(
        None, "--force-scene", help="Force-regenerate one specific scene (overrides locked state)"
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
