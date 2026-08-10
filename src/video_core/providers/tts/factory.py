from __future__ import annotations

from video_core.config.shared_settings import SharedSettings

from .analytics.collector import TTSAnalyticsCollector
from .base import TTSProvider
from .edge_tts import EdgeTTSProvider
from .voice_profiles import get_voice_profile


def get_tts_provider(
    settings: SharedSettings,
    *,
    analytics: TTSAnalyticsCollector | None = None,
) -> TTSProvider:
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
            return CartesiaTTSProvider(
                settings,
                profile=profile,
                analytics=analytics,
            )

        case "elevenlabs":
            from .elevenlabs import ElevenLabsProvider

            profile = get_voice_profile(getattr(settings, "voice_profile", ""))
            return ElevenLabsProvider(
                settings,
                profile=profile,
                analytics=analytics,
            )

        case "fish":
            from .fish_provider import FishProvider

            return FishProvider(
                settings,
                analytics=analytics,
            )

        case "speechify":
            from .speechify import SpeechifyProvider

            return SpeechifyProvider(
                settings,
                analytics=analytics,
            )

        case _:
            raise ValueError(
                f"Unsupported TTS provider: {settings.tts_provider!r}. "
                "Valid options: edge, kokoro, cartesia, elevenlabs, fish, speechify"
            )
