"""Data models for the BGM pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BGMTrack:
    """A single background music track discovered in the library."""

    path: Path
    category: str
    title: str = ""
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.title:
            self.title = self.path.stem


@dataclass
class BGMMixResult:
    """Outcome of a single BGM mixing operation."""

    track: BGMTrack
    video_duration: float
    output_path: Path
    success: bool
    category: str = ""
    error: str = ""
    mix_command: list[str] = field(default_factory=list)
