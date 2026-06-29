from rich.console import Console

from ytfactory.config.settings import Settings
from ytfactory.images.pipeline import ImagePipeline

console = Console()


def generate_images(
    project_id: str,
):
    """Generate images from scene plan."""

    settings = Settings()

    ImagePipeline(settings).run(project_id)

    console.print(
        "[green]✓ Images generated[/green]"
    )