from rich.console import Console

from .pipeline import VideoPipeline

console = Console()


def render(
    project_id: str,
):
    VideoPipeline().run(project_id)

    console.print(
        "[green]✓ Video rendered[/green]"
    )