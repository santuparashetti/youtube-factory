import typer
from rich.console import Console

from ytfactory.cli.create import create_project

app = typer.Typer(
    help="YouTube Factory CLI",
    no_args_is_help=True,
)

console = Console()


@app.command()
def doctor():
    console.print("[green]✓[/green] YouTube Factory is installed correctly!")


@app.command()
def version():
    console.print("YouTube Factory v0.1.0")


app.command(name="create")(create_project)


if __name__ == "__main__":
    app()