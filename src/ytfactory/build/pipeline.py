from ytfactory.config.settings import Settings

from ytfactory.captions.pipeline import CaptionPipeline
from ytfactory.images.pipeline import ImagePipeline
from ytfactory.review.pipeline import ReviewPipeline
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

    def run(
        self,
        project_id: str,
        skip_scenes: bool = False,
        skip_images: bool = False,
    ) -> None:

        if not skip_scenes:
            self.scenes.run(project_id)
        if not skip_images:
            self.images.run(project_id)
        self.voice.run(project_id)
        self.captions.run(project_id)
        self.video.run(project_id)
        self.review.run(project_id)