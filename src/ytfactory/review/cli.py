"""CLI command: ytfactory review <project-id>."""

from __future__ import annotations


import typer

from ytfactory.review.pipeline import ReviewPipeline


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
    report = pipeline.run(project_id)

    if report.verdict == "FAIL":
        raise typer.Exit(code=1)
