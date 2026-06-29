from rich.console import Console

from ytfactory.config.settings import Settings

from .models import VoiceRequest
from .pipeline import VoicePipeline

console = Console()


def generate_voice(
    project_id: str,
):
    """Generate narration audio."""

    settings = Settings()

    pipeline = VoicePipeline(settings)

    pipeline.generate(
        VoiceRequest(
            project=project_id,
            scene_id=1,
            text="Hello World",
        )
    )

    console.print(
        "[green]✓ Audio generated[/green]"
    )