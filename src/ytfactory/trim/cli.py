from ytfactory.config.settings import Settings
from ytfactory.trim.pipeline import SurgicalTrimPipeline


def trim_script(project_id: str) -> None:
    """Surgical trim pass — compress script.md to the 6-8 min word target (780–1040 words).

    Applies the smallest possible edits (remove redundancy, compress verbose
    sentences, cut repeated ideas) while keeping all structural sections intact:
    hook, story beats, emotional turning points, climax, rehook, and CTA.

    Backs up the original to script_pre_trim.md and writes the trimmed version
    in place. Run after compose when the script is over the target length.
    """
    pipeline = SurgicalTrimPipeline(Settings())
    pipeline.run(project_id)
