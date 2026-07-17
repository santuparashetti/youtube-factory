from rich.console import Console

from ytfactory.config.settings import Settings
from ytfactory.light_normalization.pipeline import LightNormalizationPipeline

console = Console()


def normalize(project_id: str) -> None:
    """Normalize a raw transcript before documentary script enhancement.

    Reads  workspace/jobs/<project-id>/script/script.md,
    cleans transcription artifacts while preserving all content, and
    writes the normalized text back in-place.

    Run this after import-script and before build / enhance.
    """
    pipeline = LightNormalizationPipeline(Settings())
    pipeline.run(project_id)
