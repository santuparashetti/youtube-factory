from __future__ import annotations

from pathlib import Path

from .base import TTSProvider


class KokoroProvider(TTSProvider):
    """Placeholder Kokoro TTS provider."""

    def generate(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        language: str = "en",
    ) -> Path:
        raise NotImplementedError(
            "Kokoro provider implementation will be added in the next step."
        )