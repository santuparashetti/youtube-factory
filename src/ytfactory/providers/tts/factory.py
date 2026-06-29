from __future__ import annotations

from ytfactory.config.settings import Settings

from .base import TTSProvider
from .kokoro import KokoroProvider


def get_tts_provider() -> TTSProvider:
    settings = Settings()

    provider = settings.tts_provider.lower()

    if provider == "kokoro":
        return KokoroProvider()

    raise ValueError(f"Unsupported TTS provider: {provider}")