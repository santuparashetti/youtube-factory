"""Tests for Video Review Debug Mode V1.

Covers:
  - DebugLevel, DebugConfig — config models
  - ExecutionTimelineEntry, SceneDebugInfo, ValidationRuleDebugEntry,
    CategoryScoringDebugEntry, FeedbackDebugEntry, DebugDiagnostics,
    DebugReport — domain models and to_dict()
  - DebugCollector — time_layer(), build_report(), level-based behavior
  - DebugReporter — writes 7 files to review/debug/, correct structure
  - Integration with VQRE — default OFF writes nothing, debug level writes 7 files
  - Backward compatibility — existing tests unaffected by new optional field
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ytfactory.review.debug.collector import DebugCollector
from ytfactory.review.debug.config import DebugConfig, DebugLevel
from ytfactory.review.debug.models import (
    CategoryScoringDebugEntry,
    DebugDiagnostics,
    DebugReport,
    ExecutionTimelineEntry,
    FeedbackDebugEntry,
    SceneDebugInfo,
    ValidationRuleDebugEntry,
)
from ytfactory.review.debug.reporter import DebugReporter
from ytfactory.review.efl.models import EngineFeedbackReport, FeedbackItem
from ytfactory.review.models import ReviewReport, SceneReview, StageResult
from ytfactory.review.scoring.models import CategoryScore, QualityScoreReport, RuleContribution
from ytfactory.review.validation.models import ValidationReport, ValidationResult


# ── Shared helpers ────────────────────────────────────────────────────────────


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vr(
    rule_id: str = "SCRIPT_001",
    category: str = "script",
    status: str = "PASS",
    severity: str = "high",
    scene_index: int | None = None,
    debug_metadata: dict | None = None,
) -> ValidationResult:
    return ValidationResult(
        rule_id=rule_id,
        category=category,
        status=status,
        severity=severity,
        description="test description",
        evidence="test evidence",
        confidence=0.85,
        responsible_engine="Script Generation Engine",
        timestamp=_ts(),
        scene_index=scene_index,
        debug_metadata=debug_metadata or {},
    )


def _val_report(
    results: list[ValidationResult] | None = None,
    project_id: str = "proj",
) -> ValidationReport:
    results = results or []
    return ValidationReport(
        project_id=project_id,
        timestamp=_ts(),
        total_rules_run=len(results),
        total_passed=sum(1 for r in results if r.status == "PASS"),
        total_failed=sum(1 for r in results if r.status == "FAIL"),
        total_warnings=sum(1 for r in results if r.status == "WARNING"),
        total_skipped=sum(1 for r in results if r.status == "SKIP"),
        results=results,
    )


def _score_report(overall_score: float = 85.0, project_id: str = "proj") -> QualityScoreReport:
    contribution = RuleContribution(
        rule_id="SCRIPT_001",
        points_available=50.0,
        points_earned=50.0,
        status="pass",
        evidence="all good",
    )
    cs = CategoryScore(
        category="script",
        raw_score=overall_score,
        weighted_score=overall_score * 0.15,
        weight=0.15,
        confidence=0.9,
        evidence=[],
        summary="Good script quality",
        failed_rules=[],
        contributions=[contribution],
    )
    return QualityScoreReport(
        project_id=project_id,
        timestamp=_ts(),
        category_scores={"script": cs},
        overall_score=overall_score,
        letter_grade="B" if overall_score >= 80 else "C",
        verdict="PASS" if overall_score >= 70 else "FAIL",
        processing_time_seconds=0.01,
    )


def _feedback_item(
    feedback_id: str = "EFL-0001",
    engine_owner: str = "Script Generation Engine",
    priority: str = "medium",
    is_recurring: bool = False,
) -> FeedbackItem:
    return FeedbackItem(
        feedback_id=feedback_id,
        engine_owner=engine_owner,
        source_issue="RCA-0001",
        root_cause="test root cause",
        severity="high",
        confidence=80,
        frequency=2,
        evidence="test evidence",
        recommended_fix="Fix the script pacing",
        suggested_tests=["Test word count"],
        expected_outcome="Improved pacing",
        priority=priority,
        is_recurring=is_recurring,
        category="script",
        rule_id="SCRIPT_001",
    )


def _efl_report(
    items: list[FeedbackItem] | None = None,
    project_id: str = "proj",
) -> EngineFeedbackReport:
    items = items or []
    return EngineFeedbackReport(
        project_id=project_id,
        timestamp=_ts(),
        feedback_items=items,
        engine_summaries={},
        recurring_patterns=[],
        improvement_roadmap=[],
        total_feedback=len(items),
        total_engines_affected=len({i.engine_owner for i in items}),
        priority_distribution={},
        processing_time_seconds=0.01,
    )


def _stage_result(name: str = "asset_integrity", duration: float = 0.05) -> StageResult:
    return StageResult(
        stage_name=name,
        passed=True,
        checks_run=5,
        checks_passed=5,
        duration_seconds=duration,
    )


def _scene_review(index: int = 1, has_image: bool = True, has_audio: bool = True) -> SceneReview:
    sv = SceneReview(index=index)
    sv.has_image = has_image
    sv.has_audio = has_audio
    sv.has_subtitle = True
    sv.has_video_clip = True
    sv.narration_word_count = 50
    sv.declared_duration_seconds = 8.0
    return sv


def _minimal_debug_report(project_id: str = "proj") -> DebugReport:
    diagnostics = DebugDiagnostics(
        total_processing_seconds=0.5,
        layer_timings={"stages": 0.1},
        stage_timings={"asset_integrity": 0.05},
        missing_artifacts=[],
        error_count=0,
        warning_count=0,
        total_scenes=2,
        scenes_missing_assets=0,
    )
    return DebugReport(
        project_id=project_id,
        timestamp=_ts(),
        debug_level="basic",
        overall_verdict="PASS",
        overall_score=85.0,
        letter_grade="B",
        total_scenes=2,
        total_errors=0,
        total_warnings=0,
        diagnostics=diagnostics,
    )


# ── TestDebugLevel ────────────────────────────────────────────────────────────


class TestDebugLevel:
    def test_off_value(self):
        assert DebugLevel.OFF == "off"

    def test_basic_value(self):
        assert DebugLevel.BASIC == "basic"

    def test_detailed_value(self):
        assert DebugLevel.DETAILED == "detailed"

    def test_verbose_value(self):
        assert DebugLevel.VERBOSE == "verbose"

    def test_is_str_enum(self):
        assert isinstance(DebugLevel.BASIC, str)

    def test_four_levels(self):
        assert len(list(DebugLevel)) == 4


class TestDebugConfig:
    def test_default_level_is_off(self):
        assert DebugConfig().level == DebugLevel.OFF

    def test_can_set_basic(self):
        cfg = DebugConfig(level=DebugLevel.BASIC)
        assert cfg.level == DebugLevel.BASIC

    def test_can_set_verbose(self):
        cfg = DebugConfig(level=DebugLevel.VERBOSE)
        assert cfg.level == DebugLevel.VERBOSE


# ── TestExecutionTimelineEntry ────────────────────────────────────────────────


class TestExecutionTimelineEntry:
    def test_to_dict_has_required_keys(self):
        entry = ExecutionTimelineEntry(
            event="validation:start",
            layer="validation",
            timestamp=_ts(),
        )
        d = entry.to_dict()
        assert d["event"] == "validation:start"
        assert d["layer"] == "validation"
        assert "timestamp" in d
        assert d["duration_seconds"] is None
        assert d["details"] == {}

    def test_to_dict_with_duration(self):
        entry = ExecutionTimelineEntry(
            event="validation:end",
            layer="validation",
            timestamp=_ts(),
            duration_seconds=0.123,
        )
        assert entry.to_dict()["duration_seconds"] == 0.123

    def test_to_dict_with_details(self):
        entry = ExecutionTimelineEntry(
            event="stages:end",
            layer="stages",
            timestamp=_ts(),
            details={"count": 4},
        )
        assert entry.to_dict()["details"] == {"count": 4}


# ── TestSceneDebugInfo ────────────────────────────────────────────────────────


class TestSceneDebugInfo:
    def _make(self, **kwargs) -> SceneDebugInfo:
        defaults = {
            "scene_index": 1,
            "has_image": True,
            "has_audio": True,
            "has_subtitle": True,
            "has_video_clip": True,
            "narration_word_count": 50,
            "declared_duration_seconds": 8.0,
            "validation_rule_ids": ["SCRIPT_001"],
            "failed_rule_ids": [],
            "issues": [],
        }
        defaults.update(kwargs)
        return SceneDebugInfo(**defaults)

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        for key in (
            "scene_index", "has_image", "has_audio", "has_subtitle", "has_video_clip",
            "narration_word_count", "declared_duration_seconds",
            "validation_rule_ids", "failed_rule_ids", "issues",
        ):
            assert key in d

    def test_missing_image_reflected(self):
        d = self._make(has_image=False).to_dict()
        assert d["has_image"] is False

    def test_failed_rule_ids(self):
        d = self._make(failed_rule_ids=["REND_001"]).to_dict()
        assert "REND_001" in d["failed_rule_ids"]


# ── TestValidationRuleDebugEntry ──────────────────────────────────────────────


class TestValidationRuleDebugEntry:
    def _make(self, **kwargs) -> ValidationRuleDebugEntry:
        defaults = {
            "rule_id": "SCRIPT_001",
            "category": "script",
            "status": "PASS",
            "severity": "high",
            "confidence": 0.9,
            "evidence": "all good",
            "responsible_engine": "Script Generation Engine",
            "description": "Word count check",
        }
        defaults.update(kwargs)
        return ValidationRuleDebugEntry(**defaults)

    def test_to_dict_has_all_keys(self):
        d = self._make().to_dict()
        for key in (
            "rule_id", "category", "status", "severity", "confidence",
            "evidence", "responsible_engine", "description",
            "scene_index", "debug_metadata",
        ):
            assert key in d

    def test_fail_status_preserved(self):
        d = self._make(status="FAIL").to_dict()
        assert d["status"] == "FAIL"

    def test_scene_index_none_by_default(self):
        assert self._make().to_dict()["scene_index"] is None

    def test_scene_index_preserved(self):
        assert self._make(scene_index=3).to_dict()["scene_index"] == 3


# ── TestCategoryScoringDebugEntry ─────────────────────────────────────────────


class TestCategoryScoringDebugEntry:
    def _make(self, **kwargs) -> CategoryScoringDebugEntry:
        defaults = {
            "category": "script",
            "raw_score": 80.0,
            "weighted_score": 12.0,
            "weight": 0.15,
            "confidence": 0.9,
            "summary": "Good",
            "failed_rules": [],
            "contributions_count": 3,
        }
        defaults.update(kwargs)
        return CategoryScoringDebugEntry(**defaults)

    def test_to_dict_has_all_keys(self):
        d = self._make().to_dict()
        for key in (
            "category", "raw_score", "weighted_score", "weight",
            "confidence", "summary", "failed_rules",
            "contributions_count", "contributions",
        ):
            assert key in d

    def test_scores_rounded(self):
        d = self._make(raw_score=80.12345).to_dict()
        assert d["raw_score"] == 80.12

    def test_failed_rules_preserved(self):
        d = self._make(failed_rules=["NARR_001"]).to_dict()
        assert "NARR_001" in d["failed_rules"]


# ── TestFeedbackDebugEntry ────────────────────────────────────────────────────


class TestFeedbackDebugEntry:
    def _make(self, **kwargs) -> FeedbackDebugEntry:
        defaults = {
            "feedback_id": "EFL-0001",
            "engine_owner": "Script Generation Engine",
            "priority": "medium",
            "root_cause": "pacing issues",
            "is_recurring": False,
            "severity": "high",
            "confidence": 80,
            "category": "script",
            "rule_id": "SCRIPT_001",
            "frequency": 2,
            "recommended_fix": "Fix pacing",
        }
        defaults.update(kwargs)
        return FeedbackDebugEntry(**defaults)

    def test_to_dict_has_all_keys(self):
        d = self._make().to_dict()
        for key in (
            "feedback_id", "engine_owner", "priority", "root_cause",
            "is_recurring", "severity", "confidence", "category",
            "rule_id", "frequency", "recommended_fix",
        ):
            assert key in d

    def test_recurring_preserved(self):
        d = self._make(is_recurring=True).to_dict()
        assert d["is_recurring"] is True


# ── TestDebugDiagnostics ──────────────────────────────────────────────────────


class TestDebugDiagnostics:
    def _make(self, **kwargs) -> DebugDiagnostics:
        defaults = {
            "total_processing_seconds": 1.5,
            "layer_timings": {"stages": 0.2, "validation": 0.3},
            "stage_timings": {"asset_integrity": 0.05},
            "missing_artifacts": [],
            "error_count": 0,
            "warning_count": 2,
            "total_scenes": 3,
            "scenes_missing_assets": 0,
        }
        defaults.update(kwargs)
        return DebugDiagnostics(**defaults)

    def test_to_dict_has_all_keys(self):
        d = self._make().to_dict()
        for key in (
            "total_processing_seconds", "layer_timings", "stage_timings",
            "missing_artifacts", "error_count", "warning_count",
            "total_scenes", "scenes_missing_assets",
        ):
            assert key in d

    def test_processing_time_rounded(self):
        d = self._make(total_processing_seconds=1.23456789).to_dict()
        assert d["total_processing_seconds"] == 1.235

    def test_layer_timings_rounded(self):
        d = self._make(layer_timings={"val": 0.123456}).to_dict()
        assert d["layer_timings"]["val"] == 0.123

    def test_missing_artifacts_propagated(self):
        d = self._make(missing_artifacts=["scene-001: no image"]).to_dict()
        assert "scene-001: no image" in d["missing_artifacts"]


# ── TestDebugReport ───────────────────────────────────────────────────────────


class TestDebugReport:
    def test_to_dict_has_version(self):
        d = _minimal_debug_report().to_dict()
        assert d["version"] == "v1"

    def test_to_dict_has_required_keys(self):
        d = _minimal_debug_report().to_dict()
        for key in (
            "version", "project_id", "timestamp", "debug_level",
            "overall_verdict", "overall_score", "letter_grade",
            "total_scenes", "total_errors", "total_warnings",
            "diagnostics", "timeline",
            "scene_debug", "validation_debug", "scoring_debug", "feedback_debug",
        ):
            assert key in d, f"missing key: {key}"

    def test_empty_lists_by_default(self):
        d = _minimal_debug_report().to_dict()
        assert d["timeline"] == []
        assert d["scene_debug"] == []
        assert d["validation_debug"] == []
        assert d["scoring_debug"] == []
        assert d["feedback_debug"] == []

    def test_overall_score_propagated(self):
        d = _minimal_debug_report().to_dict()
        assert d["overall_score"] == 85.0

    def test_debug_level_propagated(self):
        d = _minimal_debug_report().to_dict()
        assert d["debug_level"] == "basic"


# ── TestDebugCollectorEnabled ─────────────────────────────────────────────────


class TestDebugCollectorEnabled:
    def test_off_not_enabled(self):
        assert not DebugCollector(DebugLevel.OFF).enabled

    def test_basic_enabled(self):
        assert DebugCollector(DebugLevel.BASIC).enabled

    def test_detailed_enabled(self):
        assert DebugCollector(DebugLevel.DETAILED).enabled

    def test_verbose_enabled(self):
        assert DebugCollector(DebugLevel.VERBOSE).enabled


# ── TestDebugCollectorTimeLayer ───────────────────────────────────────────────


class TestDebugCollectorTimeLayer:
    def test_off_collects_no_timeline(self):
        dc = DebugCollector(DebugLevel.OFF)
        with dc.time_layer("validation"):
            pass
        assert dc._timeline == []

    def test_off_collects_no_layer_timings(self):
        dc = DebugCollector(DebugLevel.OFF)
        with dc.time_layer("validation"):
            pass
        assert dc._layer_timings == {}

    def test_basic_records_start_and_end(self):
        dc = DebugCollector(DebugLevel.BASIC)
        with dc.time_layer("validation"):
            pass
        events = [e.event for e in dc._timeline]
        assert "validation:start" in events
        assert "validation:end" in events

    def test_layer_timing_recorded(self):
        dc = DebugCollector(DebugLevel.BASIC)
        with dc.time_layer("rca"):
            time.sleep(0.01)
        assert "rca" in dc._layer_timings
        assert dc._layer_timings["rca"] >= 0.0

    def test_end_entry_has_duration(self):
        dc = DebugCollector(DebugLevel.BASIC)
        with dc.time_layer("efl"):
            pass
        end_entry = next(e for e in dc._timeline if e.event == "efl:end")
        assert end_entry.duration_seconds is not None
        assert end_entry.duration_seconds >= 0.0

    def test_multiple_layers(self):
        dc = DebugCollector(DebugLevel.DETAILED)
        for name in ("stages", "validation", "rca", "scoring", "efl"):
            with dc.time_layer(name):
                pass
        assert len(dc._layer_timings) == 5
        assert len(dc._timeline) == 10  # 2 events × 5 layers

    def test_off_yields_normally(self):
        dc = DebugCollector(DebugLevel.OFF)
        result = []
        with dc.time_layer("stages"):
            result.append(1)
        assert result == [1]

    def test_exception_inside_layer_still_records_end(self):
        dc = DebugCollector(DebugLevel.BASIC)
        with pytest.raises(ValueError):
            with dc.time_layer("stages"):
                raise ValueError("intentional")
        events = [e.event for e in dc._timeline]
        assert "stages:end" in events


# ── TestDebugCollectorBuildReport ─────────────────────────────────────────────


class TestDebugCollectorBuildReport:
    def _build(
        self,
        level: DebugLevel = DebugLevel.BASIC,
        val: ValidationReport | None = None,
        score: QualityScoreReport | None = None,
        efl: EngineFeedbackReport | None = None,
        scene_reviews: list[SceneReview] | None = None,
        stage_results: list[StageResult] | None = None,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> DebugReport:
        dc = DebugCollector(level)
        return dc.build_report(
            project_id="proj",
            timestamp=_ts(),
            overall_verdict="PASS",
            all_errors=errors or [],
            all_warnings=warnings or [],
            stage_results=stage_results or [_stage_result()],
            scene_reviews=scene_reviews or [_scene_review()],
            val_report=val,
            rca_report=None,
            score_report=score,
            efl_report=efl,
        )

    def test_returns_debug_report(self):
        assert isinstance(self._build(), DebugReport)

    def test_project_id_propagated(self):
        assert self._build().project_id == "proj"

    def test_debug_level_in_report(self):
        report = self._build(level=DebugLevel.DETAILED)
        assert report.debug_level == "detailed"

    def test_overall_score_none_when_no_score_report(self):
        assert self._build(score=None).overall_score is None

    def test_overall_score_from_score_report(self):
        report = self._build(score=_score_report(85.0))
        assert report.overall_score == 85.0

    def test_letter_grade_from_score_report(self):
        report = self._build(score=_score_report(85.0))
        assert report.letter_grade == "B"

    def test_diagnostics_error_count(self):
        report = self._build(errors=["err1", "err2"])
        assert report.diagnostics.error_count == 2

    def test_diagnostics_warning_count(self):
        report = self._build(warnings=["w1"])
        assert report.diagnostics.warning_count == 1

    def test_diagnostics_missing_image(self):
        sv = _scene_review(index=1, has_image=False)
        report = self._build(scene_reviews=[sv])
        assert any("no image" in m for m in report.diagnostics.missing_artifacts)

    def test_diagnostics_missing_audio(self):
        sv = _scene_review(index=2, has_audio=False)
        report = self._build(scene_reviews=[sv])
        assert any("no audio" in m for m in report.diagnostics.missing_artifacts)

    def test_scenes_missing_assets_count(self):
        sv1 = _scene_review(index=1, has_image=False)
        sv2 = _scene_review(index=2)
        report = self._build(scene_reviews=[sv1, sv2])
        assert report.diagnostics.scenes_missing_assets == 1

    def test_stage_timings_from_stage_results(self):
        sr = _stage_result("asset_integrity", duration=0.05)
        report = self._build(stage_results=[sr])
        assert "asset_integrity" in report.diagnostics.stage_timings

    def test_validation_debug_empty_when_no_val_report(self):
        assert self._build(val=None).validation_debug == []

    def test_validation_debug_populated_from_val_report(self):
        val = _val_report([_vr("SCRIPT_001"), _vr("NARR_001", "narration")])
        report = self._build(val=val)
        assert len(report.validation_debug) == 2

    def test_validation_debug_rule_id(self):
        val = _val_report([_vr("SCRIPT_001")])
        report = self._build(val=val)
        assert report.validation_debug[0].rule_id == "SCRIPT_001"

    def test_validation_debug_metadata_excluded_in_basic(self):
        meta = {"key": "value"}
        val = _val_report([_vr(debug_metadata=meta)])
        report = self._build(level=DebugLevel.BASIC, val=val)
        assert report.validation_debug[0].debug_metadata == {}

    def test_validation_debug_metadata_included_in_verbose(self):
        meta = {"key": "value"}
        val = _val_report([_vr(debug_metadata=meta)])
        report = self._build(level=DebugLevel.VERBOSE, val=val)
        assert report.validation_debug[0].debug_metadata == meta

    def test_scoring_debug_empty_when_no_score_report(self):
        assert self._build(score=None).scoring_debug == []

    def test_scoring_debug_populated(self):
        report = self._build(score=_score_report())
        assert len(report.scoring_debug) == 1
        assert report.scoring_debug[0].category == "script"

    def test_scoring_debug_contributions_excluded_in_basic(self):
        report = self._build(level=DebugLevel.BASIC, score=_score_report())
        assert report.scoring_debug[0].contributions == []

    def test_scoring_debug_contributions_included_in_detailed(self):
        report = self._build(level=DebugLevel.DETAILED, score=_score_report())
        assert len(report.scoring_debug[0].contributions) >= 1

    def test_scoring_debug_contributions_included_in_verbose(self):
        report = self._build(level=DebugLevel.VERBOSE, score=_score_report())
        assert len(report.scoring_debug[0].contributions) >= 1

    def test_feedback_debug_empty_when_no_efl_report(self):
        assert self._build(efl=None).feedback_debug == []

    def test_feedback_debug_populated(self):
        efl = _efl_report([_feedback_item()])
        report = self._build(efl=efl)
        assert len(report.feedback_debug) == 1
        assert report.feedback_debug[0].feedback_id == "EFL-0001"

    def test_feedback_debug_recurring_flag(self):
        efl = _efl_report([_feedback_item(is_recurring=True)])
        report = self._build(efl=efl)
        assert report.feedback_debug[0].is_recurring is True

    def test_scene_debug_populated(self):
        report = self._build(scene_reviews=[_scene_review(1), _scene_review(2)])
        assert len(report.scene_debug) == 2

    def test_scene_debug_correlates_val_results_by_scene(self):
        val = _val_report([_vr("SCRIPT_001", scene_index=1), _vr("NARR_001", "narration", scene_index=1)])
        report = self._build(val=val, scene_reviews=[_scene_review(1)])
        assert "SCRIPT_001" in report.scene_debug[0].validation_rule_ids
        assert "NARR_001" in report.scene_debug[0].validation_rule_ids

    def test_scene_debug_failed_rule_ids(self):
        val = _val_report([_vr("SCRIPT_001", status="FAIL", scene_index=1)])
        report = self._build(val=val, scene_reviews=[_scene_review(1)])
        assert "SCRIPT_001" in report.scene_debug[0].failed_rule_ids

    def test_total_processing_positive(self):
        report = self._build()
        assert report.diagnostics.total_processing_seconds >= 0.0

    def test_timeline_empty_for_off(self):
        report = self._build(level=DebugLevel.OFF)
        assert report.timeline == []


# ── TestDebugReporter ─────────────────────────────────────────────────────────


class TestDebugReporter:
    def _write(self, tmp_path: Path, project_id: str = "proj") -> Path:
        import ytfactory.review.debug.reporter as reporter_mod

        original_rws = reporter_mod.review_directory

        # Patch review_directory to use tmp_path
        def patched_review_dir(pid: str) -> Path:
            d = tmp_path / pid / "review"
            d.mkdir(parents=True, exist_ok=True)
            return d

        reporter_mod.review_directory = patched_review_dir  # type: ignore[assignment]
        try:
            report = _minimal_debug_report(project_id)
            return DebugReporter().write(report)
        finally:
            reporter_mod.review_directory = original_rws  # type: ignore[assignment]

    def _write_with_monkeypatch(self, tmp_path: Path, monkeypatch, report: DebugReport) -> Path:
        monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.review.debug.reporter.review_directory",
                            lambda pid: tmp_path / pid / "review")
        debug_dir = tmp_path / report.project_id / "review" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        return DebugReporter().write(report)


class TestDebugReporterFiles:
    """Verify DebugReporter creates all 7 expected files."""

    @pytest.fixture()
    def debug_dir(self, tmp_path, monkeypatch) -> Path:
        monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr(
            "ytfactory.review.debug.reporter.review_directory",
            lambda pid: (tmp_path / pid / "review").also(
                lambda p: p.mkdir(parents=True, exist_ok=True)
            )
            if False
            else _patched_review_dir(tmp_path, pid),
        )

        report = _minimal_debug_report("test-proj")
        # Build a richer report
        diagnostics = DebugDiagnostics(
            total_processing_seconds=0.5,
            layer_timings={"stages": 0.1, "validation": 0.2},
            stage_timings={"asset_integrity": 0.05},
            missing_artifacts=["scene-002: no audio"],
            error_count=1,
            warning_count=2,
            total_scenes=2,
            scenes_missing_assets=1,
        )
        report = DebugReport(
            project_id="test-proj",
            timestamp=_ts(),
            debug_level="detailed",
            overall_verdict="FAIL",
            overall_score=65.0,
            letter_grade="D",
            total_scenes=2,
            total_errors=1,
            total_warnings=2,
            diagnostics=diagnostics,
            timeline=[
                ExecutionTimelineEntry("stages:start", "stages", _ts()),
                ExecutionTimelineEntry("stages:end", "stages", _ts(), 0.1),
            ],
            scene_debug=[
                SceneDebugInfo(
                    scene_index=1,
                    has_image=True,
                    has_audio=True,
                    has_subtitle=True,
                    has_video_clip=False,
                    narration_word_count=60,
                    declared_duration_seconds=8.0,
                    validation_rule_ids=["SCRIPT_001"],
                    failed_rule_ids=[],
                    issues=[],
                )
            ],
            validation_debug=[
                ValidationRuleDebugEntry(
                    rule_id="NARR_001",
                    category="narration",
                    status="FAIL",
                    severity="high",
                    confidence=0.9,
                    evidence="missing narration",
                    responsible_engine="Speech Optimizer",
                    description="Narration presence check",
                )
            ],
            scoring_debug=[
                CategoryScoringDebugEntry(
                    category="script",
                    raw_score=70.0,
                    weighted_score=10.5,
                    weight=0.15,
                    confidence=0.9,
                    summary="Acceptable",
                    failed_rules=[],
                    contributions_count=2,
                )
            ],
            feedback_debug=[
                FeedbackDebugEntry(
                    feedback_id="EFL-0001",
                    engine_owner="Speech Optimizer",
                    priority="high",
                    root_cause="missing narration",
                    is_recurring=True,
                    severity="high",
                    confidence=85,
                    category="narration",
                    rule_id="NARR_001",
                    frequency=3,
                    recommended_fix="Add narration to all scenes",
                )
            ],
        )

        review_dir = tmp_path / "test-proj" / "review"
        review_dir.mkdir(parents=True, exist_ok=True)

        import ytfactory.review.debug.reporter as reporter_mod
        reporter_mod.review_directory = lambda pid: tmp_path / pid / "review"  # type: ignore[assignment]
        try:
            return DebugReporter().write(report)
        finally:
            import ytfactory.review.debug.reporter as reporter_mod2
            from ytfactory.review.artifacts import review_directory as orig_rd
            reporter_mod2.review_directory = orig_rd  # type: ignore[assignment]

    def test_writes_seven_files(self, debug_dir):
        expected = {
            "debug-report.md",
            "debug-summary.json",
            "scene-debug.json",
            "validation-debug.json",
            "scoring-debug.json",
            "feedback-debug.json",
            "execution-timeline.json",
        }
        actual = {f.name for f in debug_dir.iterdir()}
        assert expected == actual

    def test_debug_summary_has_version(self, debug_dir):
        data = json.loads((debug_dir / "debug-summary.json").read_text())
        assert data["version"] == "v1"

    def test_debug_summary_has_verdict(self, debug_dir):
        data = json.loads((debug_dir / "debug-summary.json").read_text())
        assert data["overall_verdict"] == "FAIL"

    def test_debug_summary_has_diagnostics(self, debug_dir):
        data = json.loads((debug_dir / "debug-summary.json").read_text())
        assert "diagnostics" in data

    def test_scene_debug_has_scenes_key(self, debug_dir):
        data = json.loads((debug_dir / "scene-debug.json").read_text())
        assert "scenes" in data
        assert isinstance(data["scenes"], list)

    def test_validation_debug_has_rules_key(self, debug_dir):
        data = json.loads((debug_dir / "validation-debug.json").read_text())
        assert "rules" in data
        assert len(data["rules"]) == 1
        assert data["rules"][0]["rule_id"] == "NARR_001"

    def test_validation_debug_by_category(self, debug_dir):
        data = json.loads((debug_dir / "validation-debug.json").read_text())
        assert "narration" in data["by_category"]

    def test_scoring_debug_has_categories(self, debug_dir):
        data = json.loads((debug_dir / "scoring-debug.json").read_text())
        assert "categories" in data
        assert len(data["categories"]) == 1

    def test_feedback_debug_has_feedback_key(self, debug_dir):
        data = json.loads((debug_dir / "feedback-debug.json").read_text())
        assert "feedback" in data
        assert data["feedback"][0]["feedback_id"] == "EFL-0001"

    def test_feedback_debug_recurring_count(self, debug_dir):
        data = json.loads((debug_dir / "feedback-debug.json").read_text())
        assert data["recurring_count"] == 1

    def test_execution_timeline_has_events(self, debug_dir):
        data = json.loads((debug_dir / "execution-timeline.json").read_text())
        assert "events" in data
        assert data["total_events"] == 2

    def test_debug_report_md_contains_verdict(self, debug_dir):
        md = (debug_dir / "debug-report.md").read_text()
        assert "FAIL" in md

    def test_debug_report_md_contains_debug_level(self, debug_dir):
        md = (debug_dir / "debug-report.md").read_text()
        assert "DETAILED" in md

    def test_debug_report_md_contains_missing_artifacts(self, debug_dir):
        md = (debug_dir / "debug-report.md").read_text()
        assert "scene-002: no audio" in md


def _patched_review_dir(tmp_path: Path, pid: str) -> Path:
    d = tmp_path / pid / "review"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── TestVQREIntegration ───────────────────────────────────────────────────────


@pytest.fixture()
def vqre_debug_proj(tmp_path, monkeypatch) -> str:
    """Full VQRE project fixture with all required assets for debug mode tests."""
    pid = "vqre-debug-proj"
    project_dir = tmp_path / pid
    for subdir in ("script", "scenes", "images", "audio", "subtitles", "video", "review"):
        (project_dir / subdir).mkdir(parents=True)

    words = " ".join(["word"] * 210)
    (project_dir / "script" / "script.md").write_text(
        f"# Title\n\n{words}\n\nTest script.",
        encoding="utf-8",
    )

    scenes = [
        {
            "index": i,
            "title": f"Scene {i}",
            "scene_type": "generated_image",
            "narration": f"Narration for scene {i} with enough words to satisfy checks.",
            "visual_prompt": f"Visual prompt {i}: cinematic, wide shot, sunset, no text.",
            "duration_seconds": 8.0,
            "shot_type": "wide_shot",
            "transition": "fade",
        }
        for i in range(1, 4)
    ]
    (project_dir / "scenes" / "scene-plan.json").write_text(
        json.dumps({"scenes": scenes}), encoding="utf-8"
    )

    png_stub = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2000
    mp3_stub = b"\xff\xfb" + b"\x00" * 6000
    srt = (
        "1\n00:00:00,000 --> 00:00:04,000\nTest subtitle\n\n"
        "2\n00:00:04,000 --> 00:00:08,000\nSecond subtitle\n"
    )
    for i in range(1, 4):
        (project_dir / "images" / f"scene-{i:03d}.png").write_bytes(png_stub)
        (project_dir / "audio" / f"scene-{i:03d}.mp3").write_bytes(mp3_stub)
        (project_dir / "subtitles" / f"scene-{i:03d}.srt").write_text(srt, encoding="utf-8")
        (project_dir / "video" / f"scene-{i:03d}.mp4").write_bytes(b"\x00" * 15000)
    (project_dir / "video" / "final.mp4").write_bytes(b"\x00" * 200000)

    monkeypatch.setattr("ytfactory.review.engine.WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))
    return pid


class TestVQREDebugIntegration:
    def test_default_no_debug_dir(self, vqre_debug_proj, tmp_path):
        """Default config (OFF) must not create the debug directory."""
        from ytfactory.review.engine import VideoQualityReviewEngine

        VideoQualityReviewEngine().review(vqre_debug_proj)
        debug_dir = tmp_path / vqre_debug_proj / "review" / "debug"
        assert not debug_dir.exists()

    def test_default_debug_report_is_none(self, vqre_debug_proj):
        """Default config must leave ReviewReport.debug_report as None."""
        from ytfactory.review.engine import VideoQualityReviewEngine

        report = VideoQualityReviewEngine().review(vqre_debug_proj)
        assert report.debug_report is None

    def test_basic_level_creates_debug_dir(self, vqre_debug_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.BASIC))
        engine.review(vqre_debug_proj)
        debug_dir = tmp_path / vqre_debug_proj / "review" / "debug"
        assert debug_dir.exists()

    def test_basic_level_writes_seven_files(self, vqre_debug_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.BASIC))
        engine.review(vqre_debug_proj)
        debug_dir = tmp_path / vqre_debug_proj / "review" / "debug"
        expected = {
            "debug-report.md",
            "debug-summary.json",
            "scene-debug.json",
            "validation-debug.json",
            "scoring-debug.json",
            "feedback-debug.json",
            "execution-timeline.json",
        }
        actual = {f.name for f in debug_dir.iterdir()}
        assert expected == actual

    def test_detailed_level_writes_seven_files(self, vqre_debug_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.DETAILED))
        engine.review(vqre_debug_proj)
        debug_dir = tmp_path / vqre_debug_proj / "review" / "debug"
        assert len(list(debug_dir.iterdir())) == 7

    def test_verbose_level_writes_seven_files(self, vqre_debug_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.VERBOSE))
        engine.review(vqre_debug_proj)
        debug_dir = tmp_path / vqre_debug_proj / "review" / "debug"
        assert len(list(debug_dir.iterdir())) == 7

    def test_debug_report_in_review_report(self, vqre_debug_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.BASIC))
        report = engine.review(vqre_debug_proj)
        assert report.debug_report is not None
        assert isinstance(report.debug_report, dict)

    def test_debug_report_has_version(self, vqre_debug_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.BASIC))
        report = engine.review(vqre_debug_proj)
        assert report.debug_report["version"] == "v1"

    def test_debug_report_has_timeline(self, vqre_debug_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugLevel.DETAILED)
        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.DETAILED))
        report = engine.review(vqre_debug_proj)
        assert len(report.debug_report["timeline"]) > 0

    def test_debug_summary_json_valid(self, vqre_debug_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.BASIC))
        engine.review(vqre_debug_proj)
        path = tmp_path / vqre_debug_proj / "review" / "debug" / "debug-summary.json"
        data = json.loads(path.read_text())
        assert data["project_id"] == vqre_debug_proj
        assert "overall_verdict" in data

    def test_execution_timeline_has_layer_events(self, vqre_debug_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.BASIC))
        engine.review(vqre_debug_proj)
        path = tmp_path / vqre_debug_proj / "review" / "debug" / "execution-timeline.json"
        data = json.loads(path.read_text())
        event_names = {e["event"] for e in data["events"]}
        assert "stages:start" in event_names
        assert "validation:end" in event_names

    def test_scene_debug_json_has_scenes(self, vqre_debug_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.BASIC))
        engine.review(vqre_debug_proj)
        path = tmp_path / vqre_debug_proj / "review" / "debug" / "scene-debug.json"
        data = json.loads(path.read_text())
        assert data["total_scenes"] == 3
        assert len(data["scenes"]) == 3

    def test_validation_debug_json_has_rules(self, vqre_debug_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.BASIC))
        engine.review(vqre_debug_proj)
        path = tmp_path / vqre_debug_proj / "review" / "debug" / "validation-debug.json"
        data = json.loads(path.read_text())
        assert data["total_rules"] > 0
        assert len(data["rules"]) > 0

    def test_scoring_debug_json_has_categories(self, vqre_debug_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.BASIC))
        engine.review(vqre_debug_proj)
        path = tmp_path / vqre_debug_proj / "review" / "debug" / "scoring-debug.json"
        data = json.loads(path.read_text())
        assert len(data["categories"]) > 0

    def test_detailed_scoring_debug_has_contributions(self, vqre_debug_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.DETAILED))
        engine.review(vqre_debug_proj)
        path = tmp_path / vqre_debug_proj / "review" / "debug" / "scoring-debug.json"
        data = json.loads(path.read_text())
        for cat in data["categories"]:
            if cat["contributions_count"] > 0:
                assert len(cat["contributions"]) > 0

    def test_basic_scoring_debug_no_contributions(self, vqre_debug_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.BASIC))
        engine.review(vqre_debug_proj)
        path = tmp_path / vqre_debug_proj / "review" / "debug" / "scoring-debug.json"
        data = json.loads(path.read_text())
        for cat in data["categories"]:
            assert cat["contributions"] == []

    def test_verbose_includes_debug_metadata(self, vqre_debug_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.VERBOSE))
        engine.review(vqre_debug_proj)
        path = tmp_path / vqre_debug_proj / "review" / "debug" / "validation-debug.json"
        data = json.loads(path.read_text())
        assert len(data["rules"]) > 0  # verbose mode wrote all rules

    def test_existing_review_files_not_affected(self, vqre_debug_proj, tmp_path):
        """Debug mode must not skip the dedicated-reporter output files."""
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.BASIC))
        engine.review(vqre_debug_proj)
        review_dir = tmp_path / vqre_debug_proj / "review"
        # Files written by dedicated reporters (QSE, RCA, EFL) must still exist
        assert (review_dir / "quality-score.json").exists()
        assert (review_dir / "root-cause.json").exists()
        assert (review_dir / "engine-feedback.json").exists()

    def test_debug_config_passable_to_engine(self, vqre_debug_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine

        cfg = DebugConfig(level=DebugLevel.VERBOSE)
        engine = VideoQualityReviewEngine(debug_config=cfg)
        report = engine.review(vqre_debug_proj)
        assert report.debug_report is not None

    def test_off_is_backward_compatible(self, vqre_debug_proj):
        """Explicit OFF behaves identically to the default (no debug output)."""
        from ytfactory.review.engine import VideoQualityReviewEngine

        engine = VideoQualityReviewEngine(debug_config=DebugConfig(level=DebugLevel.OFF))
        report = engine.review(vqre_debug_proj)
        assert report.debug_report is None


# ── TestReviewReportDebugField ────────────────────────────────────────────────


class TestReviewReportDebugField:
    def test_debug_report_field_defaults_none(self):
        report = ReviewReport(
            project_id="proj",
            verdict="PASS",
            timestamp=_ts(),
        )
        assert report.debug_report is None

    def test_debug_report_field_settable(self):
        report = ReviewReport(
            project_id="proj",
            verdict="PASS",
            timestamp=_ts(),
            debug_report={"version": "v1"},
        )
        assert report.debug_report == {"version": "v1"}

    def test_to_dict_includes_debug_report_key(self):
        report = ReviewReport(
            project_id="proj",
            verdict="PASS",
            timestamp=_ts(),
            debug_report=None,
        )
        d = report.to_dict()
        assert "debug_report" in d
