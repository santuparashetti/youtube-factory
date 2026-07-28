"""
LangGraph agentic pipeline graph definition.

Flow:
  research_agent
    → script_writer
      → [human_review_script]
        → composer  ◄── joins here from the alternate entry below too
          → editorial_qa        ← Editorial QA Stage (flags only, never gates)
            → [human_review_final_script]  ← hash-guarded review checkpoint
              → scene_planner
          → [human_review_scenes]

  Alternate entry — YouTube URL source (see _route_entry):
    acquire_audio → transcribe → translate → [human_review_base_script]
      → composer
            → generate_scene_assets (parallel fan-out, one per scene)
              → video_renderer
                → video_concatenator
                  → cta                  ← CTA Overlay Engine V2
                    → quality_review     ← Video Quality Review Engine V1
                      PASS → publish     ← Publishing & Growth Engine V1
                      FAIL → remediation ← Auto Remediation Engine V1
                        PASS → publish
                        FAIL → END (pipeline stopped, publishing skipped)

composer replaces the retired transform-based enhancer (Pass 1/2/3) and the
Structural Retention Pass — both archived, not deleted (still importable:
agents/nodes/script_enhancer.py, agents/nodes/structural_retention.py) but no
longer wired into this graph until the composer is proven.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ytfactory.agents.nodes.composer import composer_node
from ytfactory.agents.nodes.cta import cta_node
from ytfactory.agents.nodes.editorial_qa import editorial_qa_node
from ytfactory.agents.nodes.human_review import (
    human_review_base_script_node,
    human_review_final_script_node,
    human_review_scenes_node,
    human_review_script_node,
)
from ytfactory.agents.nodes.pre_render_gate import pre_render_gate_node
from ytfactory.agents.nodes.research import research_node
from ytfactory.agents.nodes.scene_assets import generate_scene_assets
from ytfactory.agents.nodes.scene_planner import scene_planner_node
from ytfactory.agents.nodes.script_writer import script_writer_node
from ytfactory.agents.nodes.publish import publish_node
from ytfactory.agents.nodes.quality_review import quality_review_node
from ytfactory.agents.nodes.remediation import remediation_node
from ytfactory.agents.nodes.video_concatenator import video_concatenator_node
from ytfactory.agents.nodes.video_renderer import video_renderer_node
from ytfactory.agents.nodes.youtube_ingest import (
    acquire_audio_node,
    transcribe_node,
    translate_node,
)
from ytfactory.agents.state import VideoState


def _dispatch_scenes(state: VideoState) -> list[Send]:
    """Fan out: one generate_scene_assets invocation per scene."""
    return [
        Send("generate_scene_assets", {**state, "current_scene": scene})
        for scene in state.get("scene_plan", [])
    ]


def _route_entry(state: VideoState) -> str:
    """Route by input source: YouTube URL > pre-written script > full research."""
    if state.get("source_url"):
        return "acquire_audio"
    if state.get("script_md"):
        return "composer"
    return "research_agent"


def _route_after_assets(state: VideoState) -> str:
    """Skip video rendering when --no-images was used (no images to render)."""
    if state.get("skip_images"):
        return END
    return "video_renderer"


def _route_after_review(state: VideoState) -> str:
    """Gate publish on review verdict: PASS continues, FAIL goes to remediation."""
    verdict = (state.get("review_result") or {}).get("verdict", "FAIL")
    if verdict == "PASS":
        return "publish"
    return "remediation"


def _route_after_remediation(state: VideoState) -> str:
    """Gate publish on remediation outcome: PASS continues, FAIL stops pipeline."""
    verdict = (state.get("remediation_result") or {}).get("final_verdict", "FAIL")
    if verdict == "PASS":
        return "publish"
    return END


def build_graph() -> StateGraph:
    workflow = StateGraph(VideoState)

    # ── Register nodes ────────────────────────────────────────────────────
    workflow.add_node("research_agent", research_node)
    workflow.add_node("script_writer", script_writer_node)
    workflow.add_node("composer", composer_node)
    workflow.add_node("editorial_qa", editorial_qa_node)
    workflow.add_node("human_review_final_script", human_review_final_script_node)
    workflow.add_node("human_review_script", human_review_script_node)
    workflow.add_node("acquire_audio", acquire_audio_node)
    workflow.add_node("transcribe", transcribe_node)
    workflow.add_node("translate", translate_node)
    workflow.add_node("human_review_base_script", human_review_base_script_node)
    workflow.add_node("scene_planner", scene_planner_node)
    workflow.add_node("pre_render_gate", pre_render_gate_node)
    workflow.add_node("human_review_scenes", human_review_scenes_node)
    workflow.add_node("generate_scene_assets", generate_scene_assets)
    workflow.add_node("video_renderer", video_renderer_node)
    workflow.add_node("video_concatenator", video_concatenator_node)
    workflow.add_node("cta", cta_node)
    workflow.add_node("quality_review", quality_review_node)
    workflow.add_node("remediation", remediation_node)
    workflow.add_node("publish", publish_node)

    # ── Entry ─────────────────────────────────────────────────────────────
    # YouTube URL → ingestion chain → base script review → compose → plan scenes
    # User provided --script → compose it whole → plan scenes
    # No script, no URL → full research → script writer → compose → plan scenes
    workflow.add_conditional_edges(
        START,
        _route_entry,
        {
            "acquire_audio": "acquire_audio",
            "research_agent": "research_agent",
            "composer": "composer",
        },
    )
    workflow.add_edge("acquire_audio", "transcribe")
    workflow.add_edge("transcribe", "translate")
    workflow.add_edge("translate", "human_review_base_script")
    workflow.add_edge("human_review_base_script", "composer")
    workflow.add_edge("research_agent", "script_writer")
    workflow.add_edge("script_writer", "human_review_script")
    workflow.add_edge("human_review_script", "composer")
    workflow.add_edge("composer", "editorial_qa")
    workflow.add_edge("editorial_qa", "human_review_final_script")
    workflow.add_edge("human_review_final_script", "scene_planner")
    workflow.add_edge("scene_planner", "pre_render_gate")
    workflow.add_edge("pre_render_gate", "human_review_scenes")

    # ── Parallel fan-out: one node call per scene ─────────────────────────
    workflow.add_conditional_edges("human_review_scenes", _dispatch_scenes)

    # ── Fan-in: all scene nodes join here, then route to renderer or END ─────
    workflow.add_conditional_edges(
        "generate_scene_assets",
        _route_after_assets,
        {"video_renderer": "video_renderer", END: END},
    )
    workflow.add_edge("video_renderer", "video_concatenator")
    workflow.add_edge("video_concatenator", "cta")
    workflow.add_edge("cta", "quality_review")
    workflow.add_conditional_edges(
        "quality_review",
        _route_after_review,
        {"publish": "publish", "remediation": "remediation"},
    )
    workflow.add_conditional_edges(
        "remediation",
        _route_after_remediation,
        {"publish": "publish", END: END},
    )
    workflow.add_edge("publish", END)

    return workflow


def compile_graph():
    """Compile and return the runnable LangGraph application."""
    from langgraph.checkpoint.memory import MemorySaver

    return build_graph().compile(checkpointer=MemorySaver())


# Build once at module import (used by CLI)
graph = compile_graph()
