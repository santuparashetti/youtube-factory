from __future__ import annotations

import typer

from .models import VoiceRequest
from .pipeline import VoicePipeline

app = typer.Typer(help="Generate narration audio.")


@app.command()
def generate(
    project: str,
) -> None:
    pipeline = VoicePipeline()

    pipeline.generate(
        VoiceRequest(
            project=project,
            scene_id=1,
            text="Hello World",
        )
    )

    typer.echo("Audio generation completed.")