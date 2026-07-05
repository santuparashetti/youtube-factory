import typer
from rich.console import Console

from .pipeline import BuildPipeline

console = Console()


def build(
    project_id: str = typer.Argument(..., help="Project ID to build"),
    skip_scenes: bool = typer.Option(False, "--skip-scenes", help="Skip scene planning (use existing scene-plan.json)"),
    skip_images: bool = typer.Option(False, "--skip-images", help="Skip image generation (use existing images)"),
    no_remediate: bool = typer.Option(False, "--no-remediate", help="Skip auto-remediation even if review fails"),
    remediation_threshold: float = typer.Option(70.0, "--remediation-threshold", help="Quality score threshold for auto-remediation (0-100)"),
    remediation_retries: int = typer.Option(3, "--remediation-retries", help="Max auto-remediation retry cycles"),
):
    """Build the complete video production pipeline end-to-end.

    Runs: scenes → images → voice → captions → video → review →
    [auto-remediation if FAIL] → publish
    """
    BuildPipeline().run(
        project_id,
        skip_scenes=skip_scenes,
        skip_images=skip_images,
        auto_remediate=not no_remediate,
        remediation_threshold=remediation_threshold,
        remediation_max_retries=remediation_retries,
    )

    console.print("[bold green]✓ Build completed[/bold green]")
