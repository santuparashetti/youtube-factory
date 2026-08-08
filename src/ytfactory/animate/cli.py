import typer

from ytfactory.animate.pipeline import AnimatePipeline


def animate_scenes(
    project_id: str = typer.Argument(..., help="Project ID"),
) -> None:
    """Animate scene images with LLM-selected motion effects (motion engine)."""
    AnimatePipeline().run(project_id)
