import typer
from rich.console import Console

console = Console()


def generate_images(
    project_id: str = typer.Argument(..., help="Project ID"),
) -> None:
    """Generate images from scene plan."""

    console.print(
        f"[yellow]Image generation is under implementation for '{project_id}'.[/yellow]"
    )