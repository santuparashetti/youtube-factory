"""Source refiner node — editorial pass on the base script before composition."""

from __future__ import annotations

from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.source_refiner.pipeline import SourceRefinerPipeline


def source_refiner_node(state: VideoState) -> dict:
    """Run the editorial refinement pass on the base script.

    Reads script_md from state (set by the runner before graph entry),
    applies SOURCE_REFINER_PROMPT (universalise culturally specific references,
    improve clarity/flow), writes refined text back to disk and returns it
    in state so the composer receives clean universal material.
    """
    project_id = state["project_id"]
    settings = Settings()
    pipeline = SourceRefinerPipeline(settings)
    refined = pipeline.run(project_id)
    return {"script_md": refined}
