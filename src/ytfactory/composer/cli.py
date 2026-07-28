from ytfactory.config.settings import Settings
from ytfactory.composer.pipeline import ComposerPipeline


def compose(project_id: str) -> None:
    """Compose the finished documentary narration from a base script.

    Reads workspace/jobs/<project-id>/script/script.md (the base script),
    runs one whole-cloth LLM call per ATMA_THEORY_COMPOSER.md, and writes the
    composed result back in place. Snapshots the pre-compose input to
    script_pre_composer.md.

    Normally runs automatically as part of `build` / `run`, replacing the
    (archived, not deleted) enhancer + Structural Retention Pass. Use this to
    re-run just this stage on an existing project.
    """
    pipeline = ComposerPipeline(Settings())
    pipeline.run(project_id)
