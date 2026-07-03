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

    # Default voice per BCP-47 language code
    _VOICES: dict[str, str] = {
        "en": "en-US-AndrewNeural",
        "en-US": "en-US-AndrewNeural",
        "en-GB": "en-GB-RyanNeural",
        "es": "es-ES-AlvaroNeural",
        "fr": "fr-FR-HenriNeural",
        "de": "de-DE-ConradNeural",
        "hi": "hi-IN-MadhurNeural",
        "mr": "mr-IN-ManoharNeural",
        "ja": "ja-JP-KeitaNeural",
        "zh": "zh-CN-YunxiNeural",
        "pt": "pt-BR-AntonioNeural",
        "ar": "ar-SA-HamedNeural",
        "ru": "ru-RU-DmitryNeural",
        "ko": "ko-KR-InJoonNeural",
        "it": "it-IT-DiegoNeural",
    }

    def _resolve_voice(self, voice: str | None, language: str) -> str:
        if voice:
            return voice
        return self._VOICES.get(language, self._VOICES["en"])

    def generate(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        language: str = "en",
    ) -> Path:

        resolved_voice = self._resolve_voice(voice, language)

        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self._synthesize(text=text, output_path=output_path, voice=resolved_voice),
                )
                future.result()
        except RuntimeError:
            asyncio.run(
                self._synthesize(text=text, output_path=output_path, voice=resolved_voice)
            )

        return output_path