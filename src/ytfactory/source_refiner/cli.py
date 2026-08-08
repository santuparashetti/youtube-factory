from ytfactory.config.settings import Settings
from ytfactory.source_refiner.pipeline import SourceRefinerPipeline


def refine_source(project_id: str) -> None:
    """Editorial refinement pass on the base source script.

    Reads workspace/jobs/<project-id>/script/script.md, applies conservative
    editorial improvements (universalise culturally specific examples, improve
    clarity and flow without changing meaning), backs up the original to
    script_pre_refiner.md, and writes the refined text in place.

    Run this after import-script and before compose.
    """
    pipeline = SourceRefinerPipeline(Settings())
    pipeline.run(project_id)
