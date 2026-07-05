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
from ytfactory.scenes.cli import plan_scenes
from ytfactory.video.cli import render
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
app.command(name="review")(review)
app.command(name="build")(build)


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
):
    """
    Run the full agentic video production pipeline.

    Research → Script → Scenes → Images + Voice (parallel) → Video → final.mp4

    Pass --script to skip research and use your own script directly.
    Pass --no-images to skip image generation (get IMAGE_PROMPTS.md, then place images manually).

    Examples:
        ytfactory run "History of Shivaji" --auto
        ytfactory run "The Silent Force" --script my_script.md --style spiritual --auto
        ytfactory run "The Silent Force" --script my_script.md --style spiritual --target-minutes 8 --auto
        ytfactory run "The Silent Force" --script my_script.md --style spiritual --no-images --auto
        ytfactory run "How Semiconductors Work" --language en --auto
        ytfactory run "Topic" --project existing-project-id
    """
    from ytfactory.agents.runner import run_pipeline

    run_pipeline(
        topic,
        project_id=project_id,
        language=language,
        auto=auto,
        script_path=script,
        style=style,
        no_images=no_images,
        target_minutes=target_minutes,
    )


if __name__ == "__main__":
    app()
