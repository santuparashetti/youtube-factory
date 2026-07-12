"""Pollinations.ai image provider — free, no API key, FLUX-backed."""

from __future__ import annotations

import io
import time
from urllib.parse import quote

import requests
from loguru import logger
from PIL import Image

from video_core.config.shared_settings import SharedSettings
from video_core.domain.image import ImageRequest, ImageResponse

from .base import ImageProvider

_API_BASE = "https://image.pollinations.ai/prompt"

# Available models on Pollinations (free, no key)
#   flux          — FLUX.1-schnell (default, fast)
#   flux-realism  — photorealistic variant
#   flux-3d       — 3D render style
#   turbo         — SDXL Turbo
POLLINATIONS_MODEL = "flux-realism"


class PollinationsImageProvider(ImageProvider):
    """
    Free image generation via Pollinations.ai.
    No API key, no rate limits, no signup required.
    Backed by FLUX.1 — same model as HuggingFace's paid inference endpoint.
    """

    def __init__(self, settings: SharedSettings):
        self._settings = settings
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "youtube-factory/0.1"})

    def generate(
        self,
        request: ImageRequest,
    ) -> ImageResponse:

        start = time.perf_counter()

        # Claude-generated prompts are already highly specific — pass them through directly.
        # The prefix below was useful for short/vague prompts but overrides specific
        # camera/composition choices baked into Claude's visual prompts (e.g. "wide shot"
        # conflicts with a scene written for a close-up or mid-frame composition).
        # enriched_prompt = (
        #     "Ultra realistic cinematic YouTube documentary style, "
        #     "16:9 landscape composition, wide shot, 1920x1080 framing, "
        #     "professional photography, sharp focus, high detail. "
        #     + request.prompt
        # )
        enriched_prompt = request.prompt

        params: dict[str, str | int] = {
            "width": request.width,
            "height": request.height,
            "model": POLLINATIONS_MODEL,
            "nologo": "true",
            "enhance": "false",  # we already write detailed prompts
        }

        if request.negative_prompt:
            params["negative"] = request.negative_prompt

        if request.seed is not None:
            params["seed"] = request.seed

        url = f"{_API_BASE}/{quote(enriched_prompt, safe='')}"

        response = None
        for attempt in range(5):
            response = self._session.get(url, params=params, timeout=120)
            if response.status_code == 429:
                wait = 20 * (2**attempt)  # 20, 40, 80, 160, 320s
                logger.warning(
                    "Pollinations 429 rate limit — waiting {}s (attempt {})",
                    wait,
                    attempt + 1,
                )
                time.sleep(wait)
                continue
            response.raise_for_status()
            break
        else:
            response.raise_for_status()  # re-raise after 5 failed attempts

        image = Image.open(io.BytesIO(response.content)).convert("RGB")

        # Fit / crop to exact YouTube dimensions (same logic as HuggingFace provider)
        image = self._fit_to_youtube(image, request.width, request.height)

        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(request.output_path, format="PNG")

        elapsed = time.perf_counter() - start

        return ImageResponse(
            file=request.output_path,
            provider="pollinations",
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
        """Center-crop to exact target ratio then resize. Never stretches."""
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
