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
    bgm_volume: float = 0.30

    # Minimum BGM level during active speech (0.0–bgm_volume).
    # Music never drops below this floor even at maximum narration amplitude.
    duck_floor: float = 0.04

    # Sidechain compress threshold: amplitude above which ducking engages.
    # 0.008 ≈ -42 dBFS — sensitive enough to catch speech onset early.
    duck_threshold: float = 0.008

    # Compression ratio — how aggressively the main BGM path ducks.
    # 8.0:1 produces strong ducking while still preserving a floor.
    duck_ratio: float = 8.0

    # Milliseconds for ducking to engage after speech onset.
    # 15 ms: near-instantaneous — BGM ducks before the word lands.
    duck_attack_ms: int = 15

    # Milliseconds for music to recover after speech ends.
    # 350 ms: fast enough to fill sentence gaps, slow enough to avoid pumping.
    duck_release_ms: int = 350

    # Fade-in duration at the very start of the video.
    fade_in_seconds: float = 1.5

    # Fade-out duration at the very end of the video.
    fade_out_seconds: float = 2.5

    # Crossfade duration between successive loops of the music track.
    crossfade_seconds: float = 2.0

    # When multiple tracks exist in the selected category, pick randomly.
    random_track: bool = True

    # AAC bitrate for the final mixed audio track.
    audio_bitrate: str = "192k"

    # ── V2: VAD-assisted adaptive ducking ────────────────────────────────────

    # Enable VAD pre-analysis for phrase grouping and debug output.
    # When True, an agate filter is added to the sidechain to suppress
    # inter-word pumping; debug files are written to bgm-debug/.
    vad_enabled: bool = True

    # VAD backend — "silero" preferred per spec; current implementation uses
    # FFmpeg silencedetect (no extra deps). Reserved for future Silero support.
    vad_provider: str = "silero"

    # Gap (ms) between speech bursts treated as one continuous phrase.
    # The agate hold parameter is set to this value so music stays ducked
    # across brief inter-word pauses.
    phrase_gap_ms: int = 300

    # Silence duration (ms) after which music recovers to full volume.
    # Used by review rules to verify recovery timing.
    long_silence_ms: int = 2000

    # Vary duck depth with narration energy (louder → deeper duck).
    # Implemented naturally by sidechaincompress — this flag gates debug output.
    dynamic_ducking: bool = True

    # Volume recovery curve after long silence.
    # "logarithmic" matches the natural sidechaincompress release envelope.
    restore_curve: str = "logarithmic"
