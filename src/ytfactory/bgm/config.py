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
    # 0.35 = 35% — clearly audible ambient presence during silence between sentences.
    bgm_volume: float = 0.35

    # Minimum BGM level during active speech (0.0–bgm_volume).
    # Music never drops below this level even at maximum narration amplitude.
    # 0.05 = 5% floor — ensures music stays present but well behind narration.
    duck_floor: float = 0.05

    # Sidechain compress threshold: amplitude above which ducking engages.
    # ~0.02 ≈ -34 dBFS — detects the onset of speech without false-triggering
    # on room noise or breath sounds.
    duck_threshold: float = 0.02

    # Compression ratio — how aggressively the main BGM path ducks.
    # 2.5:1 is a gentle duck: music drops to ~11% during strong narration
    # while remaining clearly audible as a background presence.
    duck_ratio: float = 2.5

    # Milliseconds for ducking to fully engage after speech onset.
    # 50 ms: fast enough to duck before the listener hears the BGM clash.
    duck_attack_ms: int = 50

    # Milliseconds for music to recover after speech ends.
    # 600 ms: snappy enough to fill sentence gaps without feeling sluggish.
    duck_release_ms: int = 600

    # Fade-in duration at the very start of the video.
    # 1.5 s: music rises naturally under the opening hook.
    fade_in_seconds: float = 1.5

    # Fade-out duration at the very end of the video.
    # 2.5 s: smooth, unhurried exit.
    fade_out_seconds: float = 2.5

    # Crossfade duration between successive loops of the music track.
    # 2 s overlap prevents audible clicks at loop boundaries.
    crossfade_seconds: float = 2.0

    # When multiple tracks exist in the selected category, pick randomly.
    random_track: bool = True

    # AAC bitrate for the final mixed audio track.
    audio_bitrate: str = "192k"
