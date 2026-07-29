"""Post-processing utility: split final.mp4 into parts at scene boundaries.

Output parts are handed off to Epidemic Sound for BGM/sound layering. This
is a pure addition after final.mp4 is produced — it never modifies the
render pipeline, scene-plan.json, or pipeline-status.json.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from loguru import logger

MICRO_TAIL_SECONDS = 60.0
DURATION_DRIFT_TOLERANCE = 0.05


class VideoSplitter:
    """Split a rendered video into parts at scene boundaries.

    ``num_parts`` is the minimum number of equal-ish parts needed to keep
    every part within ``target_seconds`` (``ceil(total_duration /
    target_seconds)``). Cut points are chosen as the scene boundary closest
    to each evenly-spaced ideal timestamp, subject to a hard ceiling: a part
    may never exceed ``target_seconds``.
    """

    def split(
        self,
        input_path: Path,
        scenes: list[dict],
        output_dir: Path,
        audio_dir: Path,
        target_minutes: float,
        max_parts: int = 3,
    ) -> list[Path]:
        # scene-plan.json's duration_seconds is a pre-TTS planning estimate and
        # can diverge sharply (14-19% observed) from the actual rendered audio
        # that final.mp4 was composed from — use the real per-scene audio
        # duration (same source as video/pipeline.py::_actual_audio_duration)
        # so cut points land on the timeline final.mp4 was actually built on.
        actual_durations = self._actual_scene_durations(scenes, audio_dir)
        total_duration = sum(actual_durations)
        final_duration = self._ffprobe_duration(input_path)

        if final_duration <= 0.0 or total_duration <= 0.0:
            logger.error(
                "VideoSplitter: could not determine actual durations "
                f"(scene audio sum={total_duration:.1f}s, "
                f"final.mp4={final_duration:.1f}s) — refusing to split."
            )
            return []

        drift = abs(total_duration - final_duration) / final_duration
        if drift > DURATION_DRIFT_TOLERANCE:
            logger.error(
                f"VideoSplitter: per-scene audio duration sum ({total_duration:.1f}s) "
                f"diverges from final.mp4 duration ({final_duration:.1f}s) by "
                f"{drift:.1%} (> {DURATION_DRIFT_TOLERANCE:.0%}) — refusing to split; "
                "cut points would not be reliable."
            )
            return []

        scenes = [
            {**scene, "duration_seconds": duration}
            for scene, duration in zip(scenes, actual_durations)
        ]

        target_seconds = target_minutes * 60.0
        num_parts = math.ceil(total_duration / target_seconds)

        if num_parts <= 1:
            logger.info(
                f"VideoSplitter: total duration {total_duration:.1f}s fits within "
                f"a single {target_seconds:.1f}s part — skipping split, final.mp4 "
                "left as a single file."
            )
            return []

        if num_parts > max_parts:
            logger.error(
                f"VideoSplitter: {num_parts} parts are required to keep every "
                f"part within {target_seconds:.1f}s, but max_parts={max_parts} — "
                "refusing to split."
            )
            return []

        split_points = self._find_split_points(scenes, total_duration, target_seconds, num_parts)
        if split_points is None:
            return []

        if split_points and (final_duration - split_points[-1]) < MICRO_TAIL_SECONDS:
            split_points.pop()

        # Last boundary is pinned to final.mp4's true (ffprobe'd) duration, not
        # the per-scene sum, so the last segment's -t always reaches real EOF
        # even with the small residual drift the guard above tolerates.
        boundaries = [0.0] + split_points + [final_duration]

        # Hard invariant: no part may exceed target_seconds. Tail absorption
        # above can grow the last part, and the last part is otherwise
        # unconstrained during selection (it's whatever remains) — so this is
        # the authoritative, final check regardless of how boundaries formed.
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            if (end - start) > target_seconds:
                logger.error(
                    f"VideoSplitter: part {start:.1f}s-{end:.1f}s "
                    f"({end - start:.1f}s) exceeds target {target_seconds:.1f}s — "
                    "refusing to split."
                )
                return []

        scene_counts = self._scene_counts_per_part(scenes, boundaries)

        output_dir.mkdir(parents=True, exist_ok=True)
        parts_meta: list[dict] = []
        output_paths: list[Path] = []

        for i, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:]), start=1):
            output_path = output_dir / f"final_part{i}.mp4"
            self._run_ffmpeg_segment(input_path, output_path, start, end - start)
            output_paths.append(output_path)
            parts_meta.append(
                {
                    "part": i,
                    "path": output_path.name,
                    "start_seconds": start,
                    "end_seconds": end,
                    "scene_count": scene_counts[i - 1],
                }
            )

        manifest_path = output_dir / "split_manifest.json"
        manifest_path.write_text(
            json.dumps({"parts": parts_meta}, indent=2), encoding="utf-8"
        )

        return output_paths

    def _actual_scene_durations(self, scenes: list[dict], audio_dir: Path) -> list[float]:
        durations = []
        for scene in scenes:
            index = int(scene["index"])
            audio_path = audio_dir / f"scene-{index:03d}.mp3"
            durations.append(self._ffprobe_duration(audio_path))
        return durations

    @staticmethod
    def _ffprobe_duration(path: Path) -> float:
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
                check=True,
                timeout=10,
            )
            return float(result.stdout.strip())
        except Exception:
            return 0.0

    def _find_split_points(
        self,
        scenes: list[dict],
        total_duration: float,
        target_seconds: float,
        num_parts: int,
    ) -> list[float] | None:
        cumulative = 0.0
        boundaries: list[float] = []
        for scene in scenes:
            cumulative += float(scene.get("duration_seconds", 0.0))
            boundaries.append(cumulative)

        ideal_timestamps = [total_duration * i / num_parts for i in range(1, num_parts)]

        split_points: list[float] = []
        last_split = 0.0

        for ideal in ideal_timestamps:
            # No window, no floor, no ceiling on the search itself — just the
            # scene boundary closest to the ideal timestamp. The hard ceiling
            # (part <= target_seconds) is enforced separately below by only
            # considering eligible candidates, so a closer-but-too-far
            # boundary is skipped in favor of the closest one that still fits.
            candidates = [b for b in boundaries if last_split < b < total_duration]
            eligible = [b for b in candidates if (b - last_split) <= target_seconds]

            if not eligible:
                logger.error(
                    f"VideoSplitter: no scene boundary between {last_split:.1f}s "
                    f"and {last_split + target_seconds:.1f}s — cannot keep this "
                    f"part within the {target_seconds:.1f}s target."
                )
                return None

            best = min(eligible, key=lambda b: abs(b - ideal))
            split_points.append(best)
            last_split = best

        return split_points

    def _scene_counts_per_part(
        self, scenes: list[dict], boundaries: list[float]
    ) -> list[int]:
        counts = [0] * (len(boundaries) - 1)
        cumulative = 0.0
        for scene in scenes:
            cumulative += float(scene.get("duration_seconds", 0.0))
            for part_idx in range(len(counts)):
                if cumulative <= boundaries[part_idx + 1] or part_idx == len(counts) - 1:
                    counts[part_idx] += 1
                    break
        return counts

    def _run_ffmpeg_segment(
        self, input_path: Path, output_path: Path, start_seconds: float, duration_seconds: float
    ) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start_seconds),
            "-i",
            str(input_path),
            "-t",
            str(duration_seconds),
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
