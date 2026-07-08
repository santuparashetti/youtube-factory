"""
WhisperX forced alignment — convert narration text + audio into word timestamps.

Unlike full transcription, forced alignment takes the KNOWN narration text and
the generated audio, then finds exactly when each word was spoken.  This gives
dramatically more accurate word boundaries than the proportional estimates
produced by Edge TTS's SentenceBoundary events.

Requirements
------------
    pip install whisperx

WhisperX is an optional heavy dependency (PyTorch-based).  This module uses
lazy imports and fails gracefully when the package is absent.

Output format (alignment.json)
------------------------------
    {
        "version": "whisperx_v1",
        "words": [
            {"word": "from",     "start": 0.12, "end": 0.38, "score": 0.98},
            {"word": "childhood","start": 0.40, "end": 0.82, "score": 0.95},
            ...
        ],
        "sentences": [
            {"start": 0.12, "end": 2.45, "text": "From childhood we ..."},
            ...
        ],
        "confidence": 0.96
    }

The ``words`` list is compatible with the word-boundary format used by the
rest of the subtitle pipeline — ``[{word, start, end}]``.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger


def is_available() -> bool:
    """Return True when whisperx can be imported."""
    try:
        import whisperx  # type: ignore[import-untyped]  # noqa: F401

        return True
    except ImportError:
        return False


def align(
    narration: str,
    audio_path: Path,
    *,
    device: str = "cpu",
    language: str = "en",
) -> dict:
    """
    Force-align narration text to audio and return alignment data.

    Uses whisperx forced alignment (wav2vec2 phoneme model per language).
    The alignment model is language-specific and has no configurable size —
    WHISPERX_MODEL in settings is reserved for future transcription use.

    Args:
        narration:   The known narration text (used as the reference transcript).
        audio_path:  Path to the generated MP3/WAV audio file.
        device:      PyTorch device: 'cpu' or 'cuda'.
        language:    BCP-47 language code (e.g. 'en').

    Returns:
        Dict with keys: version, words, sentences, confidence.
        words is compatible with the [{word, start, end}] boundary format.

    Raises:
        RuntimeError: if whisperx is not installed or alignment fails.
    """
    try:
        import whisperx  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "WhisperX forced alignment requires the 'whisperx' package. "
            "Install with: pip install whisperx\n"
            f"Original error: {exc}"
        ) from exc

    lang_code = language.split("-")[0]  # "en-US" → "en"

    logger.info(
        "WhisperX: aligning {} words against {} (device={})",
        len(narration.split()),
        audio_path.name,
        device,
    )

    # Load audio as float32 array
    audio = whisperx.load_audio(str(audio_path))

    # Build a minimal "transcription" from the known narration.
    # WhisperX align() accepts a list of segment dicts with a 'text' key.
    # We treat the entire narration as a single segment — forced alignment will
    # find the timing for every word within it.
    audio_duration = len(audio) / 16000.0  # whisperx loads at 16 kHz

    segments = [
        {
            "text": narration.strip(),
            "start": 0.0,
            "end": audio_duration,
        }
    ]

    # Load phoneme-level alignment model for the given language
    model_a, metadata = whisperx.load_align_model(
        language_code=lang_code,
        device=device,
    )

    # Perform forced alignment
    result = whisperx.align(
        segments,
        model_a,
        metadata,
        audio,
        device,
        return_char_alignments=False,
    )

    # Extract word-level data from all aligned segments
    words: list[dict] = []
    sentence_data: list[dict] = []
    scores: list[float] = []

    for seg in result.get("segments", []):
        sentence_data.append(
            {
                "start": seg.get("start", 0.0),
                "end": seg.get("end", 0.0),
                "text": seg.get("text", "").strip(),
            }
        )
        for w in seg.get("words", []):
            score = float(w.get("score", 0.0))
            scores.append(score)
            words.append(
                {
                    "word": w.get("word", "").strip(),
                    "start": float(w.get("start", 0.0)),
                    "end": float(w.get("end", 0.0)),
                    "score": round(score, 4),
                }
            )

    avg_confidence = round(sum(scores) / max(len(scores), 1), 4)

    logger.info(
        "WhisperX: aligned {} words, avg confidence={:.3f}",
        len(words),
        avg_confidence,
    )

    return {
        "version": "whisperx_v1",
        "words": words,
        "sentences": sentence_data,
        "confidence": avg_confidence,
    }


def save_alignment(alignment: dict, path: Path) -> None:
    """Write alignment data to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(alignment, indent=2), encoding="utf-8")


def load_alignment(path: Path) -> dict | None:
    """Load alignment data from JSON; return None if the file is absent or invalid."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") == "whisperx_v1" and "words" in data:
            return data
        return None
    except (json.JSONDecodeError, OSError):
        return None


def boundaries_from_alignment(alignment: dict) -> list[dict]:
    """
    Extract a [{word, start, end}] list from an alignment dict.

    Compatible with the word-boundary format used by SubtitleEngine.
    Filters out words with missing timing.
    """
    result: list[dict] = []
    for w in alignment.get("words", []):
        word = w.get("word", "").strip()
        start = w.get("start")
        end = w.get("end")
        if word and start is not None and end is not None:
            result.append({"word": word, "start": float(start), "end": float(end)})
    return result
