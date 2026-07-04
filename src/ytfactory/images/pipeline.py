from __future__ import annotations

import json
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
    """Generate YouTube-ready images."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._provider = get_image_provider(settings)
        self._repository = ImageRepository()

    def run(
        self,
        project_id: str,
    ) -> ImageGenerationResult:

        project_dir = Path("workspace/jobs") / project_id

        scene_plan_file = (
            project_dir
            / "scenes"
            / "scene-plan.json"
        )

        if not scene_plan_file.exists():
            raise FileNotFoundError(
                f"Scene plan not found: {scene_plan_file}"
            )

        with open(
            scene_plan_file,
            encoding="utf-8",
        ) as f:
            scene_plan = json.load(f)

        scenes = scene_plan["scenes"]

        output_dir = project_dir / "images"
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        manifest = ImageManifest()

        total = len(scenes)

        print(
            f"\nGenerating {total} YouTube images "
            f"({self._settings.image_width}x{self._settings.image_height})\n"
        )

        for index, scene in enumerate(
            scenes,
            start=1,
        ):

            filename = (
                f"scene-{scene['index']:03d}.png"
            )

            output_path = output_dir / filename

            # Asset scenes skip AI image generation entirely.
            if scene.get("scene_type") == "asset":
                asset_path = Path(scene.get("asset_path", ""))
                print(f"[{index}/{total}] {filename} (asset — skipping generation)")
                manifest.images.append(
                    ImageArtifact(
                        scene_index=scene["index"],
                        prompt="",
                        filename=filename,
                        path=asset_path if asset_path.exists() else output_path,
                    )
                )
                continue

            request = ImageRequest(
                prompt=scene["visual_prompt"],
                output_path=output_path,
                width=self._settings.image_width,
                height=self._settings.image_height,
            )

            if output_path.exists():
                print(f"[{index}/{total}] {filename} (skip)")
                manifest.images.append(
                    ImageArtifact(
                        scene_index=scene["index"],
                        prompt=scene["visual_prompt"],
                        filename=filename,
                        path=output_path,
                    )
                )
                continue

            print(
                f"[{index}/{total}] {filename}"
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

        print("\nImage generation completed.\n")

        return ImageGenerationResult(
            manifest=manifest,
            output_directory=output_dir,
        )