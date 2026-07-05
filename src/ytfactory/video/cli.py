import json
from pathlib import Path

from rich.console import Console

from .pipeline import VideoPipeline

console = Console()


def render(
    project_id: str,
):
    VideoPipeline().run(project_id)

    console.print("[green]✓ Video rendered[/green]")


def compare_video(
    original: str,
    optimised: str,
    json_out: str = "",
) -> None:
    """Compare two video files and print a quality/size report."""
    from .reporter import compare_videos

    report = compare_videos(Path(original), Path(optimised))
    console.print(report.to_markdown())

    if json_out:
        out = Path(json_out)
        out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        console.print(f"\n[dim]JSON report written to {out}[/dim]")
