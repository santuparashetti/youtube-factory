"""CLI command: ytfactory publish <project-id>."""

from __future__ import annotations

import typer


def publish(
    project_id: str = typer.Argument(..., help="Project ID to publish"),
    skip_thumbnail: bool = typer.Option(
        False,
        "--skip-thumbnail",
        help="Skip thumbnail generation (useful when image API is unavailable).",
    ),
) -> None:
    """Generate the upload-ready YouTube publishing package.

    Produces title, description, SEO tags, chapters, and thumbnail
    under workspace/jobs/<project-id>/publish/.
    """
    from ytfactory.publish.config import PublishConfig
    from ytfactory.publish.pipeline import PublishPipeline

    config = PublishConfig(skip_thumbnail=skip_thumbnail)
    package = PublishPipeline(config=config).run(project_id)

    if not package.is_valid:
        for err in package.validation_errors:
            typer.echo(f"ERROR: {err}", err=True)
        raise typer.Exit(1)
