from rich.console import Console

from .pipeline import BuildPipeline

console = Console()


def build(
    project_id: str,
    skip_scenes: bool = False,
    skip_images: bool = False,
):
    """Build complete video."""

    BuildPipeline().run(project_id, skip_scenes=skip_scenes, skip_images=skip_images)

    console.print(
        "[bold green]✓ Build completed[/bold green]"
    )