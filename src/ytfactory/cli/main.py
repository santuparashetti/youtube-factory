import typer
from rich.console import Console

app = typer.Typer(
    help="YouTube Factory CLI",
    no_args_is_help=True,
)

console = Console()


@app.command()
def doctor():
    """Check the local environment."""
    console.print("[green]✓[/green] YouTube Factory is installed correctly!")


@app.command()
def version():
    """Show version."""
    console.print("YouTube Factory v0.1.0")

if __name__ == "__main__":
    app()