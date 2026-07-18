"""Human subject quality validation rules (category G).

Rules:
  HUM_001 [high]   — Human detected in prompt but missing quality reinforcement markers
  HUM_002 [medium] — Human in wide/establishing/drone shot without subject dominance guidance
  HUM_003 [high]   — Image sharpness below threshold for a human scene (blurry face)
  HUM_004 [high]   — Human Subject QA Gate (ADR-0015) failed for a human-critical scene
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.images.human_detector import (
    _SUBJECT_DOMINANCE_PHRASE,
    _WIDE_SHOT_TYPES,
    compute_sharpness,
    detect_human_presence,
    has_human_quality_reinforcement,
)
from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult

# Default sharpness threshold for HUM_003.
# Can be overridden via ValidationRulesConfig rules={"HUM_003": RuleConfig(threshold=10.0)}.
_DEFAULT_SHARPNESS_THRESHOLD = 8.0


class HumanValidator(BaseValidator):
    """Validate human subject quality in image prompts and generated images."""

    category = "human"
    responsible_engine = "Image Prompt Engine"

    _RULES = ("HUM_001", "HUM_002", "HUM_003", "HUM_004")

    def validate(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []

        generated = [
            s
            for s in scenes
            if s.get("scene_type", "generated_image") == "generated_image"
        ]

        if not generated:
            for rule_id in self._RULES:
                if self._config.is_enabled(rule_id):
                    results.append(self._skip(rule_id, "no generated scenes"))
            return results

        sharpness_threshold = self._config.threshold_for(
            "HUM_003", _DEFAULT_SHARPNESS_THRESHOLD
        )

        for scene in generated:
            idx = scene.get("index", 0)
            prompt = scene.get("visual_prompt", "")
            shot_type = scene.get("shot_type", "")

            if not detect_human_presence(prompt):
                continue

            # HUM_001: human quality markers present in prompt
            if self._config.is_enabled("HUM_001"):
                if has_human_quality_reinforcement(prompt):
                    results.append(
                        self._pass(
                            "HUM_001",
                            f"Scene {idx} human quality markers present",
                            "quality reinforcement confirmed",
                            scene_index=idx,
                        )
                    )
                else:
                    results.append(
                        self._fail(
                            "HUM_001",
                            f"Scene {idx}: human detected but prompt lacks quality reinforcement",
                            f"prompt excerpt: '{prompt[:80]}'",
                            "high",
                            scene_index=idx,
                        )
                    )

            # HUM_002: subject dominance for wide/establishing/drone shots
            if self._config.is_enabled("HUM_002"):
                is_wide = shot_type.lower().strip() in _WIDE_SHOT_TYPES
                dominance_hint = _SUBJECT_DOMINANCE_PHRASE.lstrip(", ")
                has_dominance = dominance_hint in prompt

                if not is_wide:
                    results.append(
                        self._skip(
                            "HUM_002",
                            f"scene {idx} is not a wide/establishing/drone shot",
                            scene_index=idx,
                        )
                    )
                elif has_dominance:
                    results.append(
                        self._pass(
                            "HUM_002",
                            f"Scene {idx} has subject dominance guidance",
                            f"shot_type={shot_type!r}",
                            scene_index=idx,
                        )
                    )
                else:
                    results.append(
                        self._warn(
                            "HUM_002",
                            f"Scene {idx}: wide shot with human but no subject dominance guidance",
                            f"shot_type={shot_type!r}, add: '{dominance_hint}'",
                            "medium",
                            scene_index=idx,
                            shot_type=shot_type,
                        )
                    )

            # HUM_003: image sharpness for human scenes
            if self._config.is_enabled("HUM_003"):
                img_path = project_dir / "images" / f"scene-{idx:03d}.png"
                if not img_path.exists():
                    results.append(
                        self._skip(
                            "HUM_003",
                            f"scene {idx} image file missing (covered by IMG_001)",
                            scene_index=idx,
                        )
                    )
                else:
                    sharpness = compute_sharpness(img_path)
                    if sharpness >= sharpness_threshold:
                        results.append(
                            self._pass(
                                "HUM_003",
                                f"Scene {idx} human image sharpness OK",
                                f"sharpness={sharpness:.1f} >= threshold={sharpness_threshold}",
                                scene_index=idx,
                                sharpness=sharpness,
                            )
                        )
                    else:
                        results.append(
                            self._fail(
                                "HUM_003",
                                f"Scene {idx}: human image sharpness too low ({sharpness:.1f})",
                                f"sharpness={sharpness:.1f} < threshold={sharpness_threshold}",
                                "high",
                                scene_index=idx,
                                sharpness=sharpness,
                                threshold=sharpness_threshold,
                            )
                        )

            # HUM_004: Human Subject QA Gate outcome (ADR-0015)
            if self._config.is_enabled("HUM_004"):
                review_path = project_dir / "images" / f"image-review-{idx:03d}.json"
                if not review_path.exists():
                    results.append(
                        self._skip(
                            "HUM_004",
                            f"scene {idx}: no image review artifact (review not run)",
                            scene_index=idx,
                        )
                    )
                else:
                    try:
                        data = json.loads(review_path.read_text(encoding="utf-8"))
                    except Exception:
                        results.append(
                            self._skip(
                                "HUM_004",
                                f"scene {idx}: could not read image review artifact",
                                scene_index=idx,
                            )
                        )
                        continue

                    if not data.get("human_qa_triggered", False):
                        results.append(
                            self._skip(
                                "HUM_004",
                                f"scene {idx}: human QA gate not triggered (non-critical scene)",
                                scene_index=idx,
                            )
                        )
                    elif data.get("human_qa_passed", False):
                        results.append(
                            self._pass(
                                "HUM_004",
                                f"Scene {idx}: Human Subject QA Gate passed",
                                "all staged checks: human QA, hand QA, clothing QA, prompt compliance",
                                scene_index=idx,
                            )
                        )
                    else:
                        failed_stages = [
                            label
                            for key, label in (
                                ("human_qa_status", "human QA"),
                                ("hand_qa_status", "hand QA"),
                                ("clothing_qa_status", "clothing QA"),
                                ("prompt_compliance_status", "prompt compliance"),
                            )
                            if data.get(key) == "FAIL"
                        ]
                        stage_list = ", ".join(failed_stages) if failed_stages else "see artifact"
                        results.append(
                            self._fail(
                                "HUM_004",
                                f"Scene {idx}: Human Subject QA Gate failed — {stage_list}",
                                f"artifact: {review_path.name}",
                                "high",
                                scene_index=idx,
                                failed_stages=failed_stages,
                            )
                        )

        return results
