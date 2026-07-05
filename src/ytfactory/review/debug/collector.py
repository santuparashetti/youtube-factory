"""Debug data collection for Video Review Debug Mode V1.

DebugCollector is wired into VideoQualityReviewEngine.review() to capture
timing and diagnostic data from every pipeline layer without adding overhead
when debug is OFF.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Generator

from ytfactory.review.debug.config import DebugLevel
from ytfactory.review.debug.models import (
    CategoryScoringDebugEntry,
    DebugDiagnostics,
    DebugReport,
    ExecutionTimelineEntry,
    FeedbackDebugEntry,
    SceneDebugInfo,
    ValidationRuleDebugEntry,
)

if TYPE_CHECKING:
    from ytfactory.review.efl.models import EngineFeedbackReport
    from ytfactory.review.models import SceneReview, StageResult
    from ytfactory.review.scoring.models import QualityScoreReport
    from ytfactory.review.validation.models import ValidationReport


class DebugCollector:
    """Accumulates timing and diagnostic data during a review pipeline run.

    Usage in VideoQualityReviewEngine.review():
        debug = DebugCollector(config.level)
        with debug.time_layer("stages"):
            ...
        with debug.time_layer("validation"):
            ...
        if debug.enabled:
            report = debug.build_report(...)
            DebugReporter().write(report)
    """

    def __init__(self, level: DebugLevel) -> None:
        self._level = level
        self._layer_timings: dict[str, float] = {}
        self._timeline: list[ExecutionTimelineEntry] = []
        self._t0 = time.perf_counter()

    @property
    def enabled(self) -> bool:
        return self._level != DebugLevel.OFF

    @contextmanager
    def time_layer(self, layer_name: str) -> Generator[None, None, None]:
        """Context manager that records layer start/end events and elapsed time."""
        if not self.enabled:
            yield
            return
        ts_start = datetime.now(timezone.utc).isoformat()
        t = time.perf_counter()
        self._timeline.append(
            ExecutionTimelineEntry(
                event=f"{layer_name}:start",
                layer=layer_name,
                timestamp=ts_start,
            )
        )
        try:
            yield
        finally:
            elapsed = time.perf_counter() - t
            self._layer_timings[layer_name] = round(elapsed, 3)
            ts_end = datetime.now(timezone.utc).isoformat()
            self._timeline.append(
                ExecutionTimelineEntry(
                    event=f"{layer_name}:end",
                    layer=layer_name,
                    timestamp=ts_end,
                    duration_seconds=round(elapsed, 3),
                )
            )

    def build_report(
        self,
        project_id: str,
        timestamp: str,
        overall_verdict: str,
        all_errors: list[str],
        all_warnings: list[str],
        stage_results: list[StageResult],
        scene_reviews: list[SceneReview],
        val_report: ValidationReport | None,
        rca_report: object | None,
        score_report: QualityScoreReport | None,
        efl_report: EngineFeedbackReport | None,
    ) -> DebugReport:
        """Build a DebugReport from all post-run data."""
        total_elapsed = time.perf_counter() - self._t0

        stage_timings = {sr.stage_name: sr.duration_seconds for sr in stage_results}

        # Detect missing artifacts from scene reviews
        missing_artifacts: list[str] = []
        scenes_missing = 0
        for sv in scene_reviews:
            scene_had_missing = False
            if not sv.has_image:
                missing_artifacts.append(f"scene-{sv.index:03d}: no image")
                scene_had_missing = True
            if not sv.has_audio:
                missing_artifacts.append(f"scene-{sv.index:03d}: no audio")
                scene_had_missing = True
            if not sv.has_subtitle:
                missing_artifacts.append(f"scene-{sv.index:03d}: no subtitle")
                scene_had_missing = True
            if scene_had_missing:
                scenes_missing += 1

        diagnostics = DebugDiagnostics(
            total_processing_seconds=round(total_elapsed, 3),
            layer_timings=dict(self._layer_timings),
            stage_timings=stage_timings,
            missing_artifacts=missing_artifacts,
            error_count=len(all_errors),
            warning_count=len(all_warnings),
            total_scenes=len(scene_reviews),
            scenes_missing_assets=scenes_missing,
        )

        overall_score = score_report.overall_score if score_report is not None else None
        letter_grade = score_report.letter_grade if score_report is not None else None

        scene_debug = self._build_scene_debug(scene_reviews, val_report)
        validation_debug = self._build_validation_debug(val_report)
        scoring_debug = self._build_scoring_debug(score_report)
        feedback_debug = self._build_feedback_debug(efl_report)

        return DebugReport(
            project_id=project_id,
            timestamp=timestamp,
            debug_level=self._level.value,
            overall_verdict=overall_verdict,
            overall_score=overall_score,
            letter_grade=letter_grade,
            total_scenes=len(scene_reviews),
            total_errors=len(all_errors),
            total_warnings=len(all_warnings),
            diagnostics=diagnostics,
            timeline=list(self._timeline),
            scene_debug=scene_debug,
            validation_debug=validation_debug,
            scoring_debug=scoring_debug,
            feedback_debug=feedback_debug,
        )

    # ── Private extraction helpers ────────────────────────────────────────────

    def _build_scene_debug(
        self,
        scene_reviews: list[SceneReview],
        val_report: ValidationReport | None,
    ) -> list[SceneDebugInfo]:
        """Build per-scene debug info by correlating scene reviews with validation results."""
        scene_val_results: dict[int | None, list] = {}
        if val_report is not None:
            for r in val_report.results:
                scene_val_results.setdefault(r.scene_index, []).append(r)

        infos = []
        for sv in scene_reviews:
            scene_results = scene_val_results.get(sv.index, [])
            all_rule_ids = [r.rule_id for r in scene_results]
            failed_rule_ids = [
                r.rule_id for r in scene_results if r.status in ("FAIL", "WARNING")
            ]
            infos.append(
                SceneDebugInfo(
                    scene_index=sv.index,
                    has_image=sv.has_image,
                    has_audio=sv.has_audio,
                    has_subtitle=sv.has_subtitle,
                    has_video_clip=sv.has_video_clip,
                    narration_word_count=sv.narration_word_count,
                    declared_duration_seconds=sv.declared_duration_seconds,
                    validation_rule_ids=all_rule_ids,
                    failed_rule_ids=failed_rule_ids,
                    issues=list(sv.issues),
                )
            )
        return infos

    def _build_validation_debug(
        self,
        val_report: ValidationReport | None,
    ) -> list[ValidationRuleDebugEntry]:
        """Extract per-rule debug entries from the validation report."""
        if val_report is None:
            return []
        include_metadata = self._level == DebugLevel.VERBOSE
        return [
            ValidationRuleDebugEntry(
                rule_id=r.rule_id,
                category=r.category,
                status=r.status,
                severity=r.severity,
                confidence=r.confidence,
                evidence=r.evidence,
                responsible_engine=r.responsible_engine,
                description=r.description,
                scene_index=r.scene_index,
                debug_metadata=r.debug_metadata if include_metadata else {},
            )
            for r in val_report.results
        ]

    def _build_scoring_debug(
        self,
        score_report: QualityScoreReport | None,
    ) -> list[CategoryScoringDebugEntry]:
        """Extract per-category scoring debug entries."""
        if score_report is None:
            return []
        include_contributions = self._level in (DebugLevel.DETAILED, DebugLevel.VERBOSE)
        return [
            CategoryScoringDebugEntry(
                category=cs.category,
                raw_score=cs.raw_score,
                weighted_score=cs.weighted_score,
                weight=cs.weight,
                confidence=cs.confidence,
                summary=cs.summary,
                failed_rules=list(cs.failed_rules),
                contributions_count=len(cs.contributions),
                contributions=[c.to_dict() for c in cs.contributions]
                if include_contributions
                else [],
            )
            for cs in score_report.category_scores.values()
        ]

    def _build_feedback_debug(
        self,
        efl_report: EngineFeedbackReport | None,
    ) -> list[FeedbackDebugEntry]:
        """Extract per-feedback-item debug entries."""
        if efl_report is None:
            return []
        return [
            FeedbackDebugEntry(
                feedback_id=item.feedback_id,
                engine_owner=item.engine_owner,
                priority=item.priority,
                root_cause=item.root_cause,
                is_recurring=item.is_recurring,
                severity=item.severity,
                confidence=item.confidence,
                category=item.category,
                rule_id=item.rule_id,
                frequency=item.frequency,
                recommended_fix=item.recommended_fix,
            )
            for item in efl_report.feedback_items
        ]
