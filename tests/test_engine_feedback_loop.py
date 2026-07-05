"""Tests for the Engine Feedback Loop V1.

Covers:
  - FeedbackItem, EngineFeedbackSummary, RecurringPattern, RoadmapItem,
    EngineFeedbackReport models
  - EFLConfig (normalization, escalation, priority)
  - EngineFeedbackLoopEngine (feedback generation, escalation, roadmap)
  - EFLReporter (5 output files, recurring-patterns accumulation)
  - Integration: VQRE populates efl_report and writes all 5 files
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ytfactory.review.efl.config import (
    EFLConfig,
    escalate_priority,
    normalize_engine,
    severity_to_priority,
)
from ytfactory.review.efl.engine import (
    EngineFeedbackLoopEngine,
    _build_engine_summaries,
    _build_recurring_patterns,
    _build_roadmap,
    _derive_expected_outcome,
    _estimate_effort,
    _priority_rank,
    _worst_severity,
)
from ytfactory.review.efl.models import (
    EngineFeedbackReport,
    EngineFeedbackSummary,
    FeedbackItem,
    RecurringPattern,
    RoadmapItem,
)
from ytfactory.review.efl.reporter import (
    EFLReporter,
    efl_recurring_patterns_path,
    engine_feedback_json_path,
    engine_feedback_md_path,
    engine_priority_report_path,
    improvement_roadmap_md_path,
)
from ytfactory.review.rca.models import RCAIssue, RCAReport, RecurringIssue
from ytfactory.review.scoring.models import CategoryScore, QualityScoreReport
from ytfactory.review.validation.models import ValidationReport, ValidationResult


# ── Shared helpers ────────────────────────────────────────────────────────────


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vr(
    rule_id: str,
    category: str,
    status: str = "FAIL",
    severity: str = "high",
    scene_index: int | None = None,
) -> ValidationResult:
    return ValidationResult(
        rule_id=rule_id,
        category=category,
        status=status,
        severity=severity,
        description="test description",
        evidence="test evidence",
        confidence=0.9,
        responsible_engine="TestEngine",
        timestamp=_ts(),
        scene_index=scene_index,
    )


def _val_report(
    results: list[ValidationResult], project_id: str = "p"
) -> ValidationReport:
    return ValidationReport(
        project_id=project_id,
        timestamp=_ts(),
        total_rules_run=len(results),
        results=results,
    )


def _rca_issue(
    issue_id: str = "RCA-0001",
    rule_id: str = "REND_003",
    category: str = "rendering",
    root_cause_code: str = "missing_asset",
    root_cause_description: str = "Final video missing",
    severity: str = "critical",
    confidence: int = 90,
    primary_engine: str = "Video Renderer",
    suggested_fix: str = "Ensure final.mp4 is produced",
    scene_index: int | None = None,
) -> RCAIssue:
    return RCAIssue(
        issue_id=issue_id,
        rule_id=rule_id,
        category=category,
        root_cause_code=root_cause_code,
        root_cause_description=root_cause_description,
        confidence=confidence,
        severity=severity,
        evidence="test evidence",
        primary_engine=primary_engine,
        secondary_engines=[],
        suggested_fix=suggested_fix,
        suggested_tests=["Assert file exists", "Test error handling"],
        timestamp=_ts(),
        scene_index=scene_index,
    )


def _rca_report(
    issues: list[RCAIssue] | None = None,
    recurring: list[RecurringIssue] | None = None,
    project_id: str = "p",
) -> RCAReport:
    issues = issues or []
    return RCAReport(
        project_id=project_id,
        timestamp=_ts(),
        total_issues=len(issues),
        critical_issues=sum(1 for i in issues if i.severity == "critical"),
        high_issues=sum(1 for i in issues if i.severity == "high"),
        medium_issues=sum(1 for i in issues if i.severity == "medium"),
        low_issues=sum(1 for i in issues if i.severity == "low"),
        issues=issues,
        recurring_issues=recurring or [],
    )


def _score_report(project_id: str = "p") -> QualityScoreReport:
    return QualityScoreReport(
        project_id=project_id,
        timestamp=_ts(),
        overall_score=85.0,
        letter_grade="B",
        verdict="PASS",
    )


def _feedback_item(
    fid: str = "EFL-0001",
    engine: str = "Video Renderer",
    priority: str = "critical",
    is_recurring: bool = False,
    frequency: int = 1,
) -> FeedbackItem:
    return FeedbackItem(
        feedback_id=fid,
        engine_owner=engine,
        source_issue="RCA-0001",
        root_cause="Final video missing",
        severity="critical",
        confidence=90,
        frequency=frequency,
        evidence="evidence",
        recommended_fix="Ensure final.mp4 is produced",
        suggested_tests=["Assert file exists"],
        expected_outcome="final.mp4 will exist after fix",
        priority=priority,
        is_recurring=is_recurring,
        category="rendering",
        rule_id="REND_003",
    )


def _efl_report(project_id: str = "p") -> EngineFeedbackReport:
    item = _feedback_item()
    return EngineFeedbackReport(
        project_id=project_id,
        timestamp=_ts(),
        feedback_items=[item],
        engine_summaries={},
        recurring_patterns=[],
        improvement_roadmap=[],
        priority_distribution={"critical": 1},
        total_feedback=1,
        total_engines_affected=1,
        processing_time_seconds=0.01,
    )


# ── TestEFLConfig ─────────────────────────────────────────────────────────────


class TestEFLConfig:
    def test_defaults(self):
        cfg = EFLConfig()
        assert cfg.enabled is True
        assert cfg.include_warnings is True
        assert cfg.min_confidence_to_report == 0
        assert cfg.category_score_feedback_threshold == 60.0
        assert cfg.recurring_escalation_threshold == 2

    def test_normalize_engine_known(self):
        assert normalize_engine("ScriptWriter") == "Script Generation Engine"
        assert normalize_engine("TTS Engine") == "TTS Engine"
        assert normalize_engine("CaptionGenerator") == "ASS Subtitle Engine"
        assert normalize_engine("VoiceGenerator") == "TTS Engine"
        assert normalize_engine("Video Renderer") == "Video Renderer"
        assert normalize_engine("Scene Planner") == "Scene Planner"
        assert normalize_engine("Motion Engine") == "Motion Engine"

    def test_normalize_engine_unknown_passthrough(self):
        assert normalize_engine("FutureEngine") == "FutureEngine"

    def test_escalate_priority(self):
        assert escalate_priority("low") == "medium"
        assert escalate_priority("medium") == "high"
        assert escalate_priority("high") == "critical"
        assert escalate_priority("critical") == "critical"  # can't escalate beyond critical

    def test_severity_to_priority(self):
        assert severity_to_priority("critical") == "critical"
        assert severity_to_priority("high") == "high"
        assert severity_to_priority("medium") == "medium"
        assert severity_to_priority("low") == "low"

    def test_severity_to_priority_unknown_defaults_medium(self):
        assert severity_to_priority("unknown") == "medium"

    def test_is_rule_enabled_default(self):
        cfg = EFLConfig()
        assert cfg.is_rule_enabled("REND_001") is True

    def test_is_rule_enabled_override(self):
        cfg = EFLConfig(rule_overrides={"REND_001": {"enabled": False}})
        assert cfg.is_rule_enabled("REND_001") is False
        assert cfg.is_rule_enabled("REND_002") is True


# ── TestFeedbackItem ──────────────────────────────────────────────────────────


class TestFeedbackItem:
    def test_to_dict_keys(self):
        item = _feedback_item()
        d = item.to_dict()
        for key in (
            "feedback_id", "engine_owner", "source_issue", "root_cause",
            "severity", "confidence", "frequency", "evidence",
            "recommended_fix", "suggested_tests", "expected_outcome",
            "priority", "is_recurring", "category", "rule_id",
        ):
            assert key in d, f"missing key: {key}"

    def test_to_dict_values(self):
        item = _feedback_item(fid="EFL-0042", engine="TTS Engine", priority="high")
        d = item.to_dict()
        assert d["feedback_id"] == "EFL-0042"
        assert d["engine_owner"] == "TTS Engine"
        assert d["priority"] == "high"


# ── TestEngineFeedbackSummary ─────────────────────────────────────────────────


class TestEngineFeedbackSummary:
    def test_to_dict(self):
        s = EngineFeedbackSummary(
            engine="Video Renderer", total_feedback=3, critical_count=1,
            high_count=1, medium_count=1, low_count=0,
            top_issues=["EFL-0001"], top_recommendations=["Fix A"],
        )
        d = s.to_dict()
        assert d["engine"] == "Video Renderer"
        assert d["total_feedback"] == 3
        assert d["critical_count"] == 1


# ── TestRecurringPattern ──────────────────────────────────────────────────────


class TestRecurringPattern:
    def test_to_dict(self):
        p = RecurringPattern(
            pattern_id="PAT-0001",
            engine="Video Renderer",
            root_cause_code="missing_asset",
            total_occurrence_count=3,
            current_run_count=3,
            affected_projects=["proj-1"],
            affected_scenes=[1, 2, 3],
            severity_distribution={"critical": 3},
            suggested_systemic_fix="Fix rendering",
            priority="critical",
            first_seen=_ts(),
            last_seen=_ts(),
        )
        d = p.to_dict()
        assert d["pattern_id"] == "PAT-0001"
        assert d["total_occurrence_count"] == 3
        assert d["priority"] == "critical"


# ── TestRoadmapItem ───────────────────────────────────────────────────────────


class TestRoadmapItem:
    def test_to_dict(self):
        r = RoadmapItem(
            roadmap_id="RM-0001",
            priority="high",
            engine="TTS Engine",
            action="Fix TTS output validation",
            expected_impact="No missing audio files",
            source_feedback_ids=["EFL-0001"],
            estimated_effort="medium",
        )
        d = r.to_dict()
        assert d["roadmap_id"] == "RM-0001"
        assert d["priority"] == "high"
        assert d["estimated_effort"] == "medium"


# ── TestEngineFeedbackReport ──────────────────────────────────────────────────


class TestEngineFeedbackReport:
    def test_to_dict_version(self):
        report = _efl_report()
        d = report.to_dict()
        assert d["version"] == "v1"

    def test_to_dict_keys(self):
        report = _efl_report()
        d = report.to_dict()
        for key in (
            "version", "project_id", "timestamp", "total_feedback",
            "total_engines_affected", "priority_distribution",
            "processing_time_seconds", "feedback_items", "engine_summaries",
            "recurring_patterns", "improvement_roadmap",
        ):
            assert key in d, f"missing key: {key}"

    def test_to_dict_feedback_items_serialised(self):
        report = _efl_report()
        d = report.to_dict()
        assert len(d["feedback_items"]) == 1
        assert d["feedback_items"][0]["feedback_id"] == "EFL-0001"


# ── TestPriorityAndEscalation ─────────────────────────────────────────────────


class TestPriorityHelpers:
    def test_priority_rank_ordering(self):
        assert _priority_rank("critical") < _priority_rank("high")
        assert _priority_rank("high") < _priority_rank("medium")
        assert _priority_rank("medium") < _priority_rank("low")

    def test_worst_severity(self):
        assert _worst_severity({"critical": 1, "low": 2}) == "critical"
        assert _worst_severity({"high": 2, "medium": 1}) == "high"
        assert _worst_severity({"low": 3}) == "low"
        assert _worst_severity({}) == "low"

    def test_estimate_effort_critical_is_high(self):
        items = [_feedback_item(priority="critical")]
        assert _estimate_effort(items) == "high"

    def test_estimate_effort_recurring_is_medium(self):
        items = [_feedback_item(priority="high", is_recurring=True)]
        assert _estimate_effort(items) == "medium"

    def test_estimate_effort_three_or_more_is_medium(self):
        items = [_feedback_item(priority="medium")] * 3
        assert _estimate_effort(items) == "medium"

    def test_estimate_effort_single_low_is_low(self):
        items = [_feedback_item(priority="low")]
        assert _estimate_effort(items) == "low"

    def test_derive_expected_outcome_from_fix(self):
        outcome = _derive_expected_outcome("Ensure final.mp4 is produced", "missing_asset")
        assert "missing_asset" in outcome or "ensure" in outcome.lower() or "fail" in outcome.lower()

    def test_derive_expected_outcome_empty_fix(self):
        outcome = _derive_expected_outcome("", "wrong_duration")
        assert "wrong_duration" in outcome


# ── TestBuildHelpers ──────────────────────────────────────────────────────────


class TestBuildHelpers:
    def test_build_engine_summaries_groups_by_engine(self):
        items = [
            _feedback_item("EFL-0001", engine="Video Renderer", priority="critical"),
            _feedback_item("EFL-0002", engine="Video Renderer", priority="high"),
            _feedback_item("EFL-0003", engine="TTS Engine", priority="medium"),
        ]
        summaries = _build_engine_summaries(items)
        assert "Video Renderer" in summaries
        assert "TTS Engine" in summaries
        assert summaries["Video Renderer"].total_feedback == 2
        assert summaries["TTS Engine"].total_feedback == 1

    def test_build_engine_summaries_counts_priorities(self):
        items = [
            _feedback_item("EFL-0001", engine="Video Renderer", priority="critical"),
            _feedback_item("EFL-0002", engine="Video Renderer", priority="high"),
            _feedback_item("EFL-0003", engine="Video Renderer", priority="medium"),
            _feedback_item("EFL-0004", engine="Video Renderer", priority="low"),
        ]
        summaries = _build_engine_summaries(items)
        s = summaries["Video Renderer"]
        assert s.critical_count == 1
        assert s.high_count == 1
        assert s.medium_count == 1
        assert s.low_count == 1

    def test_build_engine_summaries_top_issues_max_5(self):
        items = [_feedback_item(f"EFL-{i:04d}", engine="Video Renderer") for i in range(1, 10)]
        summaries = _build_engine_summaries(items)
        assert len(summaries["Video Renderer"].top_issues) <= 5

    def test_build_recurring_patterns_creates_pat_ids(self):
        rec = RecurringIssue(
            engine="Video Renderer",
            root_cause_code="missing_asset",
            occurrence_count=3,
            affected_scenes=[1, 2, 3],
            severity_distribution={"critical": 3},
            suggested_systemic_fix="Fix rendering",
        )
        rca = _rca_report(recurring=[rec])
        patterns = _build_recurring_patterns(rca, "my-proj", _ts())
        assert len(patterns) == 1
        assert patterns[0].pattern_id == "PAT-0001"
        assert patterns[0].engine == "Video Renderer"
        assert "my-proj" in patterns[0].affected_projects

    def test_build_recurring_patterns_escalates_priority(self):
        rec = RecurringIssue(
            engine="TTS Engine",
            root_cause_code="wrong_duration",
            occurrence_count=2,
            affected_scenes=[1, 2],
            severity_distribution={"high": 2},
            suggested_systemic_fix="Fix TTS",
        )
        rca = _rca_report(recurring=[rec])
        patterns = _build_recurring_patterns(rca, "p", _ts())
        assert patterns[0].priority == "critical"  # high → escalated to critical

    def test_build_roadmap_critical_first(self):
        # Give each item a distinct recommended_fix so dedup keeps all three
        items = [
            FeedbackItem(
                feedback_id="EFL-0001", engine_owner="Video Renderer",
                source_issue="RCA-0001", root_cause="rc", severity="low",
                confidence=80, frequency=1, evidence="ev",
                recommended_fix="Fix low-priority issue",
                suggested_tests=[], expected_outcome="ok", priority="low",
                category="rendering", rule_id="REND_005",
            ),
            FeedbackItem(
                feedback_id="EFL-0002", engine_owner="TTS Engine",
                source_issue="RCA-0002", root_cause="rc", severity="critical",
                confidence=95, frequency=1, evidence="ev",
                recommended_fix="Fix critical-priority issue",
                suggested_tests=[], expected_outcome="ok", priority="critical",
                category="audio", rule_id="AUD_001",
            ),
            FeedbackItem(
                feedback_id="EFL-0003", engine_owner="Scene Planner",
                source_issue="RCA-0003", root_cause="rc", severity="medium",
                confidence=70, frequency=1, evidence="ev",
                recommended_fix="Fix medium-priority issue",
                suggested_tests=[], expected_outcome="ok", priority="medium",
                category="motion", rule_id="MOT_001",
            ),
        ]
        summaries = _build_engine_summaries(items)
        roadmap = _build_roadmap(items, summaries)
        priorities = [r.priority for r in roadmap]
        assert priorities.index("critical") < priorities.index("medium")
        assert priorities.index("medium") < priorities.index("low")

    def test_build_roadmap_deduplicates_actions(self):
        # Two items with the same recommended_fix → one roadmap entry
        items = [
            _feedback_item("EFL-0001", priority="high"),
            _feedback_item("EFL-0002", priority="high"),
        ]
        summaries = _build_engine_summaries(items)
        roadmap = _build_roadmap(items, summaries)
        actions = [r.action for r in roadmap]
        assert len(actions) == len(set(actions))

    def test_build_roadmap_empty_input(self):
        roadmap = _build_roadmap([], {})
        assert roadmap == []


# ── TestEngineFeedbackLoopEngine ──────────────────────────────────────────────


class TestEngineFeedbackLoopEngine:
    def _engine(self, **cfg_kwargs) -> EngineFeedbackLoopEngine:
        return EngineFeedbackLoopEngine(EFLConfig(**cfg_kwargs))

    def test_empty_rca_produces_empty_report(self, tmp_path):
        engine = self._engine()
        report = engine.generate(
            tmp_path, [], _val_report([]), _rca_report(), _score_report(), {}
        )
        assert report.total_feedback == 0
        assert report.feedback_items == []

    def test_single_rca_issue_becomes_feedback(self, tmp_path):
        issue = _rca_issue()
        rca = _rca_report(issues=[issue])
        engine = self._engine()
        report = engine.generate(tmp_path, [], _val_report([]), rca, _score_report(), {})
        assert report.total_feedback == 1
        item = report.feedback_items[0]
        assert item.feedback_id == "EFL-0001"
        assert item.engine_owner == "Video Renderer"  # normalized

    def test_engine_name_normalized(self, tmp_path):
        issue = _rca_issue(primary_engine="ScriptWriter")
        rca = _rca_report(issues=[issue])
        report = self._engine().generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        assert report.feedback_items[0].engine_owner == "Script Generation Engine"

    def test_severity_maps_to_priority(self, tmp_path):
        for sev in ("critical", "high", "medium", "low"):
            issue = _rca_issue(severity=sev)
            rca = _rca_report(issues=[issue])
            report = self._engine().generate(
                tmp_path, [], _val_report([]), rca, _score_report(), {}
            )
            assert report.feedback_items[0].priority == sev

    def test_recurring_issue_escalates_priority(self, tmp_path):
        issue = _rca_issue(
            severity="high",
            primary_engine="Video Renderer",
            root_cause_code="missing_asset",
            scene_index=1,
        )
        rec = RecurringIssue(
            engine="Video Renderer",
            root_cause_code="missing_asset",
            occurrence_count=3,
            affected_scenes=[1, 2, 3],
            severity_distribution={"high": 3},
            suggested_systemic_fix="Fix",
        )
        rca = _rca_report(issues=[issue], recurring=[rec])
        report = self._engine().generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        item = report.feedback_items[0]
        assert item.is_recurring is True
        assert item.priority == "critical"  # escalated from high

    def test_sequential_feedback_ids(self, tmp_path):
        issues = [_rca_issue(issue_id=f"RCA-{i:04d}") for i in range(1, 4)]
        rca = _rca_report(issues=issues)
        report = self._engine().generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        ids = [item.feedback_id for item in report.feedback_items]
        assert ids == ["EFL-0001", "EFL-0002", "EFL-0003"]

    def test_confidence_filter(self, tmp_path):
        low_conf = _rca_issue(confidence=10)
        rca = _rca_report(issues=[low_conf])
        report = self._engine(min_confidence_to_report=50).generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        assert report.total_feedback == 0

    def test_rule_disabled_skips_feedback(self, tmp_path):
        issue = _rca_issue(rule_id="REND_003")
        rca = _rca_report(issues=[issue])
        cfg = EFLConfig(rule_overrides={"REND_003": {"enabled": False}})
        report = EngineFeedbackLoopEngine(cfg).generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        assert report.total_feedback == 0

    def test_engine_summaries_populated(self, tmp_path):
        issues = [
            _rca_issue(primary_engine="Video Renderer"),
            _rca_issue(primary_engine="TTS Engine", rule_id="AUD_001", root_cause_code="missing_audio"),
        ]
        rca = _rca_report(issues=issues)
        report = self._engine().generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        assert "Video Renderer" in report.engine_summaries
        assert "TTS Engine" in report.engine_summaries

    def test_priority_distribution_populated(self, tmp_path):
        issues = [
            _rca_issue(severity="critical"),
            _rca_issue(severity="high", rule_id="AUD_001", root_cause_code="x"),
        ]
        rca = _rca_report(issues=issues)
        report = self._engine().generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        assert report.priority_distribution.get("critical", 0) >= 1

    def test_improvement_roadmap_generated(self, tmp_path):
        issue = _rca_issue(severity="critical")
        rca = _rca_report(issues=[issue])
        report = self._engine().generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        assert len(report.improvement_roadmap) >= 1
        rm = report.improvement_roadmap[0]
        assert rm.roadmap_id == "RM-0001"
        assert rm.engine == "Video Renderer"

    def test_processing_time_positive(self, tmp_path):
        report = self._engine().generate(
            tmp_path, [], _val_report([]), _rca_report(), _score_report(), {}
        )
        assert report.processing_time_seconds >= 0.0

    def test_project_id_propagated(self, tmp_path):
        val = _val_report([], project_id="my-video")
        rca = _rca_report(project_id="my-video")
        sr = _score_report(project_id="my-video")
        report = self._engine().generate(tmp_path, [], val, rca, sr, {})
        assert report.project_id == "my-video"

    def test_frequency_counts_same_root_cause(self, tmp_path):
        # Same (engine, root_cause_code) appears on 3 scenes → frequency = 3
        issues = [
            _rca_issue(issue_id=f"RCA-{i:04d}", scene_index=i, root_cause_code="missing_asset")
            for i in range(1, 4)
        ]
        rca = _rca_report(issues=issues)
        report = self._engine().generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        # All items share the same engine+root_cause → frequency = 3
        assert all(item.frequency == 3 for item in report.feedback_items)

    def test_total_engines_affected(self, tmp_path):
        issues = [
            _rca_issue(primary_engine="Video Renderer"),
            _rca_issue(primary_engine="TTS Engine", rule_id="X", root_cause_code="y"),
        ]
        rca = _rca_report(issues=issues)
        report = self._engine().generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        assert report.total_engines_affected == 2

    def test_feedback_has_expected_outcome(self, tmp_path):
        issue = _rca_issue(suggested_fix="Validate output file size before returning")
        rca = _rca_report(issues=[issue])
        report = self._engine().generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        assert report.feedback_items[0].expected_outcome != ""

    def test_feedback_has_suggested_tests(self, tmp_path):
        issue = _rca_issue()
        rca = _rca_report(issues=[issue])
        report = self._engine().generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        assert len(report.feedback_items[0].suggested_tests) > 0

    def test_recurring_patterns_in_report(self, tmp_path):
        rec = RecurringIssue(
            engine="Video Renderer",
            root_cause_code="missing_asset",
            occurrence_count=3,
            affected_scenes=[1, 2, 3],
            severity_distribution={"critical": 3},
            suggested_systemic_fix="Fix",
        )
        rca = _rca_report(recurring=[rec])
        report = self._engine().generate(
            tmp_path, [], _val_report([]), rca, _score_report(), {}
        )
        assert len(report.recurring_patterns) == 1


# ── TestEFLReporter ───────────────────────────────────────────────────────────


@pytest.fixture()
def proj_id(tmp_path, monkeypatch) -> str:
    pid = "efl-test-project"
    project_dir = tmp_path / pid
    (project_dir / "review").mkdir(parents=True)
    monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))
    return pid


def _sample_efl_report(project_id: str) -> EngineFeedbackReport:
    item = _feedback_item()
    pattern = RecurringPattern(
        pattern_id="PAT-0001",
        engine="Video Renderer",
        root_cause_code="missing_asset",
        total_occurrence_count=3,
        current_run_count=3,
        affected_projects=[project_id],
        affected_scenes=[1, 2, 3],
        severity_distribution={"critical": 3},
        suggested_systemic_fix="Fix rendering pipeline",
        priority="critical",
        first_seen=_ts(),
        last_seen=_ts(),
    )
    roadmap = RoadmapItem(
        roadmap_id="RM-0001",
        priority="critical",
        engine="Video Renderer",
        action="Ensure final.mp4 is produced",
        expected_impact="Final video always exists",
        source_feedback_ids=["EFL-0001"],
        estimated_effort="high",
    )
    summary = EngineFeedbackSummary(
        engine="Video Renderer",
        total_feedback=1,
        critical_count=1,
        high_count=0,
        medium_count=0,
        low_count=0,
        top_issues=["EFL-0001"],
        top_recommendations=["Ensure final.mp4 is produced"],
    )
    return EngineFeedbackReport(
        project_id=project_id,
        timestamp=_ts(),
        feedback_items=[item],
        engine_summaries={"Video Renderer": summary},
        recurring_patterns=[pattern],
        improvement_roadmap=[roadmap],
        priority_distribution={"critical": 1},
        total_feedback=1,
        total_engines_affected=1,
        processing_time_seconds=0.01,
    )


class TestEFLReporter:
    def test_writes_five_files(self, proj_id):
        report = _sample_efl_report(proj_id)
        EFLReporter().write(report)
        assert engine_feedback_json_path(proj_id).exists()
        assert engine_feedback_md_path(proj_id).exists()
        assert engine_priority_report_path(proj_id).exists()
        assert efl_recurring_patterns_path(proj_id).exists()
        assert improvement_roadmap_md_path(proj_id).exists()

    def test_engine_feedback_json_valid(self, proj_id):
        report = _sample_efl_report(proj_id)
        EFLReporter().write(report)
        data = json.loads(engine_feedback_json_path(proj_id).read_text())
        assert data["version"] == "v1"
        assert data["total_feedback"] == 1
        assert len(data["feedback_items"]) == 1
        assert data["feedback_items"][0]["feedback_id"] == "EFL-0001"

    def test_engine_feedback_json_not_stub(self, proj_id):
        report = _sample_efl_report(proj_id)
        EFLReporter().write(report)
        data = json.loads(engine_feedback_json_path(proj_id).read_text())
        assert data.get("status") != "not_implemented"

    def test_engine_feedback_md_contains_engine(self, proj_id):
        report = _sample_efl_report(proj_id)
        EFLReporter().write(report)
        content = engine_feedback_md_path(proj_id).read_text()
        assert "Video Renderer" in content
        assert "EFL-0001" in content

    def test_engine_feedback_md_no_feedback_shows_pass(self, proj_id, tmp_path):
        report = EngineFeedbackReport(
            project_id=proj_id,
            timestamp=_ts(),
            total_feedback=0,
        )
        EFLReporter().write(report)
        content = engine_feedback_md_path(proj_id).read_text()
        assert "No feedback" in content or "passed" in content.lower()

    def test_priority_report_has_structure(self, proj_id):
        report = _sample_efl_report(proj_id)
        EFLReporter().write(report)
        data = json.loads(engine_priority_report_path(proj_id).read_text())
        assert data["version"] == "v1"
        assert "by_priority" in data
        assert "priority_distribution" in data
        assert "engine_summary" in data

    def test_priority_report_items_in_correct_bucket(self, proj_id):
        report = _sample_efl_report(proj_id)
        EFLReporter().write(report)
        data = json.loads(engine_priority_report_path(proj_id).read_text())
        assert len(data["by_priority"]["critical"]) == 1
        assert data["by_priority"]["critical"][0]["feedback_id"] == "EFL-0001"

    def test_recurring_patterns_first_run(self, proj_id):
        report = _sample_efl_report(proj_id)
        EFLReporter().write(report)
        data = json.loads(efl_recurring_patterns_path(proj_id).read_text())
        assert data["total_patterns"] == 1
        assert data["patterns"][0]["engine"] == "Video Renderer"

    def test_recurring_patterns_accumulates_across_runs(self, proj_id):
        reporter = EFLReporter()
        r1 = _sample_efl_report(proj_id)
        reporter.write(r1)
        r2 = _sample_efl_report(proj_id)
        r2.timestamp = _ts()
        reporter.write(r2)
        data = json.loads(efl_recurring_patterns_path(proj_id).read_text())
        # The same pattern should be merged (not duplicated), total stays at 1
        assert data["total_patterns"] == 1
        merged = data["patterns"][0]
        assert merged["total_occurrence_count"] == 6  # 3 + 3

    def test_recurring_patterns_corrupt_file_resets(self, proj_id):
        efl_recurring_patterns_path(proj_id).write_text("not json", encoding="utf-8")
        report = _sample_efl_report(proj_id)
        EFLReporter().write(report)
        data = json.loads(efl_recurring_patterns_path(proj_id).read_text())
        assert data["total_patterns"] == 1

    def test_improvement_roadmap_md_contains_action(self, proj_id):
        report = _sample_efl_report(proj_id)
        EFLReporter().write(report)
        content = improvement_roadmap_md_path(proj_id).read_text()
        assert "Ensure final.mp4 is produced" in content
        assert "RM-0001" in content
        assert "CRITICAL" in content.upper() or "Critical" in content

    def test_improvement_roadmap_md_no_items_shows_pass(self, proj_id, tmp_path):
        report = EngineFeedbackReport(
            project_id=proj_id, timestamp=_ts(), total_feedback=0
        )
        EFLReporter().write(report)
        content = improvement_roadmap_md_path(proj_id).read_text()
        assert "No improvements" in content or "passed" in content.lower()

    def test_returns_review_directory(self, proj_id):
        report = _sample_efl_report(proj_id)
        review_dir = EFLReporter().write(report)
        assert review_dir.is_dir()


# ── TestVQREIntegration ───────────────────────────────────────────────────────


@pytest.fixture()
def vqre_proj(tmp_path, monkeypatch):
    """Full VQRE project fixture with all required assets."""
    pid = "vqre-efl-proj"
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
            "index": i, "title": f"Scene {i}", "scene_type": "generated_image",
            "narration": f"Narration for scene {i} with enough words to satisfy checks.",
            "visual_prompt": f"Visual prompt {i}: cinematic, wide shot, sunset, no text.",
            "duration_seconds": 8.0, "shot_type": "wide_shot", "transition": "fade",
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


class TestVQREIntegration:
    def test_efl_report_in_review_report(self, vqre_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine
        report = VideoQualityReviewEngine().review(vqre_proj)
        assert report.efl_report is not None
        assert report.efl_report["version"] == "v1"

    def test_five_efl_files_written(self, vqre_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine
        VideoQualityReviewEngine().review(vqre_proj)
        review_dir = tmp_path / vqre_proj / "review"
        assert (review_dir / "engine-feedback.json").exists()
        assert (review_dir / "engine-feedback.md").exists()
        assert (review_dir / "engine-priority-report.json").exists()
        assert (review_dir / "recurring-patterns.json").exists()
        assert (review_dir / "improvement-roadmap.md").exists()

    def test_engine_feedback_json_not_stub(self, vqre_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine
        VideoQualityReviewEngine().review(vqre_proj)
        data = json.loads(
            (tmp_path / vqre_proj / "review" / "engine-feedback.json").read_text()
        )
        assert data.get("status") != "not_implemented"
        assert "version" in data
        assert data["version"] == "v1"

    def test_engine_feedback_json_has_feedback_items_list(self, vqre_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine
        VideoQualityReviewEngine().review(vqre_proj)
        data = json.loads(
            (tmp_path / vqre_proj / "review" / "engine-feedback.json").read_text()
        )
        assert "feedback_items" in data
        assert isinstance(data["feedback_items"], list)

    def test_efl_config_passable(self, vqre_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine
        from ytfactory.review.efl.config import EFLConfig
        engine = VideoQualityReviewEngine(
            efl_config=EFLConfig(min_confidence_to_report=50)
        )
        report = engine.review(vqre_proj)
        assert report.efl_report is not None

    def test_recurring_patterns_written_on_each_run(self, vqre_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine
        engine = VideoQualityReviewEngine()
        engine.review(vqre_proj)
        engine.review(vqre_proj)
        data = json.loads(
            (tmp_path / vqre_proj / "review" / "recurring-patterns.json").read_text()
        )
        assert "patterns" in data
        assert isinstance(data["patterns"], list)

    def test_review_report_has_efl_report_field(self, vqre_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine
        from ytfactory.review.models import ReviewReport
        report = VideoQualityReviewEngine().review(vqre_proj)
        assert hasattr(report, "efl_report")

    def test_improvement_roadmap_md_exists(self, vqre_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine
        VideoQualityReviewEngine().review(vqre_proj)
        roadmap = (tmp_path / vqre_proj / "review" / "improvement-roadmap.md").read_text()
        assert "# Improvement Roadmap" in roadmap


# ── TestBackwardCompatibility ─────────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_efl_importable(self):
        from ytfactory.review.efl import __init__  # noqa: F401

    def test_efl_engine_importable(self):
        from ytfactory.review.efl.engine import EngineFeedbackLoopEngine
        assert EngineFeedbackLoopEngine is not None

    def test_efl_models_importable(self):
        from ytfactory.review.efl.models import EngineFeedbackReport, FeedbackItem
        assert FeedbackItem is not None
        assert EngineFeedbackReport is not None

    def test_efl_config_importable(self):
        from ytfactory.review.efl.config import EFLConfig, ENGINE_TARGETS
        assert len(ENGINE_TARGETS) == 12

    def test_efl_reporter_importable(self):
        from ytfactory.review.efl.reporter import EFLReporter
        assert EFLReporter is not None

    def test_review_report_has_efl_field(self):
        from ytfactory.review.models import ReviewReport
        r = ReviewReport(project_id="p", verdict="PASS", timestamp="t")
        assert hasattr(r, "efl_report")
        assert r.efl_report is None

    def test_vqre_accepts_efl_config(self):
        from ytfactory.review.engine import VideoQualityReviewEngine
        from ytfactory.review.efl.config import EFLConfig
        engine = VideoQualityReviewEngine(efl_config=EFLConfig())
        assert engine is not None

    def test_existing_review_module_unchanged(self):
        from ytfactory.review.reporter import ReviewReporter
        from ytfactory.review.models import ReviewReport, StageResult, SceneReview
        assert ReviewReporter is not None
        assert ReviewReport is not None
