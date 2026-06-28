import typer

from ytfactory.create.cli import create
from ytfactory.doctor.cli import doctor
from ytfactory.research.cli import research

app = typer.Typer(
    help="YouTube Factory CLI",
    no_args_is_help=True,
)

app.command()(doctor)
app.command()(create)
app.command()(research)


if __name__ == "__main__":
    app()