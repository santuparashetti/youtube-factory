"""Voice Activity Detection for BGM adaptive ducking.

Uses FFmpeg silencedetect to build a phrase-level SpeechTimeline.
No external Python dependencies — relies only on the ffmpeg/ffprobe
binaries already required by the rest of the pipeline.

V3 additions:
- PauseType / PauseEvent: classify each gap between speech segments
- PauseClassifier: uses Kokoro word timestamps as primary source,
  falls back to VAD segments when timestamps are absent.
- build_speech_timeline_from_kokoro(): reads all scene timing.json /
  alignment.json files and merges them into a single SpeechTimeline.

Optional Silero VAD can be added later by swapping the backend in
detect_speech(); the public API and data model stay identical.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
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
# V3: Pause classification
# ---------------------------------------------------------------------------


class PauseType(str, Enum):
    """How a gap between speech segments is classified.

    Only LONG_SILENCE may trigger music restoration (MUSIC_FEATURE state).
    All other types keep music ducked (NARRATION_ACTIVE state).
    """

    BREATH = "breath"             # < 200 ms — between words, micro-pause
    COMMA = "comma"               # 200–500 ms — comma or short clause break
    DRAMATIC_PAUSE = "dramatic_pause"   # 500–1500 ms — intentional emphasis
    SENTENCE_PAUSE = "sentence_pause"   # 1500–long_silence_ms — sentence boundary
    LONG_SILENCE = "long_silence"       # > long_silence_threshold_ms — raise music


@dataclass
class PauseEvent:
    """A classified gap between two consecutive speech segments."""

    start: float  # seconds — end of previous segment
    end: float    # seconds — start of next segment
    pause_type: PauseType
    duration: float  # seconds

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
            "pause_type": self.pause_type.value,
        }


def classify_pause(gap_seconds: float, long_silence_threshold_ms: int = 2500) -> PauseType:
    """Return the PauseType for a gap of *gap_seconds* seconds.

    Thresholds (all in seconds):
        < 0.20  → BREATH
        0.20–0.50 → COMMA
        0.50–1.50 → DRAMATIC_PAUSE
        1.50–(long_silence_threshold_ms/1000) → SENTENCE_PAUSE
        ≥ long_silence_threshold_ms/1000 → LONG_SILENCE
    """
    long_s = long_silence_threshold_ms / 1000.0
    if gap_seconds < 0.20:
        return PauseType.BREATH
    if gap_seconds < 0.50:
        return PauseType.COMMA
    if gap_seconds < 1.50:
        return PauseType.DRAMATIC_PAUSE
    if gap_seconds < long_s:
        return PauseType.SENTENCE_PAUSE
    return PauseType.LONG_SILENCE


class PauseClassifier:
    """Classify pauses in a SpeechTimeline.

    Primary source: Kokoro word timestamps (timing.json / alignment.json).
    Fallback: SpeechTimeline segments from VAD.

    Usage::

        classifier = PauseClassifier(long_silence_threshold_ms=2500)
        events = classifier.classify(timeline)
    """

    def __init__(self, long_silence_threshold_ms: int = 2500) -> None:
        self._threshold_ms = long_silence_threshold_ms

    def classify(self, timeline: SpeechTimeline) -> list[PauseEvent]:
        """Return a PauseEvent for each gap between segments in *timeline*."""
        events: list[PauseEvent] = []
        segs = timeline.segments
        for i in range(len(segs) - 1):
            gap_start = segs[i].end
            gap_end = segs[i + 1].start
            gap_dur = max(0.0, gap_end - gap_start)
            events.append(
                PauseEvent(
                    start=gap_start,
                    end=gap_end,
                    pause_type=classify_pause(gap_dur, self._threshold_ms),
                    duration=gap_dur,
                )
            )
        return events


# ---------------------------------------------------------------------------
# V3: Kokoro timestamp reader
# ---------------------------------------------------------------------------


def _load_timing_json(path: Path) -> list[dict]:
    """Load scene-NNN.timing.json → list of {word, start, end} dicts."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _load_alignment_json(path: Path) -> list[dict]:
    """Load scene-NNN.alignment.json → list of {word, start, end} dicts."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        words = data.get("words", [])
        if isinstance(words, list):
            return words
    except Exception:
        pass
    return []


def build_speech_timeline_from_kokoro(
    project_dir: Path,
    *,
    phrase_gap_ms: int = 300,
    long_silence_threshold_ms: int = 2500,
) -> SpeechTimeline | None:
    """Build a SpeechTimeline from Kokoro word timestamps across all scenes.

    Reads ``audio/scene-NNN.alignment.json`` (WhisperX, preferred) then
    ``audio/scene-NNN.timing.json`` (TTS boundaries, fallback) for each scene.

    Each scene's words are offset by the scene's cumulative start time.  The
    function estimates scene offsets by summing the last ``end`` value of the
    previous scene (plus a small inter-scene gap of 0.1 s).

    Returns None when no timing files are found (caller falls back to VAD).
    """
    audio_dir = project_dir / "audio"
    if not audio_dir.exists():
        return None

    all_words: list[dict] = []
    cursor = 0.0  # cumulative start time of current scene

    # Collect all scene files in order
    mp3_files = sorted(audio_dir.glob("scene-*.mp3"))
    if not mp3_files:
        return None

    for mp3 in mp3_files:
        stem = mp3.stem  # "scene-001"
        alignment = audio_dir / f"{stem}.alignment.json"
        timing = audio_dir / f"{stem}.timing.json"

        words: list[dict] = []
        if alignment.exists():
            words = _load_alignment_json(alignment)
        elif timing.exists():
            words = _load_timing_json(timing)

        if not words:
            # Estimate scene duration via ffprobe; skip if unavailable
            dur = _probe_duration(mp3)
            cursor += dur + 0.1
            continue

        # Find actual end of this scene's audio (last word end)
        last_end = 0.0
        for w in words:
            word_start = float(w.get("start", 0.0)) + cursor
            word_end = float(w.get("end", 0.0)) + cursor
            last_end = max(last_end, word_end)
            all_words.append(
                {
                    "word": w.get("word", ""),
                    "start": round(word_start, 4),
                    "end": round(word_end, 4),
                }
            )

        # Advance cursor to after this scene (leave 0.1 s gap for transitions)
        cursor = last_end + 0.1

    if not all_words:
        return None

    # Build speech segments: each word is a segment; group nearby words
    word_segs = [
        SpeechSegment(start=w["start"], end=w["end"])
        for w in all_words
        if w["end"] > w["start"]
    ]
    if not word_segs:
        return None

    phrases = _group_phrases(word_segs, phrase_gap_ms / 1000.0)
    total_dur = phrases[-1].end if phrases else 0.0
    speech_total = sum(s.duration for s in phrases)
    speech_ratio = round(speech_total / total_dur, 3) if total_dur > 0 else 0.0

    return SpeechTimeline(
        segments=phrases,
        total_duration=total_dur,
        speech_ratio=speech_ratio,
    )


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
