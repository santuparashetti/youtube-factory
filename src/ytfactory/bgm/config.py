"""BGMConfig — all configurable parameters for Background Music mixing."""

from __future__ import annotations

from dataclasses import dataclass


CATEGORIES: list[str] = [
    "spiritual",
    "meditation",
    "cinematic_ambient",
    "emotional_documentary",
    "inspirational",
    "calm_piano",
    "nature_ambient",
]

DEFAULT_CATEGORY = "spiritual"


@dataclass
class BGMConfig:
    """Configuration for the Background Music pipeline."""

    # Master switch — False means no BGM processing at all
    enabled: bool = False

    # "auto" selects based on video topic; or name a CATEGORIES value directly
    category: str = "auto"

    # Directory containing music tracks.
    # Subdirectory layout:  library_path/<category>/*.mp3
    # Flat layout:          library_path/*.mp3
    library_path: str = "workspace/music"

    # BGM volume relative to full scale (0.0–1.0) during quiet/pause sections.
    # 0.12 = 12% — subtle; clearly secondary to narration.
    bgm_volume: float = 0.12

    # Sidechain compress threshold: amplitude above which ducking engages.
    # ~0.02 ≈ -34 dBFS — detects the onset of speech without false-triggering
    # on room noise or breath sounds.
    duck_threshold: float = 0.02

    # Compression ratio — how aggressively to duck when threshold is exceeded.
    # 6:1 reduces 12% music to ~2% while speech is active.
    duck_ratio: float = 6.0

    # Milliseconds for ducking to fully engage after speech onset.
    duck_attack_ms: int = 200

    # Milliseconds for music to recover after speech ends.
    # 1000 ms gives a smooth "breathe back in" feel between sentences.
    duck_release_ms: int = 1000

    # Fade-in duration at the very start of the video.
    fade_in_seconds: float = 3.0

    # Fade-out duration at the very end of the video.
    fade_out_seconds: float = 4.0

    # Crossfade duration between successive loops of the music track.
    # 2 s overlap prevents audible clicks at loop boundaries.
    crossfade_seconds: float = 2.0

    # When multiple tracks exist in the selected category, pick randomly.
    random_track: bool = True

    # AAC bitrate for the final mixed audio track.
    audio_bitrate: str = "192k"
