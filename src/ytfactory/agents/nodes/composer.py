"""Composer node — delegates to ComposerPipeline.

Replaces script_enhancer_node + structural_retention_node in the active
graph. Both remain importable (archived, not deleted) but are no longer
wired into build_graph() — see agents/graph.py.
"""

from __future__ import annotations

from ytfactory.agents.state import VideoState
from ytfactory.composer.pipeline import ComposerPipeline
from ytfactory.composer.selection import run_composer_with_ab_selection
from ytfactory.config.settings import Settings


def composer_node(state: VideoState) -> dict:
    settings = Settings()
    pipeline = ComposerPipeline(settings)
    base_script = state.get("script_md", "")

    # A/B selection is interactive (blocking terminal prompt). It is opt-in via
    # its own wizard question and independent of auto_mode, so a fully-automatic
    # run can still pick between two variants. Off by default → single compose,
    # which keeps non-interactive graph runs from blocking.
    if state.get("ab_script_selection", False):
        composed = run_composer_with_ab_selection(
            pipeline, state["project_id"], base_script_text=base_script
        )
        return {"script_md": composed}

    composed = pipeline.run(state["project_id"], script_text=base_script)
    return {"script_md": composed}
