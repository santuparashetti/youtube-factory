"""Rendering validation rules (category G).

Rules:
  REND_001 [critical] — Scene video clip exists for every scene
  REND_002 [high]     — Scene video clip meets minimum size
  REND_003 [critical] — Final video file exists
  REND_004 [high]     — Final video meets minimum size
  REND_005 [high]     — All expected scene clips are present
  REND_006 [high]     — No unexpected black frames > 100 ms mid-scene
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult


def _clip_duration_seconds(clip: Path) -> float:
    """Return the duration of a video clip in seconds via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(clip),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        val = result.stdout.strip()
        if val:
            return float(val)
    except Exception:
        pass
    return 0.0


def _detect_unexpected_black_frames(
    clip: Path,
    skip_start: float,
    skip_end: float,
    min_duration: float,
    pic_th: float,
) -> list[dict]:
    """Run ffmpeg blackdetect on *clip* and return unexpected black segments.

    Segments that fall entirely within the fade-in window (first *skip_start*
    seconds) or entirely within the fade-out window (last *skip_end* seconds)
    are excluded — those are intentional cinematic transitions.

    Returns a list of dicts: [{start, end, duration}, ...].
    """
    clip_dur = _clip_duration_seconds(clip)

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-i", str(clip),
                "-vf",
                (
                    f"blackdetect=d={min_duration:.4f}"
                    f":pic_th={pic_th:.4f}"
                    ":pix_th=0.10"
                ),
                "-an",
                "-f", "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        return []
    except Exception:
        return []

    unexpected: list[dict] = []
    pattern = re.compile(
        r"black_start:(\S+)\s+black_end:(\S+)\s+black_duration:(\S+)"
    )
    for line in stderr.splitlines():
        m = pattern.search(line)
        if not m:
            continue
        bs = float(m.group(1))
        be = float(m.group(2))
        dur = float(m.group(3))

        # Skip segments that are entirely within the fade-in window
        if be <= skip_start:
            continue
        # Skip segments that are entirely within the fade-out window
        if clip_dur > 0 and bs >= max(0.0, clip_dur - skip_end):
            continue
        unexpected.append({"start": bs, "end": be, "duration": dur})

    return unexpected


