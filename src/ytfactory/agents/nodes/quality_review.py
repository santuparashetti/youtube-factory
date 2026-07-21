"""Quality review node — Video Quality Review Engine V1 final gate."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.state import VideoState
from ytfactory.review.pipeline import ReviewPipeline
from ytfactory.retention.models import RetentionScoreResult

console = Console()


def _print_pipeline_qa_telemetry(score: RetentionScoreResult) -> None:
    mapping = {
        "Hook": ("hook", 30),
        "Story": ("story_flow", 20),
        "Motion": ("visuals_editing", 20),
        "Audio": ("audio_pacing", 15),
        "Ending": ("ending", 15),
    }
    lines = [f"Pipeline QA Score: {score.total:.0f}"]
    for label, (key, max_val) in mapping.items():
        val = score.breakdown.get(key, 0.0)
        lines.append(f"{label}: {val:.0f}/{max_val}")
    if score.violations:
        lines.append("Violations:")
        for v in score.violations[:10]:
            lines.append(f"- {v}")
    console.print(Panel("\n".join(lines), title="Pipeline QA", border_style="cyan"))


def quality_review_node(state: VideoState) -> dict:
    """
    Run the Video Quality Review Engine immediately after video concatenation.

    Reads all pipeline artefacts from disk (images, audio, subtitles, video
    clips, final.mp4, scene-plan.json, script.md) and writes reports to
    workspace/jobs/<project_id>/review/.

    Passes the pre-render retention score (from pre_render_gate_node state)
    to the review engine so it can combine pre- and post-render scores.

    Returns:
        review_result: {"verdict": "PASS"|"FAIL", ...}
        pipeline_qa_score: {"total": float, "breakdown": {...}, "violations": [...], "passed": bool}
    """
    project_id = state["project_id"]

    pipeline = ReviewPipeline()
    pre_render_score = state.get("pipeline_qa_score")
    report = pipeline.run(project_id, pre_render_score=pre_render_score)

    combined = RetentionScoreResult(
        total=report.pipeline_qa_score.get("total", 100.0) if report.pipeline_qa_score else 100.0,
        breakdown=report.pipeline_qa_score.get("breakdown", {}) if report.pipeline_qa_score else {},
        violations=report.pipeline_qa_score.get("violations", []) if report.pipeline_qa_score else [],
        passed=report.pipeline_qa_score.get("passed", True) if report.pipeline_qa_score else True,
    )

    _print_pipeline_qa_telemetry(combined)

    return {
        "review_result": {
            "verdict": report.verdict,
            "errors": report.all_errors,
            "warnings": report.all_warnings,
            "scenes_passed": report.scenes_passed,
            "scenes_failed": report.scenes_failed,
            "total_scenes": report.total_scenes,
            "processing_time_seconds": report.processing_time_seconds,
        },
        "pipeline_qa_score": {
            "total": combined.total,
            "breakdown": combined.breakdown,
            "violations": combined.violations,
            "passed": combined.passed,
        },
        "stage_errors": [f"[review] {e}" for e in report.all_errors],
    }
