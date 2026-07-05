"""Motion validation rules (category E).

Rules:
  MOT_001 [high]     — Scene duration within configured bounds
  MOT_002 [critical] — No zero-duration or negative-duration scenes
  MOT_003 [low]      — Shot type assigned (cinematic quality indicator)
  MOT_004 [low]      — Transition type specified
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult


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
            for rule_id in ("MOT_001", "MOT_002", "MOT_003", "MOT_004"):
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

        return results
