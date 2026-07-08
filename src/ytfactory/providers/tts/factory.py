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
            raise NotImplementedError(
                "ElevenLabs TTS is not yet implemented. "
                "Set TTS_PROVIDER=edge in your .env to use Edge TTS. "
                "To add ElevenLabs: implement providers/tts/elevenlabs.py "
                "subclassing TTSProvider, then add a case here."
            )

        case _:
            raise ValueError(
                f"Unsupported TTS provider: {settings.tts_provider!r}. "
                f"Valid values: edge, kokoro, elevenlabs (coming soon)."
            )
