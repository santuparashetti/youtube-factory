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
    # V2 legacy value — used when adaptive_mixing=False.
    phrase_gap_ms: int = 300

    # Silence duration (ms) after which music recovers to full volume (V2).
    # Overridden by long_silence_threshold_ms when adaptive_mixing=True.
    long_silence_ms: int = 2500

    # Vary duck depth with narration energy (louder → deeper duck).
    # Implemented naturally by sidechaincompress — this flag gates debug output.
    dynamic_ducking: bool = True

    # Volume recovery curve after long silence.
    # "logarithmic" matches the natural sidechaincompress release envelope.
    restore_curve: str = "logarithmic"

    # ── V3: Adaptive State-Machine Mixing ────────────────────────────────────

    # Enable V3 adaptive mixing. When True, uses hold_after_speech_ms for the
    # agate hold and V3 attack/release values. When False, falls back to V2
    # phrase_gap_ms + the original duck_attack_ms / duck_release_ms values.
    adaptive_mixing: bool = True

    # Duration (ms) music stays ducked after speech ends before beginning
    # recovery. Bridges breaths, commas, dramatic pauses, and sentence pauses.
    # Only silence longer than this allows music to rise (MUSIC_FEATURE state).
    hold_after_speech_ms: int = 2200

    # Threshold (ms) above which a gap is classified as "long_silence" (vs
    # dramatic_pause). Used by PauseClassifier and review rules only — the
    # actual recovery is controlled by hold_after_speech_ms + duck_release_ms.
    long_silence_threshold_ms: int = 2500

    # Target narration level in LUFS (for review checks only; not applied to signal).
    narration_level_lufs: float = -30.0

    # Target music level in LUFS during narration (for review checks only).
    music_level_lufs: float = -17.0

    # Duck curve shape. "ease_in_out" means gentle acceleration at start and
    # end of each transition (implemented via the sidechaincompress envelope).
    transition_curve: str = "ease_in_out"
