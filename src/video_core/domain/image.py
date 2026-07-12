from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ImageRequest:
    """Normalized image generation request."""

    prompt: str

    output_path: Path

    # Native YouTube Full HD
    width: int = 1920
    height: int = 1080

    negative_prompt: str | None = None

    seed: int | None = None

    guidance_scale: float = 7.5

    steps: int = 30

    model: str | None = None


@dataclass(slots=True)
class ImageResponse:
    """Normalized image generation response."""

    file: Path

    provider: str

    width: int

    height: int

    generation_time: float = 0.0
