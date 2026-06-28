import typer
from rich.console import Console

from ytfactory.create.pipeline import CreatePipeline

console = Console()


def create(title: str):
    """Create a new project."""

    project = CreatePipeline().run(title)

    console.print()

    console.print(
        f"[green]✓[/green] Project created: {project.id}"
    )

    console.print(
        f"workspace/jobs/{project.id}"
    )