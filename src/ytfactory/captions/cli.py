from rich.console import Console

from .pipeline import CaptionPipeline

console = Console()


def generate_captions(
    project_id: str,
):
    """Generate subtitles."""

    CaptionPipeline().run(project_id)

    console.print(
        "[green]✓ Captions generated[/green]"
    )