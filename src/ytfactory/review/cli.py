"""CLI command: ytfactory review <project-id>."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ytfactory.review.pipeline import ReviewPipeline
from ytfactory.retention.models import RetentionScoreResult
from rich.console import Console
from rich.panel import Panel

console = Console()


def _load_pre_render_score(project_id: str) -> dict | None:
    """Try to load a previously-computed pre-render Pipeline QA score from disk."""
    try:
        from ytfactory.shared.constants import WORKSPACE_DIR

        project_dir = Path(WORKSPACE_DIR) / project_id
        candidates = [
            project_dir / "review" / "latest.json",
            project_dir / "review" / "quality-review.json",
        ]
        for path in candidates:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                score = data.get("pipeline_qa_score")
                if score:
                    return score
    except Exception:
        pass
    return None


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


def review(
    project_id: str = typer.Argument(..., help="Project ID to review"),
    fail_on_warnings: bool = typer.Option(
        False,
        "--strict",
        help="Treat warnings as failures (strict mode)",
    ),
) -> None:
    """Run the Video Quality Review Engine on a completed project.

    Validates asset integrity, timeline, content, and production quality.
    Writes reports to workspace/jobs/<project-id>/review/.
    """
    from ytfactory.review.config import ReviewConfig

    config = ReviewConfig(fail_on_warnings=fail_on_warnings)
    pipeline = ReviewPipeline(config)

    pre_render_score = _load_pre_render_score(project_id)
    report = pipeline.run(project_id, pre_render_score=pre_render_score)

    if report.pipeline_qa_score:
        combined = RetentionScoreResult(
            total=report.pipeline_qa_score.get("total", 100.0),
            breakdown=report.pipeline_qa_score.get("breakdown", {}),
            violations=report.pipeline_qa_score.get("violations", []),
            passed=report.pipeline_qa_score.get("passed", True),
        )
        _print_pipeline_qa_telemetry(combined)

    if report.verdict == "FAIL":
        raise typer.Exit(code=1)
