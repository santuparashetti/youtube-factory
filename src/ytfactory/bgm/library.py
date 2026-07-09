"""BGMLibrary — discovers and selects background music tracks from disk."""

from __future__ import annotations

import random
from pathlib import Path

from .config import BGMConfig
from .models import BGMTrack


_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}
)


class BGMLibrary:
    """Scans the configured music library directory and selects tracks by category.

    Directory layout (preferred):
        <library_path>/
            spiritual/track-01.mp3
            meditation/track-01.mp3
            ...

    Flat fallback:
        <library_path>/spiritual-ambient.mp3   ← category inferred from filename
    """

    def __init__(self, config: BGMConfig) -> None:
        self._config = config
        self._base = Path(config.library_path)

    # ── Public API ────────────────────────────────────────────────────────

    def find_track(self, category: str) -> BGMTrack | None:
        """Return one track for *category*, or None if the library is empty.

        Search order:
        1. ``<library_path>/<category>/`` subdirectory
        2. Tracks in ``<library_path>/`` whose filename contains the category name
        3. Any track in ``<library_path>/`` (flat fallback)
        4. Any track in any subdirectory (recursive fallback when library uses
           subdirectory layout but requested category has no tracks)
        """
        # 1. Category subdirectory
        cat_dir = self._base / category
        tracks = self._scan_dir(cat_dir, category)
        if tracks:
            return self._pick(tracks)

        # 2. Flat directory — filter by filename keyword
        flat = self._scan_dir(self._base, "")
        keyword = category.replace("_", " ")
        keyword_tracks = [
            t for t in flat
            if keyword in t.path.stem.lower() or category in t.path.stem.lower()
        ]
        if keyword_tracks:
            return self._pick(keyword_tracks)

        # 3. Any root-level track
        if flat:
            return self._pick(flat)

        # 4. Any track in any subdirectory (handles category-organised libraries
        #    where the detected category simply has no tracks yet)
        if self._base.exists():
            all_sub: list[BGMTrack] = []
            for sub in sorted(self._base.iterdir()):
                if sub.is_dir():
                    all_sub.extend(self._scan_dir(sub, sub.name))
            if all_sub:
                return self._pick(all_sub)

        return None

    def list_categories(self) -> list[str]:
        """Return the names of all subdirectories that contain audio files."""
        if not self._base.exists():
            return []
        return sorted(
            d.name
            for d in self._base.iterdir()
            if d.is_dir() and self._scan_dir(d, d.name)
        )

    def is_available(self) -> bool:
        """Return True if the library directory exists and contains audio files."""
        return bool(self._scan_dir(self._base, "")) or bool(
            any(
                self._scan_dir(d, d.name)
                for d in self._base.iterdir()
                if self._base.exists() and d.is_dir()
            )
            if self._base.exists()
            else False
        )

    # ── Internal helpers ──────────────────────────────────────────────────

    def _scan_dir(self, directory: Path, category: str) -> list[BGMTrack]:
        if not directory.exists() or not directory.is_dir():
            return []
        tracks = [
            BGMTrack(path=p, category=category or directory.name)
            for p in sorted(directory.iterdir())
            if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS
        ]
        return tracks

    def _pick(self, tracks: list[BGMTrack]) -> BGMTrack:
        if self._config.random_track and len(tracks) > 1:
            return random.choice(tracks)
        return tracks[0]
