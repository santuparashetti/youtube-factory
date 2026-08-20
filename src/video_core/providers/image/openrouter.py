"""OpenRouter image generation provider (OpenAI-compatible API)."""

from __future__ import annotations

import base64
import io
import time

import httpx
from loguru import logger
from openai import OpenAI
from PIL import Image
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from video_core.config.shared_settings import SharedSettings
from video_core.domain.image import ImageRequest, ImageResponse

from .base import ImageProvider

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class OpenRouterImageProvider(ImageProvider):
    """
    Image generation via OpenRouter's OpenAI-compatible API.
    Supports any model OpenRouter exposes for image generation,
    e.g. black-forest-labs/flux.2-klein-4b.

    Required settings:
      ANTHROPIC_API_KEY   — your OpenRouter API key (sk-or-v1-...)
      ANTHROPIC_BASE_URL  — https://openrouter.ai/api/v1  (default)
      OPENROUTER_IMAGE_MODEL — model id, e.g. black-forest-labs/flux.2-klein-4b
    """

    def __init__(self, settings: SharedSettings):
        self._settings = settings
        api_key = settings.anthropic_api_key
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY (OpenRouter key) is not set. "
                "Add it to your .env file."
            )
        base_url = settings.anthropic_base_url or _OPENROUTER_BASE
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._model = getattr(settings, "openrouter_image_model", "black-forest-labs/flux.2-klein-4b")

    @retry(
        retry=retry_if_exception_type((RuntimeError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=30),
        reraise=True,
    )
    def generate(self, request: ImageRequest) -> ImageResponse:
        start = time.perf_counter()

        prompt = request.prompt
        if request.negative_prompt:
            prompt += f"\n\nDo NOT include: {request.negative_prompt}"

        logger.info("Generating image via OpenRouter — model: {}", self._model)

        try:
            response = self._client.images.generate(
                model=self._model,
                prompt=prompt,
                n=1,
                size="1536x864",  # closest 16:9 OpenRouter accepts; we resize to target
                response_format="b64_json",
            )
        except Exception as exc:
            raise RuntimeError(f"OpenRouter image generation failed: {exc}") from exc

        b64 = response.data[0].b64_json
        if not b64:
            raise RuntimeError("OpenRouter returned no image data")

        image_bytes = base64.b64decode(b64)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image = self._fit_to_target(image, request.width, request.height)

        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(request.output_path, format="PNG")

        elapsed = time.perf_counter() - start
        logger.info(
            "OpenRouter image generated in {:.1f}s — {}×{}",
            elapsed,
            request.width,
            request.height,
        )

        return ImageResponse(
            file=request.output_path,
            provider="openrouter",
            width=request.width,
            height=request.height,
            generation_time=elapsed,
        )

    def _fit_to_target(self, image: Image.Image, width: int, height: int) -> Image.Image:
        """Center-crop to target 16:9 ratio then resize."""
        target_ratio = width / height
        current_ratio = image.width / image.height

        if current_ratio > target_ratio:
            new_width = int(image.height * target_ratio)
            left = (image.width - new_width) // 2
            image = image.crop((left, 0, left + new_width, image.height))
        elif current_ratio < target_ratio:
            new_height = int(image.width / target_ratio)
            top = (image.height - new_height) // 2
            image = image.crop((0, top, image.width, top + new_height))

        return image.resize((width, height), Image.Resampling.LANCZOS)
