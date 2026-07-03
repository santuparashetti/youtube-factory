from typing import Optional

import typer

from ytfactory.build.cli import build
from ytfactory.captions.cli import generate_captions
from ytfactory.create.cli import create
from ytfactory.doctor.cli import doctor
from ytfactory.images.cli import generate_images
from ytfactory.import_script.cli import import_script
from ytfactory.research.cli import research
from ytfactory.scenes.cli import plan_scenes
from ytfactory.video.cli import render
from ytfactory.voice.cli import generate_voice

app = typer.Typer(
    help="YouTube Factory CLI",
    no_args_is_help=True,
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
app.command(name="build")(build)


@app.command(name="run")
def run(
    topic: str = typer.Argument(..., help="Video topic or title"),
    project_id: Optional[str] = typer.Option(
        None, "--project", "-p", help="Resume an existing project by ID"
    ),
    language: str = typer.Option("en", "--language", "-l", help="BCP-47 language code for TTS"),
    auto: bool = typer.Option(
        False, "--auto", help="Skip human-review gates (fully autonomous)"
    ),
):
    """
    Run the full agentic video production pipeline.

    Research → Script → Scenes → Images + Voice (parallel) → Captions → Video → final.mp4

    Examples:
        ytfactory run "History of Shivaji"
        ytfactory run "History of Shivaji" --auto
        ytfactory run "How Semiconductors Work" --language en --auto
        ytfactory run "Topic" --project existing-project-id
    """
    from ytfactory.agents.runner import run_pipeline

    run_pipeline(topic, project_id=project_id, language=language, auto=auto)


if __name__ == "__main__":
    app()