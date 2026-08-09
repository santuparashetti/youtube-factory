"""StitchPipeline — assembles final.mp4 from already-rendered scene clips.

Runs AFTER the pre-stitch review/remediation loop so only clean scene clips
are included in the final composition.  Applies overlays and BGM as part of
the same pass via compose_continuous_video().
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.rule import Rule

from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shared.pipeline_status import get_writer

from .artifacts import video_directory

console = Console()


class StitchPipeline:
    """Compose all scene clips into final.mp4 (with overlays and BGM)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()

    def run(self, project_id: str) -> None:
        from .pipeline import compose_continuous_video

        project_dir = Path(WORKSPACE_DIR) / project_id
        output_dir = video_directory(project_id)

        _w = get_writer()
        if _w:
            _w.stage_start("video_stitch")
        else:
            console.print(Rule("[bold cyan]Final Video Stitch[/bold cyan]"))
            console.print()

        compose_continuous_video(project_dir, output_dir, self._settings)

        final_video = output_dir / "final.mp4"
        if _w:
            _w.stage_complete()
        else:
            console.print(f"[green]✓[/green] Final video: {final_video}\n")

        logger.info("StitchPipeline: final.mp4 written to {}", final_video)
