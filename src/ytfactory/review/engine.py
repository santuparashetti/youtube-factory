"""Video Quality Review Engine V1 — orchestrator.

Runs the four validation stages in order, aggregates results into a
ReviewReport, determines PASS / FAIL, and returns the report.

Extension points:
  - Quality Scoring Engine V1: sets ReviewReport.quality_score
  - Root Cause Analysis Engine V1: implemented — populates review/root-cause*.json
  - Engine Feedback Loop V1: sets ReviewReport.feedback_payload
  - Auto Remediation Engine V1: consumes ReviewReport to trigger re-runs
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ytfactory.review.config import ReviewConfig
from ytfactory.review.models import ReviewReport, SceneReview
from ytfactory.review.rca.config import RCAConfig
from ytfactory.review.rca.engine import RootCauseAnalysisEngine
from ytfactory.review.rca.reporter import RCAReporter
from ytfactory.review.scoring.config import QualityScoringConfig
from ytfactory.review.scoring.engine import QualityScoringEngine
from ytfactory.review.scoring.reporter import QualityScoringReporter
from ytfactory.review.stages.asset_integrity import AssetIntegrityStage
from ytfactory.review.stages.content import ContentReviewStage
from ytfactory.review.stages.production import ProductionQualityStage
from ytfactory.review.stages.timeline import TimelineReviewStage
from ytfactory.review.validation.config import ValidationRulesConfig
from ytfactory.review.validation.reporter import ValidationReporter
from ytfactory.review.validation.runner import ValidationRunner
from ytfactory.shared.constants import WORKSPACE_DIR


class VideoQualityReviewEngine:
    """
    Orchestrate all four review stages, produce a ReviewReport, and
    determine PASS / FAIL.

    Usage:
        engine = VideoQualityReviewEngine()
        report = engine.review(project_id)
        if report.verdict == "FAIL":
            ...
    """

    def __init__(
        self,
        config: ReviewConfig | None = None,
        validation_config: ValidationRulesConfig | None = None,
        rca_config: RCAConfig | None = None,
        scoring_config: QualityScoringConfig | None = None,
    ) -> None:
        self._config = config or ReviewConfig()
        self._val_config = validation_config or ValidationRulesConfig()
        self._rca_config = rca_config or RCAConfig()
        self._scoring_config = scoring_config or QualityScoringConfig()
        self._stages = [
            AssetIntegrityStage(self._config),
            TimelineReviewStage(self._config),
            ContentReviewStage(self._config),
            ProductionQualityStage(self._config),
        ]

    # ── Public API ────────────────────────────────────────────────────────

    def review(self, project_id: str) -> ReviewReport:
        """Run the full review pipeline and return a ReviewReport."""
        t0 = time.perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()

        project_dir = Path(WORKSPACE_DIR) / project_id
        scenes = _load_scenes(project_dir)

        # Build per-scene review objects (shared across stages)
        scene_reviews = [
            SceneReview(
                index=s.get("index", i + 1),
                scene_type=s.get("scene_type", "generated_image"),
            )
            for i, s in enumerate(scenes)
        ]

        # Shared context dict — stages may deposit discovered values here
        context: dict = {}

        # ── Run stages ────────────────────────────────────────────────────
        stage_results = []
        for stage in self._stages:
            result = stage.run(project_dir, scenes, scene_reviews, context)
            stage_results.append(result)

        # ── Aggregate errors / warnings ───────────────────────────────────
        all_errors: list[str] = []
        all_warnings: list[str] = []
        for sr in stage_results:
            all_errors.extend(sr.errors)
            all_warnings.extend(sr.warnings)

        # Add per-scene issues as warnings (not critical errors)
        for sv in scene_reviews:
            for issue in sv.issues:
                all_warnings.append(f"Scene {sv.index}: {issue}")

        # ── Validation Rules V1 ───────────────────────────────────────────
        val_runner = ValidationRunner(self._val_config)
        val_report = val_runner.run(project_dir, scenes, context)
        ValidationReporter().write(val_report)

        # Critical validation failures bubble up into all_errors → affect verdict
        for failure in val_report.critical_failures:
            all_errors.append(f"[validation:{failure.rule_id}] {failure.description}")

        # ── Root Cause Analysis Engine V1 ────────────────────────────────
        rca_engine = RootCauseAnalysisEngine(self._rca_config)
        rca_report = rca_engine.analyze(project_dir, scenes, val_report, context)
        RCAReporter().write(rca_report)

        # ── Quality Scoring Engine V1 ─────────────────────────────────────
        score_engine = QualityScoringEngine(self._scoring_config)
        score_report = score_engine.score(project_dir, scenes, val_report, rca_report, context)
        QualityScoringReporter().write(score_report)

        # ── PASS / FAIL ───────────────────────────────────────────────────
        has_critical = bool(all_errors)
        if self._config.fail_on_warnings:
            verdict = "PASS" if not has_critical and not all_warnings else "FAIL"
        else:
            verdict = "PASS" if not has_critical else "FAIL"

        # ── Final video metadata ──────────────────────────────────────────
        final_video = project_dir / "video" / "final.mp4"
        final_size_mb = 0.0
        if final_video.exists():
            final_size_mb = final_video.stat().st_size / (1024 * 1024)

        elapsed = time.perf_counter() - t0

        report = ReviewReport(
            project_id=project_id,
            verdict=verdict,
            timestamp=timestamp,
            total_scenes=len(scenes),
            scenes_passed=sum(1 for sv in scene_reviews if sv.passed),
            scenes_failed=sum(1 for sv in scene_reviews if not sv.passed),
            stage_results=stage_results,
            scene_reviews=scene_reviews,
            all_errors=all_errors,
            all_warnings=all_warnings,
            final_video_path=str(final_video) if final_video.exists() else "",
            final_video_size_mb=round(final_size_mb, 2),
            final_video_duration_seconds=context.get(
                "final_video_duration_seconds", 0.0
            ),
            processing_time_seconds=round(elapsed, 3),
            validation_report=val_report.to_dict(),
            rca_report=rca_report.to_dict(),
            quality_score=score_report.overall_score,
            quality_score_report=score_report.to_dict(),
        )

        return report


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_scenes(project_dir: Path) -> list[dict]:
    """Load scene-plan.json; return empty list when missing."""
    scene_plan = project_dir / "scenes" / "scene-plan.json"
    if not scene_plan.exists():
        return []
    try:
        data = json.loads(scene_plan.read_text(encoding="utf-8"))
        return data.get("scenes", [])
    except (json.JSONDecodeError, OSError):
        return []
