"""Composer node — delegates to ComposerPipeline.

Replaces script_enhancer_node + structural_retention_node in the active
graph. Both remain importable (archived, not deleted) but are no longer
wired into build_graph() — see agents/graph.py.
"""

from __future__ import annotations

from ytfactory.agents.state import VideoState
from ytfactory.composer.pipeline import ComposerPipeline
from ytfactory.config.settings import Settings


def composer_node(state: VideoState) -> dict:
    settings = Settings()
    pipeline = ComposerPipeline(settings)
    composed = pipeline.run(state["project_id"], script_text=state.get("script_md", ""))
    return {"script_md": composed}
