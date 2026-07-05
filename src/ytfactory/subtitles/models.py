"""
Subtitle domain models — pure data, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SubtitleFormat(str, Enum):
    """Output format selector — extend here for WebVTT, ASS, etc."""

    SRT = "srt"
    # Reserved for future formats:
    # WEBVTT = "webvtt"
    # ASS = "ass"


@dataclass
class SubtitleCue:
    """
    One displayable subtitle block.

    index:   1-based sequential number within the scene.
    start:   Display start time in seconds.
    end:     Display end time in seconds.
    lines:   Text lines (1–2 items). Stored as a list so multi-line is first-class.
    """

    index: int
    start: float
    end: float
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Full text as a single joined string (useful for analysis)."""
        return " ".join(self.lines)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def char_count(self) -> int:
        """Total non-space characters across all lines."""
        return sum(len(line.replace(" ", "")) for line in self.lines)

    @property
    def cps(self) -> float:
        """Characters per second (non-space chars / duration)."""
        if self.duration <= 0:
            return 0.0
        return self.char_count / self.duration

    @property
    def longest_line(self) -> int:
        return max((len(line) for line in self.lines), default=0)


@dataclass
class ValidationIssue:
    """A single validation finding on a subtitle cue."""

    cue_index: int
    code: str  # e.g. "HIGH_CPS", "LONG_LINE", "ORPHAN"
    severity: str  # "error" | "warning"
    message: str
    repaired: bool = False


@dataclass
class SubtitleReport:
    """Diagnostics summary produced after building subtitles for one scene."""

    scene_index: int
    cue_count: int
    avg_cps: float
    max_cps: float
    avg_duration: float
    min_duration: float
    max_duration: float
    overlap_repairs: int
    gap_repairs: int
    typography_repairs: int
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scene_index": self.scene_index,
            "cue_count": self.cue_count,
            "avg_cps": round(self.avg_cps, 2),
            "max_cps": round(self.max_cps, 2),
            "avg_duration": round(self.avg_duration, 3),
            "min_duration": round(self.min_duration, 3),
            "max_duration": round(self.max_duration, 3),
            "overlap_repairs": self.overlap_repairs,
            "gap_repairs": self.gap_repairs,
            "typography_repairs": self.typography_repairs,
            "issues": [
                {
                    "cue_index": i.cue_index,
                    "code": i.code,
                    "severity": i.severity,
                    "message": i.message,
                    "repaired": i.repaired,
                }
                for i in self.issues
            ],
        }
