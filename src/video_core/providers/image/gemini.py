"""Gemini image generation provider."""

from __future__ import annotations

import io
import time

from google import genai
from google.genai import types
from loguru import logger
from PIL import Image
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from video_core.config.shared_settings import SharedSettings
from video_core.domain.image import ImageRequest, ImageResponse

from .base import ImageProvider


class GeminiImageProvider(ImageProvider):
    """
    Google Gemini image generation via generate_content with IMAGE modality.
    Works with gemini-3.1-flash-lite-image, gemini-2.0-flash-preview-image-generation, etc.
    """

    def __init__(self, settings: SharedSettings):
        self._settings = settings
        if not settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. "
                "Add it to your .env file, or set IMAGE_PROVIDER to a different provider "
                "(e.g. IMAGE_PROVIDER=huggingface). "
                "Make sure you run ytfactory from the repo root so .env is found."
            )
        self._client = genai.Client(api_key=settings.gemini_api_key)

    @retry(
        retry=retry_if_exception_type(RuntimeError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=30),
        reraise=True,
    )
    def generate(self, request: ImageRequest) -> ImageResponse:
        start = time.perf_counter()

        prompt = (
            "Generate a high-quality photorealistic cinematic image in 16:9 landscape "
            "format for a YouTube documentary. Ultra realistic, professional photography, "
            "sharp focus, high detail, no text or watermarks. " + request.prompt
        )
        if request.negative_prompt:
            prompt += f"\n\nDo NOT include: {request.negative_prompt}"

        model = self._settings.gemini_image_model
        logger.info("Generating image via Gemini — model: {}", model)

        try:
            response = self._client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini image generation failed: {exc}") from exc

        # Extract image bytes from the first image part
        image_bytes: bytes | None = None
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                image_bytes = part.inline_data.data
                break

        if not image_bytes:
            raise RuntimeError(
                f"Gemini returned no image. "
                f"Finish reason: {response.candidates[0].finish_reason}"
            )

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image = self._fit_to_target(image, request.width, request.height)

        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(request.output_path, format="PNG")

        elapsed = time.perf_counter() - start
        logger.info(
            "Gemini image generated in {:.1f}s — {}×{}",
            elapsed,
            request.width,
            request.height,
        )

        return ImageResponse(
            file=request.output_path,
            provider="gemini",
            width=request.width,
            height=request.height,
            generation_time=elapsed,
        )

    def _fit_to_target(
        self, image: Image.Image, width: int, height: int
    ) -> Image.Image:
        """Center-crop to target 16:9 ratio then resize. Never stretches."""
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
