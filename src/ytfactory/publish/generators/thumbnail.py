"""ThumbnailGenerator — generates 1280×720 YouTube thumbnail + variants."""

from __future__ import annotations

from pathlib import Path

from video_core.domain.image import ImageRequest
from ytfactory.publish.artifacts import thumbnail_path, thumbnail_variants_directory
from ytfactory.publish.config import PublishConfig
from ytfactory.publish.models import ThumbnailResult


_VARIANT_STYLE_HINTS = [
    "close-up portrait style, dramatic lighting",
    "wide establishing shot, vibrant colors",
    "cinematic composition, high contrast",
]


class ThumbnailGenerator:
    def __init__(self, image_provider, config: PublishConfig | None = None):
        self._provider = image_provider
        self._config = config or PublishConfig()

    def generate(
        self,
        project_id: str,
        project_title: str,
        first_scene_visual_prompt: str,
    ) -> ThumbnailResult | None:
        if self._config.skip_thumbnail:
            return None

        w, h = self._config.thumbnail_width, self._config.thumbnail_height

        base_prompt = (
            f"YouTube thumbnail for '{project_title}', "
            f"{first_scene_visual_prompt}, "
            "bold text overlay, high contrast, eye-catching, 16:9 aspect ratio"
        )

        primary = thumbnail_path(project_id)
        self._provider.generate(
            ImageRequest(prompt=base_prompt, output_path=primary, width=w, height=h)
        )

        variants_dir = thumbnail_variants_directory(project_id)
        variant_paths: list[Path] = []
        for i, style_hint in enumerate(
            _VARIANT_STYLE_HINTS[: self._config.thumbnail_variants], start=1
        ):
            variant_prompt = (
                f"YouTube thumbnail for '{project_title}', "
                f"{first_scene_visual_prompt}, {style_hint}, 16:9 aspect ratio"
            )
            variant_path = variants_dir / f"variant-{i}.png"
            self._provider.generate(
                ImageRequest(
                    prompt=variant_prompt, output_path=variant_path, width=w, height=h
                )
            )
            variant_paths.append(variant_path)

        return ThumbnailResult(
            primary_path=primary,
            variant_paths=variant_paths,
            width=w,
            height=h,
        )
