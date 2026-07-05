"""ChaptersGenerator — derive accurate chapter timestamps from scene data.

Reads:
  - scenes/scene-plan.json  →  scene titles + declared durations (fallback)
  - audio/scene-NNN.timing.json  →  real duration from last boundary entry

Output: chapters.txt with lines like:
  0:00 Introduction
  1:23 The Rise of the Maratha Empire
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.publish.artifacts import chapters_path
from ytfactory.publish.models import ChapterEntry


def _format_timestamp(seconds: float) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _scene_duration(project_dir: Path, scene: dict) -> float:
    """Return real audio duration for a scene, falling back to declared duration."""
    index = scene["index"]
    timing_file = project_dir / "audio" / f"scene-{index:03d}.timing.json"
    if timing_file.exists():
        try:
            data = json.loads(timing_file.read_text(encoding="utf-8"))
            if data:
                return float(data[-1]["end"])
        except (json.JSONDecodeError, KeyError, IndexError, ValueError):
            pass
    return float(scene.get("duration_seconds", 0.0))


class ChaptersGenerator:
    """Generate chapter timestamps from scene plan + real audio durations."""

    def generate(
        self, project_id: str, project_dir: Path, scenes: list[dict]
    ) -> list[ChapterEntry]:
        """Compute chapters and write chapters.txt.  Returns list of ChapterEntry."""
        entries: list[ChapterEntry] = []
        cumulative = 0.0

        for i, scene in enumerate(scenes):
            entry = ChapterEntry(
                index=i + 1,
                timestamp_seconds=cumulative,
                timestamp_str=_format_timestamp(cumulative),
                title=scene.get("title", f"Chapter {i + 1}"),
            )
            entries.append(entry)
            cumulative += _scene_duration(project_dir, scene)

        self._write(project_id, entries)
        return entries

    def _write(self, project_id: str, entries: list[ChapterEntry]) -> None:
        lines = [f"{e.timestamp_str} {e.title}" for e in entries]
        chapters_path(project_id).write_text("\n".join(lines), encoding="utf-8")
