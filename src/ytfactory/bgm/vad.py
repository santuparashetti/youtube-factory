"""Voice Activity Detection for BGM adaptive ducking.

Uses FFmpeg silencedetect to build a phrase-level SpeechTimeline.
No external Python dependencies — relies only on the ffmpeg/ffprobe
binaries already required by the rest of the pipeline.

Optional Silero VAD can be added later by swapping the backend in
detect_speech(); the public API and data model stay identical.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SpeechSegment:
    """One continuous speech phrase detected in the narration."""

    start: float
    end: float
    energy: float = 1.0  # normalised 0–1 (1.0 = full energy)

    @property
    def duration(self) -> float:  # noqa: D401
        return max(0.0, self.end - self.start)


@dataclass
class SpeechTimeline:
    """Complete speech-activity map for a narration track."""

    segments: list[SpeechSegment] = field(default_factory=list)
    total_duration: float = 0.0
    speech_ratio: float = 0.0  # fraction of timeline occupied by speech

    def to_dict(self) -> dict:
        return {
            "total_duration": round(self.total_duration, 3),
            "speech_ratio": round(self.speech_ratio, 3),
            "segment_count": len(self.segments),
            "segments": [
                {
                    "start": round(s.start, 3),
                    "end": round(s.end, 3),
                    "duration": round(s.duration, 3),
                    "energy": round(s.energy, 3),
                }
                for s in self.segments
            ],
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_speech(
    audio_path: Path,
    *,
    silence_threshold_db: float = -40.0,
    phrase_gap_ms: int = 300,
) -> SpeechTimeline:
    """Return a SpeechTimeline from FFmpeg silencedetect on *audio_path*.

    Args:
        audio_path: Any file FFmpeg can decode (MP3, MP4, WAV …).
        silence_threshold_db: dBFS below which audio is considered silence.
        phrase_gap_ms: merge speech segments whose gap is shorter than this.

    Returns an empty SpeechTimeline on any ffmpeg failure.
    """
    total_dur = _probe_duration(audio_path)
    if total_dur <= 0:
        return SpeechTimeline(total_duration=0.0)

    silence_ranges = _run_silencedetect(audio_path, silence_threshold_db)
    speech_segments = _invert_silence(silence_ranges, total_dur)
    phrases = _group_phrases(speech_segments, phrase_gap_ms / 1000.0)

    # Normalised energy from mean dBFS (one volumedetect call for whole track)
    mean_db = _volumedetect_mean(audio_path)
    energy = _db_to_normalised_energy(mean_db)
    for seg in phrases:
        seg.energy = energy

    speech_total = sum(s.duration for s in phrases)
    speech_ratio = round(speech_total / total_dur, 3) if total_dur > 0 else 0.0
    return SpeechTimeline(
        segments=phrases,
        total_duration=total_dur,
        speech_ratio=speech_ratio,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _probe_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def _run_silencedetect(
    path: Path,
    threshold_db: float,
) -> list[tuple[float, float]]:
    """Return list of (start_s, end_s) silence intervals via ffmpeg silencedetect."""
    cmd = [
        "ffmpeg", "-nostdin",
        "-i", str(path),
        "-vn",
        "-af", f"silencedetect=n={threshold_db}dB:d=0.10",
        "-f", "null", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:
        return []

    silences: list[tuple[float, float]] = []
    pending_start: float | None = None

    for line in r.stderr.splitlines():
        m_start = re.search(r"silence_start:\s*(-?\d+\.?\d*)", line)
        if m_start:
            pending_start = float(m_start.group(1))
        m_end = re.search(r"silence_end:\s*(-?\d+\.?\d*)", line)
        if m_end is not None and pending_start is not None:
            silences.append((pending_start, float(m_end.group(1))))
            pending_start = None

    return silences


def _invert_silence(
    silences: list[tuple[float, float]],
    total_dur: float,
) -> list[SpeechSegment]:
    """Convert silence intervals to speech intervals."""
    if not silences:
        # No detected silence — treat entire track as speech
        return [SpeechSegment(start=0.0, end=total_dur)]

    speech: list[SpeechSegment] = []
    cursor = 0.0

    for sil_start, sil_end in sorted(silences):
        if sil_start > cursor + 0.05:
            speech.append(SpeechSegment(start=cursor, end=sil_start))
        cursor = max(cursor, sil_end)

    if cursor < total_dur - 0.05:
        speech.append(SpeechSegment(start=cursor, end=total_dur))

    return speech


def _group_phrases(
    segments: list[SpeechSegment],
    phrase_gap_s: float,
) -> list[SpeechSegment]:
    """Merge speech segments separated by ≤ *phrase_gap_s* into one phrase."""
    if not segments:
        return []

    result = [SpeechSegment(start=segments[0].start, end=segments[0].end)]
    for seg in segments[1:]:
        if seg.start - result[-1].end <= phrase_gap_s:
            result[-1].end = seg.end
        else:
            result.append(SpeechSegment(start=seg.start, end=seg.end))
    return result


def _volumedetect_mean(path: Path) -> float:
    """Return mean volume in dBFS, or -20.0 as a safe default."""
    cmd = [
        "ffmpeg", "-nostdin",
        "-i", str(path),
        "-vn", "-af", "volumedetect", "-f", "null", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        for line in r.stderr.splitlines():
            m = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", line)
            if m:
                return float(m.group(1))
    except Exception:
        pass
    return -20.0


def _db_to_normalised_energy(mean_db: float) -> float:
    """Map mean dBFS to a normalised energy level 0–1.

    Calibration points:
        ≤ −40 dBFS → 0.2  (very quiet)
        −20 dBFS   → 0.8  (normal narration)
        ≥ −10 dBFS → 1.0  (loud)
    """
    if mean_db >= -10.0:
        return 1.0
    if mean_db <= -40.0:
        return 0.2
    # linear interpolation between (−40, 0.2) and (−10, 1.0)
    return 0.2 + (mean_db - (-40.0)) / ((-10.0) - (-40.0)) * (1.0 - 0.2)
