"""
Subtitle Intelligence Engine — professional subtitle generation for YouTube Factory.

Entry points:
  SubtitleEngine          — full pipeline (segment → timing → validate → serialize)
  SubtitleEngine.build()  → SRT string (backward-compatible)
  SubtitleEngine.build_both() → (ass, srt, report) — primary path for ASS output
  ASSWriter, ASSTheme, ThemeManager — ASS format support
"""

from .ass import ASSTheme, ASSWriter, ThemeManager
from .engine import SubtitleEngine
from .models import SubtitleCue, SubtitleFormat

__all__ = [
    "SubtitleEngine",
    "SubtitleCue",
    "SubtitleFormat",
    "ASSWriter",
    "ASSTheme",
    "ThemeManager",
]
