"""Script Enhancer node — delegates to ScriptEnhancerPipeline."""

from __future__ import annotations

from ytfactory.agents.prompts.script_writer import TARGET_IDEAL_MINUTES
from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.script_enhancer.pipeline import ScriptEnhancerPipeline


def script_enhancer_node(state: VideoState) -> dict:
    """Expand the user-provided script to meet the target duration.

    Delegates all LLM interaction, file I/O, and console output to
    ScriptEnhancerPipeline so the same logic is reusable from BuildPipeline.

    When an original source transcript is available in state, the enhancer
    analyzes and compares it against the generated script before enhancing.
    """
    settings = Settings()
    pipeline = ScriptEnhancerPipeline(settings)

    enhanced = pipeline.run(
        state["project_id"],
        topic=state["topic"],
        style=state.get("style"),
        target_minutes=int(state.get("target_minutes", TARGET_IDEAL_MINUTES)),
        script_text=state.get("script_md", ""),
        original_source_transcript=state.get("original_source_transcript"),
        enhancement_instructions=state.get("enhancement_instructions"),
    )
    return {"script_md": enhanced}