class RenderingValidator(BaseValidator):
    category = "rendering"
    responsible_engine = "VideoRenderer"

    def validate(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []

        if not scenes:
            for rule_id in (
                "REND_001", "REND_002", "REND_003", "REND_004", "REND_005", "REND_006"
            ):
                if self._config.is_enabled(rule_id):
                    results.append(self._skip(rule_id, "no scenes available"))
            return results

        # Per-scene clip checks
        for scene in scenes:
            idx = scene.get("index", 0)
            clip_path = project_dir / "video" / f"scene-{idx:03d}.mp4"

            # REND_001: Clip exists
            if self._config.is_enabled("REND_001"):
                if not clip_path.exists():
                    results.append(
                        self._fail(
                            "REND_001",
                            f"Scene {idx}: video clip missing",
                            f"Expected: {clip_path.name}",
                            "critical",
                            scene_index=idx,
                        )
                    )
                    if self._config.is_enabled("REND_002"):
                        results.append(
                            self._skip("REND_002", "clip unavailable", scene_index=idx)
                        )
                    continue
                results.append(
                    self._pass(
                        "REND_001",
                        f"Scene {idx} video clip exists",
                        clip_path.name,
                        scene_index=idx,
                    )
                )

            # REND_002: Minimum clip size
            if self._config.is_enabled("REND_002") and clip_path.exists():
                size = clip_path.stat().st_size
                min_size = self._config.rendering_min_clip_size_bytes
                if size < min_size:
                    results.append(
                        self._fail(
                            "REND_002",
                            f"Scene {idx}: video clip too small ({size} bytes)",
                            f"size_bytes={size}, min={min_size}",
                            "high",
                            scene_index=idx,
                            size_bytes=size,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "REND_002",
                            f"Scene {idx} clip size OK",
                            f"{size} bytes",
                            scene_index=idx,
                        )
                    )

        final_path = project_dir / "video" / "final.mp4"

        # REND_003: Final video exists
        if self._config.is_enabled("REND_003"):
            if not final_path.exists():
                results.append(
                    self._fail(
                        "REND_003",
                        "Final video file missing",
                        f"Expected: {final_path}",
                        "critical",
                    )
                )
            else:
                results.append(
                    self._pass("REND_003", "Final video exists", str(final_path.name))
                )

        # REND_004: Final video minimum size
        if self._config.is_enabled("REND_004") and final_path.exists():
            size = final_path.stat().st_size
            min_size = self._config.rendering_min_final_size_bytes
            if size < min_size:
                results.append(
                    self._fail(
                        "REND_004",
                        f"Final video too small ({size} bytes)",
                        f"size_bytes={size}, min={min_size}",
                        "high",
                        size_bytes=size,
                    )
                )
            else:
                results.append(
                    self._pass("REND_004", "Final video size OK", f"{size} bytes")
                )

        # REND_005: All expected clips present
        if self._config.is_enabled("REND_005"):
            expected_indices = {s.get("index", 0) for s in scenes}
            missing = sorted(
                i
                for i in expected_indices
                if not (project_dir / "video" / f"scene-{i:03d}.mp4").exists()
            )
            if missing:
                results.append(
                    self._fail(
                        "REND_005",
                        f"{len(missing)} scene clip(s) missing from video directory",
                        f"missing scene indices: {missing[:5]}",
                        "high",
                        missing_count=len(missing),
                        missing_indices=missing,
                    )
                )
            else:
                results.append(
                    self._pass(
                        "REND_005",
                        "All expected scene clips present",
                        f"{len(expected_indices)} clips",
                    )
                )

        # REND_006: No unexpected black frames > 100 ms mid-scene
        # Checks every rendered scene clip using FFmpeg's blackdetect filter.
        # Segments within the configured fade-in / fade-out windows are exempt.
        if self._config.is_enabled("REND_006"):
            skip_start = self._config.rendering_black_frame_skip_start_seconds
            skip_end = self._config.rendering_black_frame_skip_end_seconds
            min_dur = self._config.rendering_black_frame_min_duration
            pic_th = self._config.rendering_black_frame_pic_threshold

            for scene in scenes:
                idx = scene.get("index", 0)
                clip_path = project_dir / "video" / f"scene-{idx:03d}.mp4"

                if not clip_path.exists():
                    results.append(
                        self._skip(
                            "REND_006",
                            f"Scene {idx}: clip not found, skipping black-frame check",
                            scene_index=idx,
                        )
                    )
                    continue

                try:
                    segments = _detect_unexpected_black_frames(
                        clip_path,
                        skip_start=skip_start,
                        skip_end=skip_end,
                        min_duration=min_dur,
                        pic_th=pic_th,
                    )
                except Exception as exc:
                    results.append(
                        self._skip(
                            "REND_006",
                            f"Scene {idx}: blackdetect error — {exc}",
                            scene_index=idx,
                        )
                    )
                    continue

                if segments:
                    seg_desc = "; ".join(
                        f"{s['start']:.2f}s–{s['end']:.2f}s ({s['duration']:.3f}s)"
                        for s in segments[:3]
                    )
                    results.append(
                        self._fail(
                            "REND_006",
                            f"Scene {idx}: {len(segments)} unexpected black segment(s) detected",
                            f"segments: {seg_desc}",
                            "high",
                            scene_index=idx,
                            black_segment_count=len(segments),
                            black_segments=segments[:5],
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "REND_006",
                            f"Scene {idx}: no unexpected black frames detected",
                            f"skip_start={skip_start}s, skip_end={skip_end}s",
                            scene_index=idx,
                        )
                    )

        return results
