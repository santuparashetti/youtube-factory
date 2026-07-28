from ytfactory.config.settings import Settings
from ytfactory.structural_retention.pipeline import StructuralRetentionPipeline


def structural_retention(project_id: str) -> None:
    """Reshape a script's structure for viewer retention (post-enhancer, pre-scene-planner).

    Reads workspace/jobs/<project-id>/script/script.md (the enhancer's output),
    applies the 5 structural retention moves, and writes the result back in
    place. Snapshots the pre-pass input to pre-structural-retention.md and
    writes structural-retention-report.json (moves applied, stories cut/
    reordered, faithfulness flags — non-blocking).

    Normally runs automatically as part of `build` / `run`. Use this to
    re-run just this pass on an existing project.
    """
    pipeline = StructuralRetentionPipeline(Settings())
    pipeline.run(project_id)
