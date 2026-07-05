from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AudioRequest:
    """Normalized audio generation request."""

    text: str

    output_path: Path

    voice: str = "en-US-AndrewNeural"

    rate: str = "+0%"

    volume: str = "+0%"

    pitch: str = "+0Hz"


@dataclass(slots=True)
class AudioResponse:
    """Normalized audio generation response."""

    file: Path

    provider: str

    generation_time: float = 0.0
