"""ReviewPipeline — thin orchestration layer used by BuildPipeline and CLI."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from ytfactory.review.config import ReviewConfig
from ytfactory.review.engine import VideoQualityReviewEngine
from ytfactory.review.models import ReviewReport
from ytfactory.review.reporter import ReviewReporter
from ytfactory.review.validation.config import ValidationRulesConfig

console = Console()


class ReviewPipeline:
    """Run the Video Quality Review Engine and write all artefacts."""

    def __init__(
        self,
        config: ReviewConfig | None = None,
        validation_config: ValidationRulesConfig | None = None,
    ) -> None:
        self._engine = VideoQualityReviewEngine(config, validation_config)
        self._reporter = ReviewReporter()

    def run(
        self,
        project_id: str,
        pre_render_score: dict | None = None,
    ) -> ReviewReport:
        """Execute review, write outputs, print summary.  Returns ReviewReport."""
        console.print(Rule("[bold cyan]Video Quality Review Engine V1[/bold cyan]"))
        console.print()

        report = self._engine.review(project_id, pre_render_score=pre_render_score)
        review_dir = self._reporter.write(report)

        _print_summary(report, review_dir)
        return report


# ── Console output ────────────────────────────────────────────────────────────


def _print_summary(report: ReviewReport, review_dir: Path) -> None:
    verdict_color = "green" if report.verdict == "PASS" else "red"
    verdict_icon = "✓" if report.verdict == "PASS" else "✗"

    error_lines = ""
    if report.all_errors:
        error_lines = "\n\n[red]Errors:[/red]\n" + "\n".join(
            f"  • {e}" for e in report.all_errors[:10]
        )
        if len(report.all_errors) > 10:
            error_lines += f"\n  … and {len(report.all_errors) - 10} more"

    warn_lines = ""
    if report.all_warnings:
        warn_lines = "\n\n[yellow]Warnings:[/yellow]\n" + "\n".join(
            f"  • {w}" for w in report.all_warnings[:5]
        )
        if len(report.all_warnings) > 5:
            warn_lines += f"\n  … and {len(report.all_warnings) - 5} more"

    stage_summary = "\n".join(
        f"  {'✓' if s.passed else '✗'} {s.stage_name.replace('_', ' ').title()}: "
        f"{s.checks_passed}/{s.checks_run} checks"
        for s in report.stage_results
    )

    console.print(
        Panel(
            f"[bold {verdict_color}]{verdict_icon} {report.verdict}[/bold {verdict_color}]\n\n"
            f"[bold]Project:[/bold] {report.project_id}\n"
            f"[bold]Scenes:[/bold] {report.scenes_passed}/{report.total_scenes} passed\n"
            f"[bold]Processing time:[/bold] {report.processing_time_seconds:.2f}s\n\n"
            f"[bold]Stage breakdown:[/bold]\n{stage_summary}"
            + error_lines
            + warn_lines
            + f"\n\n[bold]Reports written to:[/bold] {review_dir}",
            title="Quality Review",
            border_style=verdict_color,
        )
    )
