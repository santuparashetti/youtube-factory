"""ValidationRunner — orchestrates all 12 category validators.

Catches exceptions from individual validators so a single broken rule
cannot prevent the other categories from running.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ytfactory.review.validation.config import ValidationRulesConfig
from ytfactory.review.validation.models import ValidationReport, ValidationResult
from ytfactory.review.validation.rules.audio import AudioValidator
from ytfactory.review.validation.rules.bgm import BGMValidator
from ytfactory.review.validation.rules.human import HumanValidator
from ytfactory.review.validation.rules.image import ImageValidator
from ytfactory.review.validation.rules.motion import MotionValidator
from ytfactory.review.validation.rules.narration import NarrationValidator
from ytfactory.review.validation.rules.rendering import RenderingValidator
from ytfactory.review.validation.rules.script import ScriptValidator
from ytfactory.review.validation.rules.story import StoryValidator
from ytfactory.review.validation.rules.subtitle import SubtitleValidator
from ytfactory.review.validation.rules.cta import CTAValidator
from ytfactory.review.validation.rules.vision_review import VisionReviewValidator


class ValidationRunner:
    """Orchestrate all validation categories and produce a ValidationReport."""

    def __init__(self, config: ValidationRulesConfig | None = None) -> None:
        self._config = config or ValidationRulesConfig()

    def run(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> ValidationReport:
        """Run all 12 validators and aggregate results.

        Never raises — any validator exception is recorded as a SKIP result.
        """
        t0 = time.perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()

        if not self._config.enabled:
            return ValidationReport(
                project_id=project_dir.name,
                timestamp=timestamp,
                processing_time_seconds=round(time.perf_counter() - t0, 3),
            )

        validators = [
            ScriptValidator(self._config),
            NarrationValidator(self._config),
            SubtitleValidator(self._config),
            ImageValidator(self._config),
            HumanValidator(self._config),
            MotionValidator(self._config),
            AudioValidator(self._config),
            RenderingValidator(self._config),
            StoryValidator(self._config),
            BGMValidator(self._config),
            VisionReviewValidator(self._config),
            CTAValidator(self._config),
        ]

        all_results: list[ValidationResult] = []
        for validator in validators:
            try:
                results = validator.validate(project_dir, scenes, context)
                all_results.extend(results)
            except Exception as exc:  # noqa: BLE001
                all_results.append(
                    ValidationResult(
                        rule_id=f"{validator.category.upper()}_RUNNER_ERROR",
                        category=validator.category,
                        status="SKIP",
                        severity="low",
                        description=f"{validator.category} validator raised an exception",
                        evidence=str(exc),
                        confidence=0.0,
                        responsible_engine=validator.responsible_engine,
                        timestamp=timestamp,
                        debug_metadata={
                            "exception_type": type(exc).__name__,
                            "exception": str(exc),
                        },
                    )
                )

        # ── Aggregate ─────────────────────────────────────────────────────
        critical = [r for r in all_results if r.is_critical_failure]
        total_passed = sum(1 for r in all_results if r.status == "PASS")
        total_failed = sum(1 for r in all_results if r.status == "FAIL")
        total_warnings = sum(1 for r in all_results if r.status == "WARNING")
        total_skipped = sum(1 for r in all_results if r.status == "SKIP")

        # Per-category pass rates (SKIP excluded from denominator)
        by_category: dict[str, list[ValidationResult]] = defaultdict(list)
        for r in all_results:
            by_category[r.category].append(r)

        category_scores: dict[str, float] = {}
        for cat, cat_results in by_category.items():
            effective = [r for r in cat_results if r.status != "SKIP"]
            if effective:
                cat_pass = sum(1 for r in effective if r.status == "PASS")
                category_scores[cat] = round(cat_pass / len(effective), 3)
            else:
                category_scores[cat] = 1.0  # all skipped → neutral score

        elapsed = round(time.perf_counter() - t0, 3)

        return ValidationReport(
            project_id=project_dir.name,
            timestamp=timestamp,
            total_rules_run=len(all_results),
            total_passed=total_passed,
            total_failed=total_failed,
            total_warnings=total_warnings,
            total_skipped=total_skipped,
            critical_failures=critical,
            category_scores=category_scores,
            results=all_results,
            processing_time_seconds=elapsed,
        )
