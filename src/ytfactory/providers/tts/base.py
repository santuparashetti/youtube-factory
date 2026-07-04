from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSProvider(ABC):
    """Base interface for all text-to-speech providers."""

    @abstractmethod
    def generate(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        language: str = "en",
        style: str | None = None,
    ) -> Path:
        """Generate speech audio and return the output file path."""
        raise NotImplementedError

    def generate_with_boundaries(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        language: str = "en",
        style: str | None = None,
    ) -> tuple[Path, list[dict]]:
        """
        Generate audio and return word-level timing boundaries.

        Returns:
            (output_path, boundaries)
            boundaries: [{word: str, start: float, end: float}] in seconds.

        Default: delegates to generate() and returns empty boundaries.
        Override in providers that support word-level timing (e.g. Edge TTS).
        """
        audio_path = self.generate(
            text, output_path, voice=voice, language=language, style=style
        )
        return audio_path, []
