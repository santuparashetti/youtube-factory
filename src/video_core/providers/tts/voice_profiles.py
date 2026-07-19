"""
Voice Profile abstraction — provider-independent narration configuration.

The pipeline references a ``VOICE_PROFILE`` (e.g. ``atma_theory``) instead of
provider-specific knobs (voice IDs, speeds, models). Each profile declares the
underlying provider and the voice/style/pacing settings it needs.

Adding a new narration style requires only one registry entry here — no changes
to the providers, factory, or pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NarrationStyle(str, Enum):
    """High-level narration intent a profile is tuned for."""

    DOCUMENTARY = "documentary"
    NARRATION = "narration"
    STORYTELLING = "storytelling"
    MEDITATION = "meditation"


class Emotion(str, Enum):
    """Emotional register a profile applies (provider permitting)."""

    CALM = "calm"
    NEUTRAL = "neutral"
    WARM = "warm"
    SOLEMN = "solemn"


class PacingProfile(str, Enum):
    """Pacing preset consumed by the contemplative pacing engine."""

    SPIRITUAL = "spiritual"
    DOCUMENTARY = "documentary"
    NORMAL = "normal"
    MEDITATION = "meditation"
    SLOW_REFLECTION = "slow_reflection"


@dataclass(frozen=True)
class VoiceProfile:
    """Immutable, provider-independent descriptor of a narration voice."""

    name: str
    provider: str
    voice: str
    speed: float
    narration_style: NarrationStyle
    emotion: Emotion
    pacing_profile: PacingProfile
    language: str = "en"

    def model_name(self, settings) -> str:
        """Resolve the model for this profile's provider from settings."""
        mapping = {
            "cartesia": getattr(settings, "cartesia_model", "sonic-3.5"),
            "kokoro": getattr(settings, "kokoro_model", None),
            "edge": None,
        }
        return mapping.get(self.provider)

    def extra_settings(self, settings) -> dict:
        """Provider-specific settings relevant to this profile."""
        if self.provider == "cartesia":
            return {
                "output_format": getattr(settings, "cartesia_output_format", "wav"),
                "timeout": getattr(settings, "cartesia_timeout", 60),
                "max_chars": getattr(settings, "cartesia_max_chars", 2000),
                "cache_enabled": getattr(settings, "cartesia_cache_enabled", True),
                "pronunciation_dict_id": getattr(
                    settings, "cartesia_pronunciation_dict_id", ""
                ),
                "sample_rate": getattr(settings, "cartesia_sample_rate", 44100),
                "emotion": getattr(settings, "cartesia_emotion", "calm"),
            }
        return {}


# ── Registry ─────────────────────────────────────────────────────────────────

_VOICE_PROFILES: dict[str, VoiceProfile] = {
    "atma_theory": VoiceProfile(
        name="atma_theory",
        provider="cartesia",
        voice="",  # resolved from CARTESIA_VOICE_ID at runtime
        speed=0.84,
        narration_style=NarrationStyle.DOCUMENTARY,
        emotion=Emotion.CALM,
        pacing_profile=PacingProfile.SPIRITUAL,
    ),
}


def register_voice_profile(profile: VoiceProfile) -> None:
    """Register (or override) a voice profile. Call before provider resolution."""
    _VOICE_PROFILES[profile.name] = profile


def get_voice_profile(name: str | None) -> VoiceProfile:
    """Return the requested voice profile, falling back to the default.

    Raises ValueError if an explicit (non-empty) name is unknown.
    """
    if not name:
        return _VOICE_PROFILES["atma_theory"]
    if name not in _VOICE_PROFILES:
        raise ValueError(
            f"Unknown VOICE_PROFILE={name!r}. "
            f"Available: {', '.join(sorted(_VOICE_PROFILES))}"
        )
    return _VOICE_PROFILES[name]


def list_voice_profiles() -> list[str]:
    """Return all registered voice profile names."""
    return sorted(_VOICE_PROFILES)
