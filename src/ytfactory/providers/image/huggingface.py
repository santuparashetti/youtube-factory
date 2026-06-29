from __future__ import annotations

import time

from huggingface_hub import InferenceClient

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
            request.prompt,
            model=self._settings.hf_image_model,
        )

        request.output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        image.save(request.output_path)

        elapsed = time.perf_counter() - start

        return ImageResponse(
            file=request.output_path,
            provider="huggingface",
            width=request.width,
            height=request.height,
            generation_time=elapsed,
        )