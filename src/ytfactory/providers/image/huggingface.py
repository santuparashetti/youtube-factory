from __future__ import annotations

import time

from huggingface_hub import InferenceClient
from PIL import Image

from ytfactory.config.settings import Settings
from ytfactory.domain.image import (
    ImageRequest,
    ImageResponse,
)

from .base import ImageProvider


class HuggingFaceImageProvider(ImageProvider):
    """Hugging Face image generation provider."""

    def __init__(self, settings: Settings):
        self._settings = settings

        self._client = InferenceClient(
            token=settings.hf_token,
        )

    def generate(
        self,
        request: ImageRequest,
    ) -> ImageResponse:

        start = time.perf_counter()

        image = self._client.text_to_image(
            prompt=(
                "Ultra realistic cinematic YouTube thumbnail style, "
                "16:9 landscape composition, "
                "wide shot, "
                "1920x1080 framing. "
                + request.prompt
            ),
            model=self._settings.hf_image_model,
        )

        request.output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        image = image.convert("RGB")

        image = self._fit_to_youtube(
            image=image,
            width=request.width,
            height=request.height,
        )

        image.save(
            request.output_path,
            format="PNG",
        )

        elapsed = time.perf_counter() - start

        return ImageResponse(
            file=request.output_path,
            provider="huggingface",
            width=request.width,
            height=request.height,
            generation_time=elapsed,
        )

    def _fit_to_youtube(
        self,
        image: Image.Image,
        width: int,
        height: int,
    ) -> Image.Image:
        """
        Produce an exact 1920x1080 (16:9) image.

        - Never stretches.
        - Never adds black bars.
        - Center crops if needed.
        """

        target_ratio = width / height

        current_ratio = image.width / image.height

        if current_ratio > target_ratio:
            # Wider than target -> crop left/right
            new_width = int(image.height * target_ratio)
            left = (image.width - new_width) // 2

            image = image.crop(
                (
                    left,
                    0,
                    left + new_width,
                    image.height,
                )
            )

        elif current_ratio < target_ratio:
            # Taller than target -> crop top/bottom
            new_height = int(image.width / target_ratio)
            top = (image.height - new_height) // 2

            image = image.crop(
                (
                    0,
                    top,
                    image.width,
                    top + new_height,
                )
            )

        return image.resize(
            (
                width,
                height,
            ),
            Image.Resampling.LANCZOS,
        )