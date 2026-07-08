from __future__ import annotations

import json
from pathlib import Path

from ytfactory.config.settings import Settings
from ytfactory.domain.image import ImageRequest
from ytfactory.images.human_detector import compute_sharpness, detect_human_presence
from ytfactory.images.models import (
    ImageArtifact,
    ImageGenerationResult,
    ImageManifest,
)
from ytfactory.images.prompt_engine import _DEFAULT_NEGATIVE_PROMPT, _PROVIDERS_WITH_NEGATIVE_PROMPTS
from ytfactory.images.repository import ImageRepository
from ytfactory.images.review_config import ImageReviewConfig
from ytfactory.images.review_engine import ImageReviewEngine, write_image_quality_summary
from ytfactory.images.review_models import SceneReviewArtifact
from ytfactory.providers.image.factory import get_image_provider


class ImagePipeline:
    """Generate YouTube-ready images."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._provider = get_image_provider(settings)
        self._repository = ImageRepository()
        self._uses_negative_prompts = (
            settings.image_provider.lower() in _PROVIDERS_WITH_NEGATIVE_PROMPTS
        )
        self._review_config = ImageReviewConfig.from_settings(settings)
        self._review_engine: ImageReviewEngine | None = self._build_review_engine()

    def _build_review_engine(self) -> ImageReviewEngine | None:
        """Build the review engine if image review is enabled."""
        if not self._review_config.enabled:
            return None
        try:
            from ytfactory.providers.vision.factory import get_vision_provider
            vision = get_vision_provider(
                self._review_config.provider,
                local_model=self._review_config.local_model,
            )
            return ImageReviewEngine(self._review_config, vision, self._provider)
        except Exception:
            return None

    def run(
        self,
        project_id: str,
    ) -> ImageGenerationResult:

        project_dir = Path("workspace/jobs") / project_id

        scene_plan_file = project_dir / "scenes" / "scene-plan.json"

        if not scene_plan_file.exists():
            raise FileNotFoundError(f"Scene plan not found: {scene_plan_file}")

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
        review_artifacts: list[SceneReviewArtifact] = []

        total = len(scenes)

        print(
            f"\nGenerating {total} YouTube images "
            f"({self._settings.image_width}x{self._settings.image_height})\n"
        )

        for index, scene in enumerate(
            scenes,
            start=1,
        ):
            filename = f"scene-{scene['index']:03d}.png"

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

            negative_prompt = (
                scene.get("negative_prompt") or _DEFAULT_NEGATIVE_PROMPT
                if self._uses_negative_prompts
                else None
            )
            request = ImageRequest(
                prompt=scene["visual_prompt"],
                output_path=output_path,
                width=self._settings.image_width,
                height=self._settings.image_height,
                negative_prompt=negative_prompt,
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

            print(f"[{index}/{total}] {filename}")

            self._provider.generate(request)

            # Human quality validation: regenerate if sharpness is below threshold
            prompt_text = scene.get("visual_prompt", "")
            if detect_human_presence(prompt_text) and self._settings.image_human_max_retries > 0:
                sharpness = compute_sharpness(output_path)
                threshold = self._settings.image_human_min_sharpness
                max_retries = self._settings.image_human_max_retries
                for attempt in range(max_retries):
                    if sharpness >= threshold:
                        break
                    print(
                        f"  ↻ Human scene sharpness {sharpness:.1f} < {threshold} — "
                        f"retry {attempt + 1}/{max_retries}"
                    )
                    output_path.unlink(missing_ok=True)
                    self._provider.generate(request)
                    sharpness = compute_sharpness(output_path)
                if sharpness < threshold:
                    print(
                        f"  ⚠ {filename}: sharpness {sharpness:.1f} still below "
                        f"{threshold} after {max_retries} retries"
                    )

            # Vision review + auto-remediation (when enabled)
            if self._review_engine is not None and output_path.exists():
                scene_with_dims = {
                    **scene,
                    "width": self._settings.image_width,
                    "height": self._settings.image_height,
                }
                review_artifact = self._review_engine.review_scene(
                    scene=scene_with_dims,
                    image_path=output_path,
                    output_dir=output_dir,
                )
                review_artifacts.append(review_artifact)
                status_tag = "PASS" if review_artifact.status == "PASS" else review_artifact.status
                print(
                    f"  ✦ Vision review: {status_tag} "
                    f"(score={review_artifact.score:.0f}, "
                    f"attempts={review_artifact.attempts})"
                )

            manifest.images.append(
                ImageArtifact(
                    scene_index=scene["index"],
                    prompt=scene["visual_prompt"],
                    filename=filename,
                    path=output_path,
                )
            )

        # Write global image quality summary
        if review_artifacts:
            write_image_quality_summary(review_artifacts, output_dir)

        self._repository.save_manifest(
            output_dir,
            manifest,
        )

        print("\nImage generation completed.\n")

        return ImageGenerationResult(
            manifest=manifest,
            output_directory=output_dir,
        )
