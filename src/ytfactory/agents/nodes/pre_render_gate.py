"""Pre-render gate node — runs retention checks between scene_planner and human_review_scenes."""

from __future__ import annotations

from rich.console import Console
from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.retention.pre_render_gate import (
    link_scenes_to_segments,
    parse_script_to_segments,
    run_pre_render_gate,
)
from ytfactory.shared.pipeline_status import PipelineAbort, get_writer

_settings = Settings()
console = Console()


def pre_render_gate_node(state: VideoState) -> dict:
    """
    LangGraph node: parse script into segments, link to scenes, run the
    pre-render retention gate. Hard-reject via PipelineAbort on frame naming
    gate failure. Returns updated scene_plan with linked_segment populated.
    """
    script_md = state.get("script_md", "")
    scene_plan = state.get("scene_plan", [])

    if not _settings.pipeline_qa_enabled:
        console.print("  [dim]Pipeline QA disabled — skipping pre-render gate.[/dim]")
        return {"scene_plan": scene_plan}

    if not script_md or not scene_plan:
        console.print("  [yellow]⚠[/yellow] Pre-render gate skipped: no script or scene plan.")
        return {"scene_plan": scene_plan}

    segments = parse_script_to_segments(script_md)
    scene_plan = link_scenes_to_segments(list(scene_plan), segments)

    # Re-hydrate Scene objects for run_pre_render_gate
    from ytfactory.scenes.models import Scene

    scenes = [
        Scene(
            index=s.get("index", i + 1),
            title=s.get("title", ""),
            narration=s.get("narration", ""),
            visual_prompt=s.get("visual_prompt", ""),
            duration_seconds=float(s.get("duration_seconds", 0.0)),
            pose=s.get("pose"),
            composition=s.get("composition"),
            motion_type=s.get("motion_type"),
            text_overlay=s.get("text_overlay"),
            text_reveal_segments=s.get("text_reveal_segments", []),
            hold_required=s.get("hold_required", False),
            linked_segment=s.get("linked_segment"),
        )
        for i, s in enumerate(scene_plan)
    ]

    from ytfactory.shared.constants import WORKSPACE_DIR
    from ytfactory.shared.paths import safe_project_dir

    project_id = state["project_id"]
    project_dir = safe_project_dir(project_id, WORKSPACE_DIR)
    result = run_pre_render_gate(segments, scenes, project_dir=project_dir)

    for v in result.violations:
        console.print(f"  [yellow]⚠[/yellow] {v}")

    if not result.passed:
        writer = get_writer()
        if writer:
            writer.stage_fail(
                f"Pre-render gate failed (score {result.total}/100): "
                + "; ".join(result.violations[:3])
            )

        hard_reject = (
            any("[P1a]" in v for v in result.violations)
            and _settings.frame_naming_gate_enabled
        )
        if hard_reject:
            raise PipelineAbort(
                stage="pre_render_gate",
                reason=(
                    f"Frame naming gate failed (score {result.total}/100): "
                    + "; ".join(result.violations[:3])
                ),
            )

    console.print(
        f"  [green]✓[/green] Pre-render gate passed (score {result.total}/100)"
    )

    return {
        "scene_plan": [s.model_dump() for s in scenes],
        "pipeline_qa_score": {
            "total": result.total,
            "breakdown": result.breakdown,
            "violations": result.violations,
            "passed": result.passed,
        },
    }
