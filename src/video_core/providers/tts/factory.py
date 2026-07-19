from __future__ import annotations

from video_core.config.shared_settings import SharedSettings

from .base import TTSProvider
from .edge_tts import EdgeTTSProvider
from .voice_profiles import get_voice_profile


def get_tts_provider(settings: SharedSettings) -> TTSProvider:
    """Return the configured TTS provider.

    Resolution is driven entirely by ``TTS_PROVIDER``. The provider-agnostic
    ``VOICE_PROFILE`` is resolved and passed to providers that support it
    (currently Cartesia). Adding a new provider requires only one ``case``
    branch here plus one provider class — nothing else in the pipeline changes.
    """
    match settings.tts_provider.lower():
        case "edge":
            return EdgeTTSProvider(settings)

        case "kokoro":
            from .kokoro import KokoroProvider

            return KokoroProvider(settings)

        case "cartesia":
            from .cartesia import CartesiaTTSProvider

            profile = get_voice_profile(getattr(settings, "voice_profile", ""))
            return CartesiaTTSProvider(settings, profile=profile)

        case "elevenlabs":
            raise ValueError(
                "ElevenLabs TTS is not implemented. "
                "Valid options: edge, kokoro, cartesia"
            )

        case _:
            raise ValueError(
                f"Unsupported TTS provider: {settings.tts_provider!r}. "
                "Valid options: edge, kokoro, cartesia"
            )
