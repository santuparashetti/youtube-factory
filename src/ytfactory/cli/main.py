import typer

from ytfactory.create.cli import create
from ytfactory.doctor.cli import doctor
from ytfactory.research.cli import research
from ytfactory.import_script.cli import import_script
from ytfactory.scenes.cli import plan_scenes
from ytfactory.images.cli import generate_images
from ytfactory.voice.cli import generate_voice
from ytfactory.captions.cli import generate_captions
from ytfactory.video.cli import render
from ytfactory.build.cli import build

app = typer.Typer(
    help="YouTube Factory CLI",
    no_args_is_help=True,
)

app.command()(doctor)
app.command()(create)
app.command()(research)
app.command(name="import-script")(import_script)
app.command(name="plan-scenes")(plan_scenes)
app.command(name="generate-images")(generate_images)
app.command(name="generate-voice")(generate_voice)
app.command(name="generate-captions")(generate_captions)
app.command(name="render")(render)
app.command(name="build")(build)


if __name__ == "__main__":
    app()