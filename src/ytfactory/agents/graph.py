"""
LangGraph agentic pipeline graph definition.

Flow:
  research_agent
    → script_writer
      → [human_review_script]
        → scene_planner
          → [human_review_scenes]
            → generate_scene_assets (parallel fan-out, one per scene)
              → video_renderer
                → video_concatenator
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ytfactory.agents.nodes.human_review import (
    human_review_scenes_node,
    human_review_script_node,
)
from ytfactory.agents.nodes.research import research_node
from ytfactory.agents.nodes.scene_assets import generate_scene_assets
from ytfactory.agents.nodes.scene_planner import scene_planner_node
from ytfactory.agents.nodes.script_enhancer import script_enhancer_node
from ytfactory.agents.nodes.script_writer import script_writer_node
from ytfactory.agents.nodes.video_concatenator import video_concatenator_node
from ytfactory.agents.nodes.video_renderer import video_renderer_node
from ytfactory.agents.state import VideoState


def _dispatch_scenes(state: VideoState) -> list[Send]:
    """Fan out: one generate_scene_assets invocation per scene."""
    return [
        Send("generate_scene_assets", {**state, "current_scene": scene})
        for scene in state.get("scene_plan", [])
    ]


def _route_entry(state: VideoState) -> str:
    """Route to script_enhancer when a user script is provided; else start research."""
    if state.get("script_md"):
        return "script_enhancer"
    return "research_agent"


def _route_after_assets(state: VideoState) -> str:
    """Skip video rendering when --no-images was used (no images to render)."""
    if state.get("skip_images"):
        return END
    return "video_renderer"


def build_graph() -> StateGraph:
    workflow = StateGraph(VideoState)

    # ── Register nodes ────────────────────────────────────────────────────
    workflow.add_node("research_agent", research_node)
    workflow.add_node("script_writer", script_writer_node)
    workflow.add_node("script_enhancer", script_enhancer_node)
    workflow.add_node("human_review_script", human_review_script_node)
    workflow.add_node("scene_planner", scene_planner_node)
    workflow.add_node("human_review_scenes", human_review_scenes_node)
    workflow.add_node("generate_scene_assets", generate_scene_assets)
    workflow.add_node("video_renderer", video_renderer_node)
    workflow.add_node("video_concatenator", video_concatenator_node)

    # ── Entry ─────────────────────────────────────────────────────────────
    # User provided --script → enhance it → plan scenes
    # No script → full research → script writer → plan scenes
    workflow.add_conditional_edges(START, _route_entry, {
        "research_agent": "research_agent",
        "script_enhancer": "script_enhancer",
    })
    workflow.add_edge("research_agent", "script_writer")
    workflow.add_edge("script_writer", "human_review_script")
    workflow.add_edge("human_review_script", "scene_planner")
    workflow.add_edge("script_enhancer", "scene_planner")
    workflow.add_edge("scene_planner", "human_review_scenes")

    # ── Parallel fan-out: one node call per scene ─────────────────────────
    workflow.add_conditional_edges("human_review_scenes", _dispatch_scenes)

    # ── Fan-in: all scene nodes join here, then route to renderer or END ─────
    workflow.add_conditional_edges(
        "generate_scene_assets",
        _route_after_assets,
        {"video_renderer": "video_renderer", END: END},
    )
    workflow.add_edge("video_renderer", "video_concatenator")
    workflow.add_edge("video_concatenator", END)

    return workflow


def compile_graph():
    """Compile and return the runnable LangGraph application."""
    from langgraph.checkpoint.memory import MemorySaver
    return build_graph().compile(checkpointer=MemorySaver())


# Build once at module import (used by CLI)
graph = compile_graph()
