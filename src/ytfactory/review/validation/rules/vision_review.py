"""Vision Review validation rules (category: vision_review).

These rules read pre-written image-review artifacts from the images/
directory rather than calling the vision model at validation time.
The ReviewPipeline remains completely model-agnostic.

Rules:
  VIS_001 [high]     — Image quality summary exists (review was run)
  VIS_002 [critical] — No scene failed vision review after all retries
  VIS_003 [medium]   — All scenes met minimum score threshold
  VIS_004 [low]      — Vision review pass rate meets overall threshold
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult


class VisionReviewValidator(BaseValidator):
    category = "vision_review"
    responsible_engine = "ImageReviewEngine"

    def validate(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        images_dir = project_dir / "images"
        summary_path = images_dir / "image-quality-summary.json"

        # VIS_001: Summary exists
        if self._config.is_enabled("VIS_001"):
            if not summary_path.exists():
                results.append(
                    self._skip(
                        "VIS_001",
                        "image-quality-summary.json not present — image review not enabled",
                    )
                )
                # Skip all other rules if review was not run
                for rule in ("VIS_002", "VIS_003", "VIS_004"):
                    if self._config.is_enabled(rule):
                        results.append(self._skip(rule, "image review not enabled"))
                return results
            else:
                results.append(
                    self._pass(
                        "VIS_001", "Image quality summary present", summary_path.name
                    )
                )

        # Load summary
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as exc:
            for rule in ("VIS_002", "VIS_003", "VIS_004"):
                if self._config.is_enabled(rule):
                    results.append(self._skip(rule, f"Could not read summary: {exc}"))
            return results

        reviewed = summary.get("reviewed", 0)
        passed = summary.get("passed", 0)
        scene_details: list[dict] = summary.get("scenes", [])
        pass_rate = summary.get("overall_pass_rate", 1.0)

        # VIS_002: No scene failed vision review after all retries
        if self._config.is_enabled("VIS_002"):
            failed_scenes = [
                s for s in scene_details if (s.get("status") or "").upper() == "FAIL"
            ]
            if failed_scenes:
                idx_list = [str(s.get("scene_index")) for s in failed_scenes[:5]]
                results.append(
                    self._fail(
                        "VIS_002",
                        f"{len(failed_scenes)} scene(s) failed vision review after all retries",
                        f"Failed scenes: {', '.join(idx_list)}",
                        "critical",
                        failed_count=len(failed_scenes),
                    )
                )
            else:
                results.append(
                    self._pass(
                        "VIS_002",
                        f"All {reviewed} reviewed scenes passed vision review",
                        f"reviewed={reviewed}, passed={passed}",
                    )
                )

        # VIS_003: All scenes met minimum score
        if self._config.is_enabled("VIS_003"):
            min_score = self._config.threshold_for("VIS_003", 90.0)
            low_score = [
                s
                for s in scene_details
                if (s.get("status") or "").upper() not in ("SKIP", "ERROR")
                and s.get("score", 100) < min_score
            ]
            if low_score:
                worst = min(low_score, key=lambda s: s.get("score", 0))
                results.append(
                    self._warn(
                        "VIS_003",
                        f"{len(low_score)} scene(s) below minimum score {min_score}",
                        f"Worst: scene {worst.get('scene_index')}, score={worst.get('score', 0):.0f}",
                        "medium",
                        low_score_count=len(low_score),
                        min_score=min_score,
                    )
                )
            else:
                results.append(
                    self._pass(
                        "VIS_003",
                        f"All scenes meet minimum score ({min_score})",
                        f"reviewed={reviewed}",
                    )
                )

        # VIS_004: Overall pass rate
        if self._config.is_enabled("VIS_004"):
            min_rate = self._config.threshold_for("VIS_004", 0.8)
            if reviewed == 0:
                results.append(self._skip("VIS_004", "No scenes reviewed"))
            elif pass_rate < min_rate:
                results.append(
                    self._warn(
                        "VIS_004",
                        f"Vision review pass rate {pass_rate:.0%} below threshold {min_rate:.0%}",
                        f"passed={passed}/{reviewed}, rate={pass_rate:.3f}",
                        "low",
                        pass_rate=pass_rate,
                        threshold=min_rate,
                    )
                )
            else:
                results.append(
                    self._pass(
                        "VIS_004",
                        f"Vision review pass rate {pass_rate:.0%} meets threshold",
                        f"passed={passed}/{reviewed}",
                    )
                )

        return results
