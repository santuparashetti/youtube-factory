"""Automatic1111 Stable Diffusion WebUI image provider — local, free, unlimited.

## Setup (one-time)

1. Install A1111:
       git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui
       cd stable-diffusion-webui

2. Download a high-quality checkpoint from https://civitai.com — recommended:
       • Juggernaut XL v9       → photorealistic, best for documentary style
       • DreamShaper XL         → cinematic, versatile
       • RealVisXL V4.0         → hyperrealistic
   Place the .safetensors file in: stable-diffusion-webui/models/Stable-diffusion/

3. Launch with API enabled:
       ./webui.sh --api          # Linux/Mac
       webui-user.bat --api      # Windows

4. Set in .env:
       IMAGE_PROVIDER=a1111
       # A1111_BASE_URL=http://localhost:7860    (default)
       # A1111_STEPS=30
       # A1111_CFG_SCALE=7.0
       # A1111_SAMPLER=DPM++ 2M Karras
"""

from __future__ import annotations

import base64
import io
import time

import requests
from loguru import logger
from PIL import Image

from ytfactory.config.settings import Settings
from ytfactory.domain.image import ImageRequest, ImageResponse

from .base import ImageProvider


class A1111ImageProvider(ImageProvider):
    """
    Automatic1111 WebUI API provider.
    Requires local A1111 running with --api flag.
    """

    def __init__(self, settings: Settings):
        self._base_url = settings.a1111_base_url.rstrip("/")
        self._steps = settings.a1111_steps
        self._cfg_scale = settings.a1111_cfg_scale
        self._sampler = settings.a1111_sampler
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    def generate(self, request: ImageRequest) -> ImageResponse:
        start = time.perf_counter()

        payload = {
            "prompt": (
                "ultra realistic cinematic documentary photograph, "
                "16:9 widescreen, professional photography, "
                "sharp focus, photorealistic, high detail, 8k. "
                + request.prompt
            ),
            "negative_prompt": request.negative_prompt or (
                "text, watermark, logo, words, letters, numbers, subtitles, "
                "blurry, distorted, ugly, low quality, bad anatomy, "
                "cartoon, anime, illustration, painting, drawing, "
                "overexposed, underexposed, duplicate, worst quality"
            ),
            "width": request.width,
            "height": request.height,
            "steps": self._steps,
            "cfg_scale": self._cfg_scale,
            "sampler_name": self._sampler,
            "seed": request.seed if request.seed is not None else -1,
        }

        try:
            response = self._session.post(
                f"{self._base_url}/sdapi/v1/txt2img",
                json=payload,
                timeout=300,
            )
        except requests.ConnectionError as exc:
            raise requests.ConnectionError(
                f"Cannot reach Automatic1111 at {self._base_url}. "
                "Is it running with --api?  Start it with: ./webui.sh --api"
            ) from exc

        response.raise_for_status()
        data = response.json()

        image_b64 = data["images"][0]
        image = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")

        if image.size != (request.width, request.height):
            image = image.resize((request.width, request.height), Image.Resampling.LANCZOS)

        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(request.output_path, format="PNG")

        elapsed = time.perf_counter() - start
        logger.info(
            "A1111 generated scene image in {:.1f}s — {}×{}",
            elapsed, request.width, request.height,
        )

        return ImageResponse(
            file=request.output_path,
            provider="a1111",
            width=request.width,
            height=request.height,
            generation_time=elapsed,
        )
