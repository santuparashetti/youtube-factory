"""Stage 2 — Timeline Review.

Checks:
  - Scenes are in sequential order starting from index 1
  - No duplicate scene indices
  - Each scene's declared duration is within bounds
  - Total declared duration is within configured bounds
  - SRT files have parseable, non-overlapping timestamps
"""

from __future__ import annotations

import re
from pathlib import Path

from ytfactory.review.models import SceneReview
from ytfactory.review.stages.base import BaseReviewStage

# SRT timestamp pattern: HH:MM:SS,mmm
_SRT_TS_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)


class TimelineReviewStage(BaseReviewStage):
    name = "timeline"

    def _run_checks(
        self,
        project_dir: Path,
        scenes: list[dict],
        scene_reviews: list[SceneReview],
        context: dict,
    ) -> None:
        indices = [s.get("index", 0) for s in scenes]

        # Scene ordering
        self._check(
            indices == sorted(set(indices)),
            f"Scene indices are not in sequential order: {indices}",
        )

        # Duplicate indices
        seen: set[int] = set()
        dupes = [i for i in indices if i in seen or seen.add(i)]  # type: ignore[func-returns-value]
        self._check(not dupes, f"Duplicate scene indices: {dupes}")

        # Per-scene duration bounds
        total_duration = 0.0
        for scene in scenes:
            idx = scene.get("index", 0)
            dur = float(scene.get("duration_seconds", 0.0))

            # Find corresponding SceneReview and populate
            for sr in scene_reviews:
                if sr.index == idx:
                    sr.declared_duration_seconds = dur
                    break

            total_duration += dur

            self._check(
                dur >= self._config.min_scene_duration_seconds,
                f"Scene {idx}: duration {dur:.1f}s is below minimum "
                f"({self._config.min_scene_duration_seconds}s)",
            )
            self._check(
                dur <= self._config.max_scene_duration_seconds,
                f"Scene {idx}: duration {dur:.1f}s exceeds maximum "
                f"({self._config.max_scene_duration_seconds}s)",
            )

        # Total duration bounds
        context["total_declared_duration_seconds"] = total_duration
        self._check(
            total_duration >= self._config.min_total_duration_seconds,
            f"Total declared duration {total_duration:.1f}s is below minimum "
            f"({self._config.min_total_duration_seconds}s)",
        )
        self._check(
            total_duration <= self._config.max_total_duration_seconds,
            f"Total declared duration {total_duration:.1f}s exceeds maximum "
            f"({self._config.max_total_duration_seconds}s)",
        )

        # SRT timestamp consistency (sample check on each scene's SRT)
        for sr in scene_reviews:
            srt = project_dir / "subtitles" / f"scene-{sr.index:03d}.srt"
            if srt.exists():
                issues = _validate_srt(srt)
                if issues:
                    self._warn(f"Scene {sr.index} SRT issues: {'; '.join(issues)}")
                else:
                    self._ok()


def _validate_srt(path: Path) -> list[str]:
    """Return a list of SRT issues (empty = ok).  Non-fatal — produces warnings only."""
    issues: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [f"cannot read {path.name}"]

    matches = _SRT_TS_RE.findall(text)
    if not matches:
        issues.append("no SRT timestamp blocks found")
        return issues

    prev_end = 0.0
    for i, m in enumerate(matches):
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in m)
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000

        if end <= start:
            issues.append(f"block {i + 1}: end ≤ start ({start:.3f}s → {end:.3f}s)")
        if start < prev_end:
            issues.append(
                f"block {i + 1}: overlaps previous ({start:.3f}s < {prev_end:.3f}s)"
            )
        prev_end = end

    return issues
