from __future__ import annotations

from ytfactory.config.settings import Settings

from .base import TTSProvider
from .edge_tts import EdgeTTSProvider


def get_tts_provider(settings: Settings) -> TTSProvider:
    """Return configured TTS provider."""

    match settings.tts_provider.lower():
        case "edge":
            return EdgeTTSProvider(settings)

        case "kokoro":
            from .kokoro import KokoroProvider

            return KokoroProvider(settings)

        case "elevenlabs":
            raise ValueError(
                "ElevenLabs TTS is not implemented. "
                "Valid options: edge, kokoro"
            )

        case _:
            raise ValueError(
                f"Unsupported TTS provider: {settings.tts_provider!r}. "
                "Valid options: edge, kokoro"
            )
