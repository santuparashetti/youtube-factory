from ytfactory.config.settings import Settings

from ytfactory.captions.pipeline import CaptionPipeline
from ytfactory.images.pipeline import ImagePipeline
from ytfactory.publish.pipeline import PublishPipeline
from ytfactory.review.pipeline import ReviewPipeline
from ytfactory.review.remediation.config import RemediationConfig
from ytfactory.review.remediation.engine import AutoRemediationEngine
from ytfactory.scenes.pipeline import ScenePipeline
from ytfactory.video.pipeline import VideoPipeline
from ytfactory.voice.pipeline import VoicePipeline


class BuildPipeline:
    """Run the complete video production pipeline."""

    def __init__(self):
        settings = Settings()

        self.scenes = ScenePipeline(settings)
        self.images = ImagePipeline(settings)
        self.voice = VoicePipeline(settings)
        self.captions = CaptionPipeline()
        self.video = VideoPipeline()
        self.review = ReviewPipeline()
        self.publish = PublishPipeline(settings=settings)

    def run(
        self,
        project_id: str,
        skip_scenes: bool = False,
        skip_images: bool = False,
        auto_remediate: bool = True,
        remediation_threshold: float = 70.0,
        remediation_max_retries: int = 3,
    ) -> None:

        if not skip_scenes:
            self.scenes.run(project_id)
        if not skip_images:
            self.images.run(project_id)
        self.voice.run(project_id)
        self.captions.run(project_id)
        self.video.run(project_id)

        review_report = self.review.run(project_id)

        # Auto Remediation: run when review fails and auto_remediate is enabled
        if auto_remediate and review_report.verdict == "FAIL":
            config = RemediationConfig(
                quality_threshold=remediation_threshold,
                max_retries=remediation_max_retries,
                dry_run=False,
            )
            AutoRemediationEngine(config=config).remediate(project_id, review_report)

        self.publish.run(project_id)
