"""Structural Retention Pass node — delegates to StructuralRetentionPipeline.

Runs after script_enhancer, before scene_planner. See
STRUCTURAL_RETENTION_PASS_SPEC.md.
"""

from __future__ import annotations

from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.structural_retention.pipeline import StructuralRetentionPipeline


def structural_retention_node(state: VideoState) -> dict:
    """Reshape the enhanced script's structure for viewer retention.

    No-ops (returns script_md unchanged) when STRUCTURAL_PASS_ENABLED=false.
    """
    settings = Settings()
    pipeline = StructuralRetentionPipeline(settings)

    restructured = pipeline.run(
        state["project_id"],
        script_text=state.get("script_md", ""),
    )
    return {"script_md": restructured}
