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
    ) -> Path:
        """Generate speech audio and return the output file path."""
        raise NotImplementedError