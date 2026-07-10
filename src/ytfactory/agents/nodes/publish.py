"""Publish node — Publishing & Growth Engine V1 in the agentic pipeline."""

from __future__ import annotations

from rich.console import Console

from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.publish.config import PublishConfig
from ytfactory.publish.pipeline import PublishPipeline

console = Console()

_settings = Settings()


def publish_node(state: VideoState) -> dict:
    """
    Run the Publishing & Growth Engine as the final step of the agentic pipeline.

    Produces the complete YouTube upload package under
    workspace/jobs/<project_id>/publish/ and marks the publish stage complete.
    """
    project_id = state["project_id"]

    # Respect skip_thumbnail if the user ran with --no-images
    skip_thumbnail = bool(state.get("skip_images", False))
    config = PublishConfig(skip_thumbnail=skip_thumbnail)

    package = PublishPipeline(config=config, settings=_settings).run(project_id)

    errors = [f"[publish] {e}" for e in package.validation_errors]

    return {
        "stage_errors": errors,
    }
