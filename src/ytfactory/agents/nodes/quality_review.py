"""Quality review node — Video Quality Review Engine V1 final gate."""

from __future__ import annotations

from rich.console import Console

from ytfactory.agents.state import VideoState
from ytfactory.review.pipeline import ReviewPipeline

console = Console()


def quality_review_node(state: VideoState) -> dict:
    """
    Run the Video Quality Review Engine immediately after video concatenation.

    Reads all pipeline artefacts from disk (images, audio, subtitles, video
    clips, final.mp4, scene-plan.json, script.md) and writes reports to
    workspace/jobs/<project_id>/review/.

    Returns:
        review_result: {"verdict": "PASS"|"FAIL", "errors": [...], "warnings": [...]}
    """
    project_id = state["project_id"]

    pipeline = ReviewPipeline()
    report = pipeline.run(project_id)

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
        "stage_errors": [
            f"[review] {e}" for e in report.all_errors
        ],
    }
