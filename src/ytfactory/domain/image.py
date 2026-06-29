from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ImageRequest:
    """Normalized image generation request."""

    prompt: str

    output_path: Path

    width: int = 1280

    height: int = 720

    negative_prompt: str | None = None

    seed: int | None = None

    guidance_scale: float = 7.5

    steps: int = 30


@dataclass(slots=True)
class ImageResponse:
    """Normalized image generation response."""

    file: Path

    provider: str

    width: int

    height: int

    generation_time: float = 0.0