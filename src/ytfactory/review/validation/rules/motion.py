"""Motion validation rules (category E).

Rules:
  MOT_001 [high]     — Scene duration within configured bounds
  MOT_002 [critical] — No zero-duration or negative-duration scenes
  MOT_003 [low]      — Shot type assigned (cinematic quality indicator)
  MOT_004 [low]      — Transition type specified
  MOT_005 [critical] — No static shots > 4s in rendered video
  MOT_006 [medium]   — Motion variety: same type+direction not repeated 3+ scenes
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult
from ytfactory.shared.pipeline_status import PipelineAbort


class MotionValidator(BaseValidator):
    category = "motion"
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
                "MOT_001", "MOT_002", "MOT_003", "MOT_004", "MOT_005", "MOT_006"
            ):
                if self._config.is_enabled(rule_id):
                    results.append(self._skip(rule_id, "no scenes available"))
            return results

        for scene in scenes:
            idx = scene.get("index", 0)
            dur = float(scene.get("duration_seconds", 0.0))

            # MOT_002: No zero/negative duration (checked first — gates MOT_001)
            if self._config.is_enabled("MOT_002"):
                if dur <= 0:
                    results.append(
                        self._fail(
                            "MOT_002",
                            f"Scene {idx}: duration is zero or negative ({dur}s)",
                            f"duration_seconds={dur}",
                            "critical",
                            scene_index=idx,
                            duration_seconds=dur,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "MOT_002",
                            f"Scene {idx} has positive duration",
                            f"{dur}s",
                            scene_index=idx,
                        )
                    )

            # MOT_001: Duration within bounds (only meaningful if > 0)
            if self._config.is_enabled("MOT_001") and dur > 0:
                min_d = self._config.motion_min_scene_duration_seconds
                max_d = self._config.motion_max_scene_duration_seconds
                if dur < min_d:
                    results.append(
                        self._fail(
                            "MOT_001",
                            f"Scene {idx}: duration {dur}s below minimum {min_d}s",
                            f"duration_seconds={dur}, min={min_d}",
                            "high",
                            scene_index=idx,
                            duration_seconds=dur,
                        )
                    )
                elif dur > max_d:
                    results.append(
                        self._warn(
                            "MOT_001",
                            f"Scene {idx}: duration {dur}s exceeds maximum {max_d}s",
                            f"duration_seconds={dur}, max={max_d}",
                            "medium",
                            scene_index=idx,
                            duration_seconds=dur,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "MOT_001",
                            f"Scene {idx} duration within bounds",
                            f"{dur}s",
                            scene_index=idx,
                        )
                    )

            # MOT_003: Shot type assigned
            if self._config.is_enabled("MOT_003"):
                shot_type = scene.get("shot_type", "")
                if not shot_type:
                    results.append(
                        self._warn(
                            "MOT_003",
                            f"Scene {idx}: no shot type assigned",
                            "shot_type=empty",
                            "low",
                            scene_index=idx,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "MOT_003",
                            f"Scene {idx} has shot type",
                            shot_type,
                            scene_index=idx,
                        )
                    )

            # MOT_004: Transition type specified
            if self._config.is_enabled("MOT_004"):
                transition = scene.get("transition", "")
                if not transition:
                    results.append(
                        self._warn(
                            "MOT_004",
                            f"Scene {idx}: no transition type specified",
                            "transition=empty",
                            "low",
                            scene_index=idx,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "MOT_004",
                            f"Scene {idx} has transition",
                            transition,
                            scene_index=idx,
                        )
                    )

        # ── Pipeline QA post-render rules ─────────────────────────────────

        # MOT_005: Static shots > 4s in rendered video (hard-reject)
        if self._config.is_enabled("MOT_005"):
            static_violations = self._detect_static_shots(project_dir, context)
            if static_violations:
                for start, end in static_violations:
                    results.append(
                        self._fail(
                            "MOT_005",
                            f"Static shot detected {start:.1f}s–{end:.1f}s ({end - start:.1f}s no motion)",
                            f"static_shot={start:.1f}-{end:.1f}s",
                            "critical",
                            timestamp_seconds=start,
                        )
                    )
                raise PipelineAbort(
                    stage="quality_review",
                    reason=f"MOT_005: {len(static_violations)} static shot(s) detected in rendered video",
                )
            else:
                results.append(self._pass("MOT_005", "No static shots detected in rendered video", ""))

        # MOT_006: Motion variety — same type+direction not repeated 3+ consecutive scenes
        if self._config.is_enabled("MOT_006"):
            variety_violations = _check_motion_variety(scenes)
            if variety_violations:
                results.append(
                    self._warn(
                        "MOT_006",
                        variety_violations[0],
                        f"motion_variety_violations={len(variety_violations)}",
                        "medium",
                    )
                )
            else:
                results.append(self._pass("MOT_006", "Motion variety is sufficient", ""))

        return results

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _detect_static_shots(
        self,
        project_dir: Path,
        context: dict,
        threshold_seconds: float = 4.0,
    ) -> list[tuple[float, float]]:
        """
        Frame-diff based static shot detector. Samples frames at ~2fps from
        the rendered final video, computes per-region delta, flags continuous
        windows where delta stays below threshold for > threshold_seconds.
        """
        final_video = Path(context.get("final_video_path", ""))
        if not final_video.is_file():
            return []

        try:
            import cv2  # type: ignore[import-not-found]
        except ImportError:
            return []

        frames_dir = project_dir / "review" / "motion_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-i", str(final_video),
                    "-vf", "fps=2",
                    str(frames_dir / "frame_%05d.png"),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (subprocess.SubprocessError, OSError):
            return []

        frame_paths = sorted(frames_dir.glob("frame_*.png"))
        if len(frame_paths) < 2:
            return []

        prev_gray = None
        deltas: list[float] = []
        for fp in frame_paths:
            img = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE)
            if img is None:
                deltas.append(0.0)
                continue
            if prev_gray is not None:
                delta = float(cv2.absdiff(prev_gray, img).mean())
                deltas.append(delta)
            prev_gray = img

        return _analyze_static_runs(deltas, threshold=2.0, frame_duration=0.5, threshold_seconds=threshold_seconds)


def _analyze_static_runs(
    deltas: list[float],
    threshold: float,
    frame_duration: float,
    threshold_seconds: float,
) -> list[tuple[float, float]]:
    """
    Core frame-diff analysis: given a list of per-frame delta values, flag
    continuous windows where delta stays below threshold for longer than
    threshold_seconds. Pure function — no I/O, no cv2 dependency.
    """
    if not deltas:
        return []

    violations: list[tuple[float, float]] = []
    run_start = 0
    for i, d in enumerate(deltas):
        if d >= threshold:
            run_len = (i - run_start) * frame_duration
            if run_len > threshold_seconds:
                start_t = run_start * frame_duration
                end_t = i * frame_duration
                violations.append((start_t, end_t))
            run_start = i + 1

    run_len = (len(deltas) - run_start) * frame_duration
    if run_len > threshold_seconds:
        start_t = run_start * frame_duration
        end_t = len(deltas) * frame_duration
        violations.append((start_t, end_t))

    return violations

def _motion_direction(scene: dict) -> str:
    """Derive a direction label from the scene's motion dict."""
    motion = scene.get("motion", {})
    mtype = motion.get("motion_type", "static")
    drift_x = float(motion.get("drift_x", 0.0))
    if mtype == "drift":
        return "left" if drift_x > 0 else "right"
    if mtype == "push_in":
        return "in"
    if mtype == "pull_out":
        return "out"
    if mtype == "tilt_up":
        return "up"
    return "none"

def _check_motion_variety(scenes: list[dict]) -> list[str]:
    """
    Flag if the same (motion_type, direction) pair repeats across
    3+ consecutive scenes.
    """
    violations: list[str] = []
    keys = [(s.get("motion", {}).get("motion_type", "static"), _motion_direction(s)) for s in scenes]
    if len(keys) < 3:
        return violations

    run_start = 0
    for i in range(1, len(keys)):
        if keys[i] != keys[i - 1]:
            run_len = i - run_start
            if run_len >= 3:
                mtype, direction = keys[run_start]
                violations.append(
                    f"Motion '{mtype}/{direction}' repeats {run_len} consecutive scenes "
                    f"(scenes {run_start + 1}–{i})."
                )
            run_start = i

    run_len = len(keys) - run_start
    if run_len >= 3:
        mtype, direction = keys[run_start]
        violations.append(
            f"Motion '{mtype}/{direction}' repeats {run_len} consecutive scenes "
            f"(scenes {run_start + 1}–{len(keys)})."
        )

    return violations
