"""CLI command: ytfactory remediate <project-id>."""

from __future__ import annotations

import typer


def remediate(
    project_id: str = typer.Argument(..., help="Project ID to remediate"),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Plan remediation actions but do not execute them or re-validate.",
    ),
    quality_threshold: float = typer.Option(
        70.0,
        "--threshold",
        help="Quality score target (0–100). Stop when this is reached.",
    ),
    max_retries: int = typer.Option(
        3,
        "--max-retries",
        help="Maximum remediation cycles before giving up.",
    ),
    allow_full_regen: bool = typer.Option(
        False,
        "--allow-full-regen",
        help="Allow full_regeneration strategy as a last resort.",
    ),
) -> None:
    """Auto-repair a failed project by selectively regenerating failed components.

    Reads the latest review report for <project-id>, plans the minimum set of
    regeneration actions needed to meet the quality threshold, executes them,
    re-validates, and repeats until the threshold is met or max-retries is reached.

    Safe by default — use --dry-run to preview the plan without touching files.
    """
    from ytfactory.review.remediation.config import RemediationConfig
    from ytfactory.review.remediation.engine import AutoRemediationEngine
    from ytfactory.review.pipeline import ReviewPipeline

    # Run a fresh review to get the current state
    typer.echo(f"Running quality review for '{project_id}'…")
    review_report = ReviewPipeline().run(project_id)

    config = RemediationConfig(
        quality_threshold=quality_threshold,
        max_retries=max_retries,
        dry_run=dry_run,
        allow_full_regeneration=allow_full_regen,
    )

    engine = AutoRemediationEngine(config=config)
    typer.echo("Planning remediation…")
    report = engine.remediate(project_id, review_report)

    # ── Print summary ──────────────────────────────────────────────────────
    verdict_icon = "✅" if report.final_verdict == "PASS" else "❌"
    dry_tag = " [DRY RUN]" if report.dry_run else ""
    typer.echo("")
    typer.echo(f"Auto Remediation Engine V1{dry_tag}")
    typer.echo("=" * 40)
    typer.echo(f"Verdict:         {verdict_icon} {report.final_verdict}")
    typer.echo(f"Stopped reason:  {report.stopped_reason}")

    score_before = (
        f"{report.plan.quality_score_before:.1f}"
        if report.plan.quality_score_before is not None
        else "N/A"
    )
    score_after = (
        f"{report.final_quality_score:.1f}"
        if report.final_quality_score is not None
        else "N/A"
    )
    typer.echo(f"Score:           {score_before} → {score_after}")
    typer.echo(f"Cycles:          {report.total_cycles}")
    typer.echo(
        f"Actions:         {report.total_actions_succeeded}/{report.total_actions_executed} succeeded"
    )
    typer.echo(f"Assets rebuilt:  {len(report.regenerated_assets)}")
    typer.echo(f"Time:            {report.processing_time_seconds:.2f}s")
    typer.echo("")
    typer.echo(f"Report written to: workspace/jobs/{project_id}/remediation/")

    # Non-zero exit if FAIL after execution (not just dry-run)
    if not report.dry_run and report.final_verdict == "FAIL":
        raise typer.Exit(code=1)
