import typer
from rich.console import Console

from ytfactory.config.settings import Settings
from ytfactory.scenes.pipeline import ScenePipeline

console = Console()


def plan_scenes(
    project_id: str = typer.Argument(
        ...,
        help="Project ID",
    ),
):
    """Generate scene plan from imported script."""

    settings = Settings()

    ScenePipeline(settings).run(project_id)

    console.print("[green]✓ Scene plan generated[/green]")