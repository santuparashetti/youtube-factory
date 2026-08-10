"""Beats extractor node — step 0: identifies protected beats before source refinement."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from rich.console import Console

from ytfactory.agents.state import VideoState
from ytfactory.beats_extractor.pipeline import BeatsExtractorPipeline
from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()


def beats_extractor_node(state: VideoState) -> dict:
    """Extract protected narrative beats from the base script.

    Reads the source script from state (YT ingestion path sets script_md after
    translate) or from disk (script_path / import-script path). Must run before
    source_refiner so beats are available for every downstream prompt.
    """
    project_id = state["project_id"]
    script_dir = Path(WORKSPACE_DIR) / project_id / "script"

    source_script = state.get("script_md", "")
    if not source_script:
        script_file = script_dir / "script.md"
        if script_file.exists():
            source_script = script_file.read_text(encoding="utf-8")

    if not source_script:
        raise FileNotFoundError(
            f"BeatsExtractor: no source script found in state or at "
            f"{script_dir / 'script.md'}. Run import-script first."
        )

    settings = Settings()
    pipeline = BeatsExtractorPipeline(settings)
    beats = pipeline.run(project_id, source_script)

    logger.info("BeatsExtractor node: {} beats stored in state", len(beats))
    return {"beats": beats}
