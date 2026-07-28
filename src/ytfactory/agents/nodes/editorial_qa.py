"""Editorial QA node — delegates to EditorialQAPipeline.

Runs after structural_retention, before scene_planner. Never touches
script_md — flags only, per EDITORIAL_QA_STAGE_SPEC.md's FLAG-NEVER-GATE rule.
"""

from __future__ import annotations

from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.editorial_qa.pipeline import EditorialQAPipeline


def editorial_qa_node(state: VideoState) -> dict:
    settings = Settings()
    EditorialQAPipeline(settings).run(state["project_id"], script_text=state.get("script_md"))
    return {}
