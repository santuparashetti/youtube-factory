from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts

from ytfactory.config.settings import Settings

from .base import TTSProvider


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge Text-to-Speech provider."""

    def __init__(self, settings: Settings):
        self._settings = settings

    async def _synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str,
    ) -> None:
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
        )

        await communicate.save(str(output_path))

    def generate(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        language: str = "en",
    ) -> Path:

        asyncio.run(
            self._synthesize(
                text=text,
                output_path=output_path,
                voice=voice or "en-US-AndrewNeural",
            )
        )

        return output_path