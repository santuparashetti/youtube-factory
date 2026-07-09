"""CLI command for the CTA Overlay Engine."""

from __future__ import annotations

import typer
from rich.console import Console

_console = Console()


def overlay_cta(
    project_id: str = typer.Argument(..., help="Project ID to apply CTA overlay to"),
) -> None:
    """Apply the CTA overlay to video/final.mp4 for a project."""
    from ytfactory.cta.pipeline import CTABlockedError, CTAPipeline

    try:
        result = CTAPipeline().run(project_id)
    except CTABlockedError as exc:
        _console.print(f"[red]✗ CTA blocked: {exc}[/red]")
        raise typer.Exit(1)

    if not result.enabled:
        _console.print(
            "[dim]CTA Overlay: disabled in brand_config.yaml — skipped.[/dim]"
        )
        return

    if result.success:
        p = result.placement
        variant = p.variant.value if p else "unknown"
        ts = f"{p.timestamp:.1f}s" if p else "—"
        _console.print(
            f"[green]✓ CTA overlay applied[/green]  "
            f"variant={variant}  timestamp={ts}  "
            f"retries={result.review.retry_count}"
        )
    else:
        _console.print(
            "[red]✗ CTA overlay failed — inspect cta/cta-review-report.json[/red]"
        )
        raise typer.Exit(1)
