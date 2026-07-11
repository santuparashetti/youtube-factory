"""
AudioValidator — post-synthesis quality control for TTS output.

Checks every generated audio file for failure modes that would produce
a bad scene in the final video:

  ✓ file exists and is non-empty
  ✓ audio duration is measurable
  ✓ duration is reasonable for the word count (catches truncated generation)
  ✓ duration is not suspiciously long (catches duplicate/looped audio)

Uses ffprobe when available (always present in this pipeline), falls back
to mutagen for duration measurement.

Returns a ValidationResult with a passed flag, measured duration, and a
list of issues (failures) and warnings (non-blocking observations).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

# Minimum bytes for a non-empty MP3 (a 1-second MP3 at 128kbps = ~16000 bytes)
_MIN_FILE_BYTES = 1024

# At 130 wpm with a -15% slowdown (spiritual), 1 word ≈ 0.55 s.
# We accept down to 0.25 s/word to catch only truly truncated audio.
_MIN_SECONDS_PER_WORD = 0.25

# Warn if duration exceeds 3 s/word (likely silent padding or repeated audio).
_MAX_SECONDS_PER_WORD = 3.0

# Minimum absolute duration regardless of word count.
_MIN_ABSOLUTE_SECONDS = 0.5


@dataclass
class ValidationResult:
    """Result of validating a single generated audio file."""

    passed: bool
    duration_seconds: float
    file_size_bytes: int
    issues: list[str] = field(default_factory=list)  # failures — will trigger retry
    warnings: list[str] = field(default_factory=list)  # non-blocking observations

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "duration_seconds": round(self.duration_seconds, 3),
            "file_size_bytes": self.file_size_bytes,
            "issues": self.issues,
            "warnings": self.warnings,
        }


class AudioValidator:
    """Validate a generated MP3 file against expected narration properties."""

    def validate(
        self,
        audio_path: Path,
        word_count: int,
        scene_index: int | None = None,
    ) -> ValidationResult:
        """
        Run all validation checks on ``audio_path``.

        Args:
            audio_path:  Path to the generated .mp3 file.
            word_count:  Number of words in the narration (for duration checks).
            scene_index: Optional scene number for log messages.

        Returns:
            ValidationResult. ``passed`` is False if any check failed.
        """
        label = (
            f"Scene {scene_index}" if scene_index is not None else str(audio_path.name)
        )
        issues: list[str] = []
        warnings: list[str] = []

        # ── 1. File existence ─────────────────────────────────────────────────
        if not audio_path.exists():
            issues.append("audio file does not exist")
            return ValidationResult(
                passed=False,
                duration_seconds=0.0,
                file_size_bytes=0,
                issues=issues,
                warnings=warnings,
            )

        # ── 2. File size ──────────────────────────────────────────────────────
        size = audio_path.stat().st_size
        if size < _MIN_FILE_BYTES:
            issues.append(
                f"audio file too small: {size} bytes (minimum {_MIN_FILE_BYTES})"
            )

        # ── 3. Measure duration ───────────────────────────────────────────────
        duration = _measure_duration(audio_path)
        if duration <= 0.0:
            issues.append("could not measure audio duration (file may be corrupt)")
        elif duration < _MIN_ABSOLUTE_SECONDS:
            issues.append(
                f"audio duration too short: {duration:.2f}s (minimum {_MIN_ABSOLUTE_SECONDS}s)"
            )

        # ── 4. Duration vs word count ─────────────────────────────────────────
        if duration > 0.0 and word_count > 0:
            seconds_per_word = duration / word_count
            if seconds_per_word < _MIN_SECONDS_PER_WORD:
                issues.append(
                    f"duration too short for word count: {duration:.2f}s for {word_count} words "
                    f"({seconds_per_word:.2f} s/word, minimum {_MIN_SECONDS_PER_WORD})"
                )
            elif seconds_per_word > _MAX_SECONDS_PER_WORD:
                warnings.append(
                    f"unusually long duration: {duration:.2f}s for {word_count} words "
                    f"({seconds_per_word:.2f} s/word)"
                )

        passed = len(issues) == 0
        result = ValidationResult(
            passed=passed,
            duration_seconds=duration,
            file_size_bytes=size,
            issues=issues,
            warnings=warnings,
        )

        if not passed:
            logger.warning("{} validation failed: {}", label, "; ".join(issues))
        elif warnings:
            logger.warning("{} validation warnings: {}", label, "; ".join(warnings))
        else:
            logger.debug(
                "{} validation passed: {:.2f}s, {} bytes", label, duration, size
            )

        return result


# ── Duration measurement ───────────────────────────────────────────────────────


def _measure_duration(path: Path) -> float:
    """
    Measure the actual audio duration of ``path`` in seconds.

    Tries ffprobe first (most accurate), falls back to mutagen.
    Returns 0.0 on failure.
    """
    duration = _ffprobe_duration(path)
    if duration > 0.0:
        return duration
    return _mutagen_duration(path)


def _ffprobe_duration(path: Path) -> float:
    """Use ffprobe to read audio stream duration. Returns 0.0 on any error."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                raw = stream.get("duration", "0")
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    pass
    except Exception:
        pass
    return 0.0


def _mutagen_duration(path: Path) -> float:
    """Use mutagen to read MP3 duration. Returns 0.0 on any error."""
    try:
        from mutagen.mp3 import MP3

        return float(MP3(str(path)).info.length)
    except Exception:
        return 0.0
