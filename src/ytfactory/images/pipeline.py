from pathlib import Path

from ytfactory.config.settings import Settings
from ytfactory.domain.image import ImageRequest
from ytfactory.images.models import (
    ImageArtifact,
    ImageGenerationResult,
    ImageManifest,
)
from ytfactory.images.repository import ImageRepository
from ytfactory.providers.image.factory import get_image_provider


class ImagePipeline:
    """Generate images from a scene plan."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._provider = get_image_provider(settings)
        self._repository = ImageRepository()

    def run(
        self,
        project_id: str,
    ) -> ImageGenerationResult:

        project_dir = Path("workspace/jobs") / project_id

        scene_plan = (
            project_dir
            / "scenes"
            / "scene-plan.json"
        )

        if not scene_plan.exists():
            raise FileNotFoundError(
                f"Scene plan not found: {scene_plan}"
            )

        import json

        with open(
            scene_plan,
            encoding="utf-8",
        ) as f:
            scenes = json.load(f)["scenes"]

        output_dir = project_dir / "images"

        manifest = ImageManifest()

        for scene in scenes:

            filename = f"scene-{scene['index']:03d}.png"

            output_path = output_dir / filename

            request = ImageRequest(
                prompt=scene["visual_prompt"],
                output_path=output_path,
                width=self._settings.image_width,
                height=self._settings.image_height,
            )

            self._provider.generate(request)

            manifest.images.append(
                ImageArtifact(
                    scene_index=scene["index"],
                    prompt=scene["visual_prompt"],
                    filename=filename,
                    path=output_path,
                )
            )

        self._repository.save_manifest(
            output_dir,
            manifest,
        )

        return ImageGenerationResult(
            manifest=manifest,
            output_directory=output_dir,
        )