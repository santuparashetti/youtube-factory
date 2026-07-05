"""Stage 4 — Production Quality Review.

Checks:
  - Final video has a valid duration (via ffprobe when available)
  - Final video duration is within expected range
  - scene-plan.json contains required fields on every scene
  - Rendering was applied (scene video clips exist for expected scenes)
  - V4 shot types are assigned (quality indicator — warning only)
  - All scene clips rendered successfully (no gaps)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ytfactory.review.models import SceneReview
from ytfactory.review.stages.base import BaseReviewStage

_REQUIRED_SCENE_FIELDS = ("index", "title", "narration", "duration_seconds")


class ProductionQualityStage(BaseReviewStage):
    name = "production_quality"

    def _run_checks(
        self,
        project_dir: Path,
        scenes: list[dict],
        scene_reviews: list[SceneReview],
        context: dict,
    ) -> None:
        # ── scene-plan.json field completeness ────────────────────────────
        for scene in scenes:
            idx = scene.get("index", "?")
            for field in _REQUIRED_SCENE_FIELDS:
                self._check(
                    field in scene and scene[field] is not None,
                    f"Scene {idx}: required field '{field}' is missing from scene plan",
                )

        # ── Shot type coverage (V4 quality indicator) ──────────────────────
        gen_scenes = [
            s
            for s in scenes
            if s.get("scene_type", "generated_image") == "generated_image"
        ]
        scenes_with_shots = [s for s in gen_scenes if s.get("shot_type", "")]
        shot_coverage = len(scenes_with_shots) / max(len(gen_scenes), 1)
        if len(gen_scenes) >= 3 and shot_coverage < 0.8:
            self._warn(
                f"Only {len(scenes_with_shots)}/{len(gen_scenes)} generated scenes "
                f"have shot_type assigned (V4 coverage: {shot_coverage:.0%})"
            )
        else:
            self._ok()

        # ── Render completeness: every expected scene has a video clip ─────
        expected_indices = {s.get("index") for s in scenes}
        rendered_clips = {
            sr.index
            for sr in scene_reviews
            if sr.has_video_clip and sr.video_clip_size_bytes > 0
        }
        missing_clips = expected_indices - rendered_clips
        self._check(
            not missing_clips,
            f"Missing video clips for scenes: {sorted(missing_clips)}",
        )

        # ── Final video duration (ffprobe) ────────────────────────────────
        final_video = project_dir / "video" / "final.mp4"
        if final_video.exists():
            duration = _probe_duration(final_video)
            if duration is not None:
                context["final_video_duration_seconds"] = duration
                self._check(
                    duration >= self._config.min_total_duration_seconds,
                    f"final.mp4 duration {duration:.1f}s is below minimum "
                    f"({self._config.min_total_duration_seconds}s)",
                )
                self._check(
                    duration <= self._config.max_total_duration_seconds,
                    f"final.mp4 duration {duration:.1f}s exceeds maximum "
                    f"({self._config.max_total_duration_seconds}s)",
                )

                # Sanity: actual vs declared duration (±30%)
                declared = context.get("total_declared_duration_seconds", 0.0)
                if declared > 0:
                    ratio = duration / declared
                    if ratio < 0.7 or ratio > 1.3:
                        self._warn(
                            f"Actual video duration ({duration:.1f}s) differs significantly "
                            f"from declared ({declared:.1f}s) — ratio {ratio:.2f}"
                        )
                    else:
                        self._ok()
            else:
                self._warn("Could not determine final.mp4 duration via ffprobe")

        # ── Subtitle style markers (production readiness) ──────────────────
        ass_count = sum(
            1
            for sr in scene_reviews
            if (project_dir / "subtitles" / f"scene-{sr.index:03d}.ass").exists()
        )
        if len(scenes) > 0:
            ass_ratio = ass_count / len(scenes)
            if ass_ratio < 0.5:
                self._warn(
                    f"Only {ass_count}/{len(scenes)} scenes have ASS subtitles "
                    f"— falling back to SRT may reduce subtitle quality"
                )
            else:
                self._ok()


def _probe_duration(path: Path) -> float | None:
    """Return duration in seconds via ffprobe, or None on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return None
