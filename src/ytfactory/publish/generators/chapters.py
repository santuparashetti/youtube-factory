"""ChaptersGenerator — derive accurate chapter timestamps from scene data.

Reads:
  - scenes/scene-plan.json  →  scene titles + declared durations (fallback)
  - audio/scene-NNN.timing.json  →  real duration from last boundary entry

Output: chapters.txt with lines like:
  0:00 Introduction
  1:23 The Rise of the Maratha Empire

Chapter count is capped at publish_max_chapters (default 10) by merging
adjacent scenes into even contiguous groups.  Each chapter is guaranteed
to be at least publish_min_chapter_seconds long (default 10s, matching
YouTube's own rule) — merging further down if needed.  Short videos get
fewer chapters; they are never padded up to the cap.
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


def _make_chapter_groups(
    n: int,
    durations: list[float],
    max_chapters: int,
    min_seconds: int,
) -> list[tuple[int, ...]]:
    """Group n scenes into at most max_chapters chapters, each >= min_seconds long.

    Returns a list of tuples; each tuple contains the 0-based scene indices
    for one chapter.  Groups are contiguous and cover all scenes.

    Algorithm:
      1. If scene count <= max and every scene is >= min_seconds: one chapter
         per scene (short videos are not padded up to the cap).
      2. Otherwise distribute scenes into min(n, max_chapters) groups using
         balanced integer division (extras front-loaded so chapter sizes differ
         by at most 1).
      3. Enforce minimum: any group still below min_seconds is merged with its
         shorter neighbor until all chapters meet the threshold.  This can
         produce fewer than max_chapters chapters on very short videos.
    """
    if n == 0:
        return []

    def dur(g: tuple[int, ...]) -> float:
        return sum(durations[i] for i in g)

    # Natural grouping — one scene per chapter
    groups: list[tuple[int, ...]] = [(i,) for i in range(n)]

    # Already acceptable? Leave unchanged.
    if len(groups) <= max_chapters and all(dur(g) >= min_seconds for g in groups):
        return groups

    # Balanced merge: distribute n scenes into target groups.
    # q scenes per group, first r groups get one extra.
    target = min(max_chapters, n)
    q, r = divmod(n, target)
    merged: list[tuple[int, ...]] = []
    idx = 0
    for i in range(target):
        size = q + 1 if i < r else q
        merged.append(tuple(range(idx, idx + size)))
        idx += size
    groups = merged

    # Enforce minimum chapter duration — merge down further if needed.
    while len(groups) > 1:
        short_idx = next(
            (i for i, g in enumerate(groups) if dur(g) < min_seconds),
            None,
        )
        if short_idx is None:
            break  # all chapters meet the minimum
        # Merge with the shorter neighbour to keep groups as balanced as possible.
        if short_idx == 0:
            groups[0:2] = [groups[0] + groups[1]]
        elif short_idx == len(groups) - 1:
            groups[-2:] = [groups[-2] + groups[-1]]
        else:
            prev_dur = dur(groups[short_idx - 1])
            next_dur = dur(groups[short_idx + 1])
            if prev_dur <= next_dur:
                groups[short_idx - 1 : short_idx + 1] = [
                    groups[short_idx - 1] + groups[short_idx]
                ]
            else:
                groups[short_idx : short_idx + 2] = [
                    groups[short_idx] + groups[short_idx + 1]
                ]

    return groups


class ChaptersGenerator:
    """Generate chapter timestamps from scene plan + real audio durations."""

    def __init__(self, settings=None) -> None:
        if settings is None:
            from ytfactory.config.settings import Settings

            settings = Settings()
        self._max_chapters: int = int(getattr(settings, "publish_max_chapters", 10))
        self._min_chapter_seconds: int = int(
            getattr(settings, "publish_min_chapter_seconds", 10)
        )

    def generate(
        self, project_id: str, project_dir: Path, scenes: list[dict]
    ) -> list[ChapterEntry]:
        """Compute chapters and write chapters.txt.  Returns list of ChapterEntry."""
        if not scenes:
            self._write(project_id, [])
            return []

        durations = [_scene_duration(project_dir, s) for s in scenes]

        # Cumulative start time per scene (index 0 is always 0.0 → 0:00)
        cumulative: list[float] = []
        t = 0.0
        for d in durations:
            cumulative.append(t)
            t += d

        groups = _make_chapter_groups(
            len(scenes), durations, self._max_chapters, self._min_chapter_seconds
        )

        entries: list[ChapterEntry] = []
        for chapter_num, group in enumerate(groups):
            first_idx = group[0]
            title = scenes[first_idx].get("title", f"Chapter {chapter_num + 1}")
            ts = cumulative[first_idx]
            # First chapter must always be 0:00 — clamp defensively.
            if chapter_num == 0 and ts != 0.0:
                ts = 0.0
            entries.append(
                ChapterEntry(
                    index=chapter_num + 1,
                    timestamp_seconds=ts,
                    timestamp_str=_format_timestamp(ts),
                    title=title,
                )
            )

        self._write(project_id, entries)
        return entries

    def _write(self, project_id: str, entries: list[ChapterEntry]) -> None:
        lines = [f"{e.timestamp_str} {e.title}" for e in entries]
        chapters_path(project_id).write_text("\n".join(lines), encoding="utf-8")
