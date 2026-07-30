from rich.console import Console

from .pipeline import CaptionPipeline
from .transcript import build_transcript

console = Console()


def generate_captions(
    project_id: str,
):
    """Generate subtitles."""

    CaptionPipeline().run(project_id)

    console.print("[green]✓ Captions generated[/green]")


def transcript(
    project_id: str,
):
    """Rebuild subtitles/transcript.txt from existing per-scene .srt files."""

    path = build_transcript(project_id)

    console.print(f"[green]✓ Transcript written to {path}[/green]")
