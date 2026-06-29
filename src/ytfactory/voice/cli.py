from rich.console import Console

from ytfactory.config.settings import Settings

from .pipeline import VoicePipeline

console = Console()


def generate_voice(
    project_id: str,
):
    """Generate narration audio."""

    settings = Settings()

    VoicePipeline(settings).run(project_id)

    console.print(
        "[green]✓ Voice generated[/green]"
    )