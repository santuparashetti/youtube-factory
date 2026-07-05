"""Remediation node — Auto Remediation Engine V1 in the agentic pipeline."""

from __future__ import annotations

from rich.console import Console

from ytfactory.agents.state import VideoState
from ytfactory.review.remediation.config import RemediationConfig
from ytfactory.review.remediation.engine import AutoRemediationEngine
from ytfactory.review.pipeline import ReviewPipeline

console = Console()


def remediation_node(state: VideoState) -> dict:
    """
    Run Auto Remediation Engine when quality_review_node returned FAIL.

    Attempts up to max_retries cycles of delete-and-regenerate, then
    re-validates with the full VQRE.  Returns remediation_result so the
    downstream router can decide whether to continue to publish or stop.
    """
    project_id = state["project_id"]

    # Re-run the full ReviewPipeline to get a live ReviewReport object
    # (the state only stores a dict summary; AutoRemediationEngine needs the
    # real dataclass with sub-reports attached).
    live_review = ReviewPipeline().run(project_id)

    config = RemediationConfig(dry_run=False)
    remediation_report = AutoRemediationEngine(config=config).remediate(
        project_id, live_review
    )

    result = {
        "final_verdict": remediation_report.final_verdict,
        "stopped_reason": remediation_report.stopped_reason,
        "total_cycles": remediation_report.total_cycles,
        "final_quality_score": remediation_report.final_quality_score,
    }

    errors: list[str] = []
    if remediation_report.final_verdict != "PASS":
        errors.append(
            f"[remediation] Quality gate still FAIL after "
            f"{remediation_report.total_cycles} cycle(s) "
            f"(reason: {remediation_report.stopped_reason}). Publishing skipped."
        )

    return {
        "remediation_result": result,
        "stage_errors": errors,
    }
