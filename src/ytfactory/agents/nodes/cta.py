"""CTA node — inserts the CTA Overlay stage into the agentic pipeline."""

from __future__ import annotations

from loguru import logger

from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.cta.pipeline import CTABlockedError, CTAPipeline

_settings = Settings()


def cta_node(state: VideoState) -> dict:
    """Apply CTA overlay to the rendered video.

    Non-fatal: a CTABlockedError is captured in stage_errors so the pipeline
    can still reach quality_review and publish.
    """
    project_id = state["project_id"]
    try:
        CTAPipeline(settings=_settings).run(project_id)
    except CTABlockedError as exc:
        logger.warning("CTA Overlay blocked: {}", exc)
        return {"stage_errors": [f"[cta] {exc}"]}
    return {}
