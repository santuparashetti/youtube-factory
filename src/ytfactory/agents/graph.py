"""
LangGraph agentic pipeline graph definition.

PRODUCTION PATH (default):
  YouTube URL source  → acquire_audio → transcribe → translate
                          → [human_review_base_script] → beats_extractor
                          → script_identity → atma_7beat_refiner
                          → script_validator → [human_review_atma_script]
                          → scene_planner

  Script / project    → beats_extractor → script_identity → atma_7beat_refiner
                          → script_validator → [human_review_atma_script]
                          → scene_planner

The 7-Beat path is the default production route. It generates exactly one
refined script, validates it, and gates on human review (Accept/Reject).
A rejected script triggers targeted refinement (inside human_review_atma_script_node)
without re-running the full graph loop.

ARCHIVED (code kept, not wired):
  source_refiner, composer, script_selector_polisher, beat_verifier,
  human_review_final_script — the old A/B composition path. All nodes
  remain importable so their tests continue to pass.

  editorial_qa — retired before the A/B era; also archived.

scene_planner and everything after remains unchanged.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ytfactory.agents.nodes.atma_refiner import (
    atma_7beat_refiner_node,
    human_review_atma_script_node,
    script_identity_node,
    script_validator_node,
)
from ytfactory.agents.nodes.beats_extractor import beats_extractor_node
from ytfactory.agents.nodes.cta import cta_node
from ytfactory.agents.nodes.human_review import (
    human_review_base_script_node,
    human_review_scenes_node,
)
from ytfactory.agents.nodes.pre_render_gate import pre_render_gate_node
from ytfactory.agents.nodes.publish import publish_node
from ytfactory.agents.nodes.quality_review import quality_review_node
from ytfactory.agents.nodes.remediation import remediation_node
from ytfactory.agents.nodes.scene_assets import generate_scene_assets
from ytfactory.agents.nodes.scene_planner import scene_planner_node
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
    """Route by input source: YouTube URL → ingestion chain; otherwise → beats_extractor."""
    if state.get("source_url"):
        return "acquire_audio"
    return "beats_extractor"


def _route_after_assets(state: VideoState) -> str:
    """Skip video rendering when --no-images was used (no images to render)."""
    if state.get("skip_images"):
        return END
    return "video_renderer"


def _route_after_review(state: VideoState) -> str:
    """Pre-stitch gate: PASS → stitch, FAIL → remediation."""
    verdict = (state.get("review_result") or {}).get("verdict", "FAIL")
    if verdict == "PASS":
        return "video_concatenator"
    return "remediation"


def _route_after_remediation(state: VideoState) -> str:
    """Post-remediation gate: PASS → stitch, FAIL → stops pipeline."""
    verdict = (state.get("remediation_result") or {}).get("final_verdict", "FAIL")
    if verdict == "PASS":
        return "video_concatenator"
    return END


def build_graph() -> StateGraph:
    workflow = StateGraph(VideoState)

    # ── Production path nodes ─────────────────────────────────────────────
    workflow.add_node("acquire_audio", acquire_audio_node)
    workflow.add_node("transcribe", transcribe_node)
    workflow.add_node("translate", translate_node)
    workflow.add_node("human_review_base_script", human_review_base_script_node)
    workflow.add_node("beats_extractor", beats_extractor_node)
    workflow.add_node("script_identity", script_identity_node)
    workflow.add_node("atma_7beat_refiner", atma_7beat_refiner_node)
    workflow.add_node("script_validator", script_validator_node)
    workflow.add_node("human_review_atma_script", human_review_atma_script_node)
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
    workflow.add_conditional_edges(
        START,
        _route_entry,
        {
            "acquire_audio": "acquire_audio",
            "beats_extractor": "beats_extractor",
        },
    )

    # ── YouTube ingestion path ────────────────────────────────────────────
    workflow.add_edge("acquire_audio", "transcribe")
    workflow.add_edge("transcribe", "translate")
    workflow.add_edge("translate", "human_review_base_script")
    workflow.add_edge("human_review_base_script", "beats_extractor")

    # ── 7-Beat production path ────────────────────────────────────────────
    # beats_extractor extracts protected story beats (6-10) for the refiner.
    # script_identity extracts ScriptIdentity deterministically (no LLM).
    # atma_7beat_refiner runs one editor pass using the 7-Beat framework.
    # script_validator validates word count, beat coverage, factual risks.
    # human_review_atma_script gates on human Accept/Reject (with inline
    #   targeted-refinement loop on rejection — no graph-level cycle needed).
    # Only the accepted canonical script reaches scene_planner.
    workflow.add_edge("beats_extractor", "script_identity")
    workflow.add_edge("script_identity", "atma_7beat_refiner")
    workflow.add_edge("atma_7beat_refiner", "script_validator")
    workflow.add_edge("script_validator", "human_review_atma_script")
    workflow.add_edge("human_review_atma_script", "scene_planner")

    # ── Scene planning and rendering (unchanged) ──────────────────────────
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
    # Pre-stitch review: validate scene clips before assembling final.mp4
    workflow.add_edge("video_renderer", "quality_review")
    workflow.add_conditional_edges(
        "quality_review",
        _route_after_review,
        {"video_concatenator": "video_concatenator", "remediation": "remediation"},
    )
    workflow.add_conditional_edges(
        "remediation",
        _route_after_remediation,
        {"video_concatenator": "video_concatenator", END: END},
    )
    # Stitch + post-processing: only runs once scene clips pass review
    workflow.add_edge("video_concatenator", "cta")
    workflow.add_edge("cta", "publish")
    workflow.add_edge("publish", END)

    return workflow


def compile_graph():
    """Compile and return the runnable LangGraph application."""
    from langgraph.checkpoint.memory import MemorySaver

    return build_graph().compile(checkpointer=MemorySaver())


# Build once at module import (used by CLI)
graph = compile_graph()
