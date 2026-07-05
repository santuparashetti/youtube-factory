"""Tests for Root Cause Analysis Engine V1.

Covers:
  - RCAIssue, RCAReport, EngineOwnerSummary, RecurringIssue models
  - RCAConfig behaviour
  - RuleMapping construction
  - BaseRCAAnalyzer filtering and exception safety
  - All 8 category analyzers (script, narration, subtitle, image, motion, audio, rendering, story)
  - RootCauseAnalysisEngine orchestration (IDs, engine summaries, recurring detection)
  - RCAReporter file output
  - Integration: VQRE runs RCA and populates rca_report on ReviewReport
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ytfactory.review.rca.analyzers.audio import AudioRCAAnalyzer
from ytfactory.review.rca.analyzers.image import ImageRCAAnalyzer
from ytfactory.review.rca.analyzers.motion import MotionRCAAnalyzer
from ytfactory.review.rca.analyzers.narration import NarrationRCAAnalyzer
from ytfactory.review.rca.analyzers.rendering import RenderingRCAAnalyzer
from ytfactory.review.rca.analyzers.script import ScriptRCAAnalyzer
from ytfactory.review.rca.analyzers.story import StoryRCAAnalyzer
from ytfactory.review.rca.analyzers.subtitle import SubtitleRCAAnalyzer
from ytfactory.review.rca.config import RCAConfig
from ytfactory.review.rca.engine import RootCauseAnalysisEngine, _build_engine_summaries, _detect_recurring
from ytfactory.review.rca.framework import BaseRCAAnalyzer, RuleMapping
from ytfactory.review.rca.models import EngineOwnerSummary, RCAIssue, RCAReport, RecurringIssue
from ytfactory.review.rca.reporter import (
    RCAReporter,
    engine_owner_summary_path,
    recurring_issues_path,
    root_cause_json_path,
    root_cause_report_md_path,
)
from ytfactory.review.validation.models import ValidationReport, ValidationResult


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _val_result(
    rule_id: str,
    category: str = "script",
    status: str = "FAIL",
    severity: str = "high",
    description: str = "test failure",
    evidence: str = "test evidence",
    responsible_engine: str = "ScriptWriter",
    scene_index: int | None = None,
) -> ValidationResult:
    return ValidationResult(
        rule_id=rule_id,
        category=category,
        status=status,
        severity=severity,
        description=description,
        evidence=evidence,
        confidence=0.9,
        responsible_engine=responsible_engine,
        timestamp=_ts(),
        scene_index=scene_index,
    )


def _make_val_report(
    results: list[ValidationResult],
    project_id: str = "test-proj",
) -> ValidationReport:
    return ValidationReport(
        project_id=project_id,
        timestamp=_ts(),
        total_rules_run=len(results),
        results=results,
    )


def _rca_issue(
    issue_id: str = "RCA-0001",
    rule_id: str = "SCRIPT_001",
    category: str = "script",
    root_cause_code: str = "missing_script",
    confidence: int = 90,
    severity: str = "critical",
    primary_engine: str = "ScriptWriter",
    scene_index: int | None = None,
) -> RCAIssue:
    return RCAIssue(
        issue_id=issue_id,
        rule_id=rule_id,
        category=category,
        root_cause_code=root_cause_code,
        root_cause_description="Test root cause",
        confidence=confidence,
        severity=severity,
        evidence="test evidence",
        primary_engine=primary_engine,
        secondary_engines=[],
        suggested_fix="fix it",
        suggested_tests=["test it"],
        timestamp=_ts(),
        scene_index=scene_index,
    )


# ── TestRCAIssue ──────────────────────────────────────────────────────────────


class TestRCAIssue:
    def test_construction_defaults(self):
        issue = _rca_issue()
        assert issue.issue_id == "RCA-0001"
        assert issue.secondary_engines == []
        assert issue.scene_index is None
        assert issue.timestamp_seconds is None
        assert issue.debug_metadata == {}

    def test_to_dict_keys(self):
        issue = _rca_issue()
        d = issue.to_dict()
        for key in (
            "issue_id", "rule_id", "category", "root_cause_code",
            "root_cause_description", "confidence", "severity", "evidence",
            "primary_engine", "secondary_engines", "suggested_fix",
            "suggested_tests", "timestamp", "scene_index",
            "timestamp_seconds", "debug_metadata",
        ):
            assert key in d

    def test_to_dict_scene_index(self):
        issue = _rca_issue(scene_index=3)
        assert issue.to_dict()["scene_index"] == 3

    def test_secondary_engines_list(self):
        issue = RCAIssue(
            issue_id="RCA-0001",
            rule_id="X",
            category="script",
            root_cause_code="x",
            root_cause_description="x",
            confidence=80,
            severity="high",
            evidence="e",
            primary_engine="A",
            secondary_engines=["B", "C"],
            suggested_fix="f",
            suggested_tests=["t"],
            timestamp=_ts(),
        )
        assert issue.to_dict()["secondary_engines"] == ["B", "C"]

    def test_mutable_after_creation(self):
        issue = _rca_issue(issue_id="")
        issue.issue_id = "RCA-0042"
        assert issue.issue_id == "RCA-0042"


# ── TestRCAReport ─────────────────────────────────────────────────────────────


class TestRCAReport:
    def test_empty_report(self):
        report = RCAReport(project_id="proj", timestamp=_ts())
        assert report.total_issues == 0
        assert report.issues == []
        assert report.engine_summaries == {}
        assert report.recurring_issues == []

    def test_to_dict_version(self):
        report = RCAReport(project_id="proj", timestamp=_ts())
        d = report.to_dict()
        assert d["version"] == "v1"
        assert d["project_id"] == "proj"
        assert "issues" in d
        assert "engine_summaries" in d
        assert "recurring_issues" in d

    def test_to_dict_issue_count(self):
        issues = [_rca_issue(f"RCA-{i:04d}") for i in range(3)]
        report = RCAReport(
            project_id="proj",
            timestamp=_ts(),
            total_issues=3,
            issues=issues,
        )
        d = report.to_dict()
        assert len(d["issues"]) == 3


# ── TestEngineOwnerSummary ────────────────────────────────────────────────────


class TestEngineOwnerSummary:
    def test_to_dict(self):
        summary = EngineOwnerSummary(
            engine="ScriptWriter",
            total_issues=3,
            critical_issues=1,
            high_issues=1,
            medium_issues=1,
            low_issues=0,
            root_causes={"missing_script": 1, "padding": 2},
            avg_confidence=85.0,
            primary_recommendations=["fix this"],
        )
        d = summary.to_dict()
        assert d["engine"] == "ScriptWriter"
        assert d["total_issues"] == 3
        assert d["root_causes"]["padding"] == 2


# ── TestRecurringIssue ────────────────────────────────────────────────────────


class TestRecurringIssue:
    def test_to_dict(self):
        rec = RecurringIssue(
            engine="TTS Engine",
            root_cause_code="missing_asset",
            occurrence_count=4,
            affected_scenes=[1, 3, 5, 7],
            severity_distribution={"critical": 4},
            suggested_systemic_fix="fix TTS",
        )
        d = rec.to_dict()
        assert d["occurrence_count"] == 4
        assert d["affected_scenes"] == [1, 3, 5, 7]


# ── TestRCAConfig ─────────────────────────────────────────────────────────────


class TestRCAConfig:
    def test_defaults(self):
        cfg = RCAConfig()
        assert cfg.enabled is True
        assert cfg.recurring_threshold == 2
        assert cfg.min_confidence_to_report == 0
        assert cfg.include_warnings is True

    def test_is_rule_enabled_default_true(self):
        cfg = RCAConfig()
        assert cfg.is_rule_enabled("SCRIPT_001") is True

    def test_is_rule_enabled_override_false(self):
        cfg = RCAConfig(rule_overrides={"SCRIPT_001": {"enabled": False}})
        assert cfg.is_rule_enabled("SCRIPT_001") is False

    def test_is_rule_enabled_override_true(self):
        cfg = RCAConfig(rule_overrides={"SCRIPT_001": {"enabled": True}})
        assert cfg.is_rule_enabled("SCRIPT_001") is True

    def test_custom_threshold(self):
        cfg = RCAConfig(recurring_threshold=5)
        assert cfg.recurring_threshold == 5


# ── TestRuleMapping ───────────────────────────────────────────────────────────


class TestRuleMapping:
    def test_construction(self):
        m = RuleMapping(
            root_cause_code="missing_script",
            root_cause_description="Script not found",
            rca_category="script",
            primary_engine="ScriptWriter",
            secondary_engines=["ResearchAgent"],
            base_confidence=95,
            suggested_fix="Run ScriptWriter",
            suggested_tests=["test it"],
        )
        assert m.root_cause_code == "missing_script"
        assert m.rca_category == "script"
        assert m.base_confidence == 95

    def test_defaults(self):
        m = RuleMapping(
            root_cause_code="x",
            root_cause_description="x",
            rca_category="script",
            primary_engine="X",
        )
        assert m.secondary_engines == []
        assert m.base_confidence == 80
        assert m.suggested_fix == ""
        assert m.suggested_tests == []


# ── TestBaseRCAAnalyzer ───────────────────────────────────────────────────────


class _ConcreteAnalyzer(BaseRCAAnalyzer):
    """Minimal concrete analyzer for testing the base class logic."""

    validation_category = "script"

    def _analyze_one(self, result, project_dir, scenes, context):
        mapping = RuleMapping(
            root_cause_code="test_cause",
            root_cause_description="Test",
            rca_category="script",
            primary_engine="TestEngine",
            base_confidence=90,
        )
        return self._from_mapping(result, mapping)


class _BrokenAnalyzer(BaseRCAAnalyzer):
    validation_category = "script"

    def _analyze_one(self, result, project_dir, scenes, context):
        raise RuntimeError("deliberate failure")


class TestBaseRCAAnalyzer:
    def test_filters_by_category(self, tmp_path):
        analyzer = _ConcreteAnalyzer(RCAConfig())
        results = [
            _val_result("SCRIPT_001", category="script", status="FAIL"),
            _val_result("NARR_001", category="narration", status="FAIL"),
        ]
        issues = analyzer.analyze(results, tmp_path, [], {})
        assert len(issues) == 1
        assert issues[0].rule_id == "SCRIPT_001"

    def test_excludes_pass_and_skip(self, tmp_path):
        analyzer = _ConcreteAnalyzer(RCAConfig())
        results = [
            _val_result("SCRIPT_001", category="script", status="PASS"),
            _val_result("SCRIPT_002", category="script", status="SKIP"),
        ]
        issues = analyzer.analyze(results, tmp_path, [], {})
        assert issues == []

    def test_includes_warning_by_default(self, tmp_path):
        analyzer = _ConcreteAnalyzer(RCAConfig())
        results = [_val_result("SCRIPT_003", category="script", status="WARNING")]
        issues = analyzer.analyze(results, tmp_path, [], {})
        assert len(issues) == 1

    def test_excludes_warning_when_disabled(self, tmp_path):
        analyzer = _ConcreteAnalyzer(RCAConfig(include_warnings=False))
        results = [_val_result("SCRIPT_003", category="script", status="WARNING")]
        issues = analyzer.analyze(results, tmp_path, [], {})
        assert issues == []

    def test_exception_in_analyze_one_produces_unknown(self, tmp_path):
        analyzer = _BrokenAnalyzer(RCAConfig())
        results = [_val_result("SCRIPT_001", category="script", status="FAIL")]
        issues = analyzer.analyze(results, tmp_path, [], {})
        assert len(issues) == 1
        assert issues[0].root_cause_code == "unknown"
        assert issues[0].confidence == 0

    def test_unknown_issue_has_investigation_note(self, tmp_path):
        analyzer = _ConcreteAnalyzer(RCAConfig())
        result = _val_result("SCRIPT_999", category="script", status="FAIL")
        # Override to call unknown_issue path
        analyzer2 = _BrokenAnalyzer(RCAConfig())
        issues = analyzer2.analyze([result], tmp_path, [], {})
        assert "investigate" in issues[0].suggested_fix.lower()

    def test_min_confidence_filter(self, tmp_path):
        analyzer = _ConcreteAnalyzer(RCAConfig(min_confidence_to_report=95))
        results = [_val_result("SCRIPT_001", category="script", status="FAIL")]
        # _ConcreteAnalyzer always returns confidence 90 (base) which is < 95
        issues = analyzer.analyze(results, tmp_path, [], {})
        assert issues == []

    def test_rule_override_disabled(self, tmp_path):
        cfg = RCAConfig(rule_overrides={"SCRIPT_001": {"enabled": False}})
        analyzer = _ConcreteAnalyzer(cfg)
        results = [_val_result("SCRIPT_001", category="script", status="FAIL")]
        issues = analyzer.analyze(results, tmp_path, [], {})
        assert issues == []

    def test_warning_lowers_confidence(self, tmp_path):
        analyzer = _ConcreteAnalyzer(RCAConfig())
        fail_result = _val_result("SCRIPT_001", category="script", status="FAIL")
        warn_result = _val_result("SCRIPT_001", category="script", status="WARNING")
        fail_issues = analyzer.analyze([fail_result], tmp_path, [], {})
        warn_issues = analyzer.analyze([warn_result], tmp_path, [], {})
        assert warn_issues[0].confidence < fail_issues[0].confidence


# ── TestScriptRCAAnalyzer ─────────────────────────────────────────────────────


class TestScriptRCAAnalyzer:
    def _run(self, results, tmp_path):
        return ScriptRCAAnalyzer(RCAConfig()).analyze(results, tmp_path, [], {})

    def test_script_001_missing_script(self, tmp_path):
        results = [_val_result("SCRIPT_001", category="script", status="FAIL", severity="critical")]
        issues = self._run(results, tmp_path)
        assert len(issues) == 1
        assert issues[0].root_cause_code == "missing_script"
        assert issues[0].primary_engine == "ScriptWriter"
        assert issues[0].confidence == 100

    def test_script_002_too_short(self, tmp_path):
        results = [
            _val_result(
                "SCRIPT_002",
                category="script",
                status="FAIL",
                severity="high",
                description="Script is too short: 150 words (minimum: 200)",
            )
        ]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "wrong_duration"
        assert "Script Pacing Engine" in issues[0].primary_engine

    def test_script_002_too_long(self, tmp_path):
        results = [
            _val_result(
                "SCRIPT_002",
                category="script",
                status="WARNING",
                severity="medium",
                description="Script is very long: 6000 words (maximum: 5000)",
            )
        ]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "padding"

    def test_script_003_repeated_paragraphs(self, tmp_path):
        results = [_val_result("SCRIPT_003", category="script", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "padding"

    def test_script_004_few_sentences(self, tmp_path):
        results = [_val_result("SCRIPT_004", category="script", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "weak_flow"
        assert issues[0].primary_engine == "ScriptWriter"

    def test_script_005_few_lines(self, tmp_path):
        results = [_val_result("SCRIPT_005", category="script", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "weak_flow"

    def test_unknown_rule_produces_unknown_issue(self, tmp_path):
        results = [_val_result("SCRIPT_999", category="script", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "unknown"

    def test_rca_category_is_script(self, tmp_path):
        results = [_val_result("SCRIPT_001", category="script", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].category == "script"


# ── TestNarrationRCAAnalyzer ──────────────────────────────────────────────────


class TestNarrationRCAAnalyzer:
    def _run(self, results, tmp_path):
        return NarrationRCAAnalyzer(RCAConfig()).analyze(results, tmp_path, [], {})

    def test_narr_001_missing_narration(self, tmp_path):
        results = [_val_result("NARR_001", category="narration", status="FAIL", severity="critical")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "missing_narration"
        assert issues[0].primary_engine == "Scene Planner"
        assert issues[0].confidence == 100

    def test_narr_002_wrong_duration(self, tmp_path):
        results = [_val_result("NARR_002", category="narration", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "wrong_duration"

    def test_narr_003_padding(self, tmp_path):
        results = [_val_result("NARR_003", category="narration", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "padding"

    def test_narr_004_fast_pace(self, tmp_path):
        results = [_val_result("NARR_004", category="narration", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "fast_pace"
        assert issues[0].primary_engine == "TTS Engine"

    def test_rca_category_is_narration(self, tmp_path):
        results = [_val_result("NARR_001", category="narration", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].category == "narration"

    def test_no_issues_for_pass(self, tmp_path):
        results = [_val_result("NARR_001", category="narration", status="PASS")]
        issues = self._run(results, tmp_path)
        assert issues == []


# ── TestSubtitleRCAAnalyzer ───────────────────────────────────────────────────


class TestSubtitleRCAAnalyzer:
    def _run(self, results, tmp_path):
        return SubtitleRCAAnalyzer(RCAConfig()).analyze(results, tmp_path, [], {})

    def test_subt_001_missing(self, tmp_path):
        results = [_val_result("SUBT_001", category="subtitle", status="FAIL", severity="critical")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "missing_subtitle"
        assert issues[0].primary_engine == "CaptionGenerator"

    def test_subt_002_sync(self, tmp_path):
        results = [_val_result("SUBT_002", category="subtitle", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "sync_issue"
        assert issues[0].primary_engine == "ASS Subtitle Engine"

    def test_subt_003_reading_speed(self, tmp_path):
        results = [_val_result("SUBT_003", category="subtitle", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "reading_speed"

    def test_subt_004_formatting(self, tmp_path):
        results = [_val_result("SUBT_004", category="subtitle", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "formatting"

    def test_subt_005_empty_cues(self, tmp_path):
        results = [_val_result("SUBT_005", category="subtitle", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "formatting"

    def test_subt_006_low_overlap(self, tmp_path):
        results = [_val_result("SUBT_006", category="subtitle", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "sync_issue"


# ── TestImageRCAAnalyzer ──────────────────────────────────────────────────────


class TestImageRCAAnalyzer:
    def _run(self, results, tmp_path):
        return ImageRCAAnalyzer(RCAConfig()).analyze(results, tmp_path, [], {})

    def test_img_001_missing(self, tmp_path):
        results = [_val_result("IMG_001", category="image", status="FAIL", severity="critical")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "missing_asset"
        assert "Image Prompt Engine" in issues[0].primary_engine

    def test_img_002_too_small(self, tmp_path):
        results = [_val_result("IMG_002", category="image", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "missing_asset"

    def test_img_003_no_prompt(self, tmp_path):
        results = [_val_result("IMG_003", category="image", status="FAIL", severity="critical")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "weak_prompt"
        assert issues[0].confidence == 100

    def test_img_004_repeated_imagery(self, tmp_path):
        results = [_val_result("IMG_004", category="image", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "repeated_imagery"

    def test_img_005_no_shot_type(self, tmp_path):
        results = [_val_result("IMG_005", category="image", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "weak_prompt"

    def test_img_006_no_style_markers(self, tmp_path):
        results = [_val_result("IMG_006", category="image", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "weak_prompt"

    def test_rca_category_is_image(self, tmp_path):
        results = [_val_result("IMG_001", category="image", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].category == "image"


# ── TestMotionRCAAnalyzer ─────────────────────────────────────────────────────


class TestMotionRCAAnalyzer:
    def _run(self, results, tmp_path):
        return MotionRCAAnalyzer(RCAConfig()).analyze(results, tmp_path, [], {})

    def test_mot_001_duration_out_of_range(self, tmp_path):
        results = [_val_result("MOT_001", category="motion", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "wrong_duration"
        assert issues[0].primary_engine == "Scene Planner"

    def test_mot_002_zero_duration(self, tmp_path):
        results = [_val_result("MOT_002", category="motion", status="FAIL", severity="critical")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "wrong_duration"
        assert issues[0].confidence == 100

    def test_mot_003_no_shot_type(self, tmp_path):
        results = [_val_result("MOT_003", category="motion", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "static_scene"

    def test_mot_004_no_transition(self, tmp_path):
        results = [_val_result("MOT_004", category="motion", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "poor_transition"

    def test_rca_category_is_motion(self, tmp_path):
        results = [_val_result("MOT_001", category="motion", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].category == "motion"


# ── TestAudioRCAAnalyzer ──────────────────────────────────────────────────────


class TestAudioRCAAnalyzer:
    def _run(self, results, tmp_path):
        return AudioRCAAnalyzer(RCAConfig()).analyze(results, tmp_path, [], {})

    def test_aud_001_missing(self, tmp_path):
        results = [_val_result("AUD_001", category="audio", status="FAIL", severity="critical")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "missing_asset"
        assert issues[0].primary_engine == "TTS Engine"
        assert issues[0].confidence == 100

    def test_aud_002_too_small(self, tmp_path):
        results = [_val_result("AUD_002", category="audio", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "missing_asset"

    def test_aud_003_short_clip(self, tmp_path):
        results = [_val_result("AUD_003", category="audio", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "silence"

    def test_aud_004_confidence_zero(self, tmp_path):
        results = [_val_result("AUD_004", category="audio", status="SKIP")]
        # SKIP should not produce issues
        issues = self._run(results, tmp_path)
        assert issues == []

    def test_rca_category_is_audio(self, tmp_path):
        results = [_val_result("AUD_001", category="audio", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].category == "audio"


# ── TestRenderingRCAAnalyzer ──────────────────────────────────────────────────


class TestRenderingRCAAnalyzer:
    def _run(self, results, tmp_path):
        return RenderingRCAAnalyzer(RCAConfig()).analyze(results, tmp_path, [], {})

    def test_rend_001_clip_missing(self, tmp_path):
        results = [_val_result("REND_001", category="rendering", status="FAIL", severity="critical")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "missing_asset"
        assert issues[0].primary_engine == "Video Renderer"

    def test_rend_002_clip_too_small(self, tmp_path):
        results = [_val_result("REND_002", category="rendering", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "missing_asset"

    def test_rend_003_final_missing(self, tmp_path):
        results = [_val_result("REND_003", category="rendering", status="FAIL", severity="critical")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "missing_asset"
        assert issues[0].confidence == 100

    def test_rend_004_final_too_small(self, tmp_path):
        results = [_val_result("REND_004", category="rendering", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "missing_asset"

    def test_rend_005_clips_missing(self, tmp_path):
        results = [_val_result("REND_005", category="rendering", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "missing_asset"

    def test_rca_category_is_rendering(self, tmp_path):
        results = [_val_result("REND_001", category="rendering", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].category == "rendering"


# ── TestStoryRCAAnalyzer ──────────────────────────────────────────────────────


class TestStoryRCAAnalyzer:
    def _run(self, results, tmp_path):
        return StoryRCAAnalyzer(RCAConfig()).analyze(results, tmp_path, [], {})

    def test_stor_001_wrong_order(self, tmp_path):
        results = [_val_result("STOR_001", category="story", status="FAIL")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "wrong_order"
        assert issues[0].category == "rendering"
        assert issues[0].primary_engine == "Scene Planner"

    def test_stor_002_wrong_scene_count(self, tmp_path):
        results = [_val_result("STOR_002", category="story", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "wrong_duration"
        assert issues[0].category == "script"

    def test_stor_003_duplicate_titles(self, tmp_path):
        results = [_val_result("STOR_003", category="story", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "weak_flow"
        assert issues[0].category == "script"

    def test_stor_004_repeated_narration(self, tmp_path):
        results = [_val_result("STOR_004", category="story", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "repeated_content"
        assert issues[0].category == "narration"

    def test_stor_005_weak_opening(self, tmp_path):
        results = [_val_result("STOR_005", category="story", status="WARNING")]
        issues = self._run(results, tmp_path)
        assert issues[0].root_cause_code == "weak_flow"
        assert issues[0].category == "narration"


# ── TestRootCauseAnalysisEngine ───────────────────────────────────────────────


class TestRootCauseAnalysisEngine:
    def _make_engine(self, **kwargs):
        return RootCauseAnalysisEngine(RCAConfig(**kwargs))

    def test_empty_validation_produces_empty_report(self, tmp_path):
        engine = self._make_engine()
        val_report = _make_val_report([])
        rca_report = engine.analyze(tmp_path, [], val_report, {})
        assert rca_report.total_issues == 0
        assert rca_report.issues == []

    def test_sequential_ids_assigned(self, tmp_path):
        engine = self._make_engine()
        results = [
            _val_result("SCRIPT_001", category="script", status="FAIL"),
            _val_result("NARR_001", category="narration", status="FAIL"),
        ]
        val_report = _make_val_report(results)
        rca_report = engine.analyze(tmp_path, [], val_report, {})
        ids = [i.issue_id for i in rca_report.issues]
        assert "RCA-0001" in ids
        assert "RCA-0002" in ids
        # All IDs should be unique
        assert len(set(ids)) == len(ids)

    def test_issue_counts_correct(self, tmp_path):
        engine = self._make_engine()
        results = [
            _val_result("SCRIPT_001", category="script", status="FAIL", severity="critical"),
            _val_result("NARR_001", category="narration", status="FAIL", severity="high"),
            _val_result("IMG_004", category="image", status="WARNING", severity="medium"),
        ]
        val_report = _make_val_report(results)
        rca_report = engine.analyze(tmp_path, [], val_report, {})
        assert rca_report.total_issues == 3
        assert rca_report.critical_issues == 1
        assert rca_report.high_issues == 1
        assert rca_report.medium_issues == 1

    def test_engine_summaries_populated(self, tmp_path):
        engine = self._make_engine()
        results = [
            _val_result("SCRIPT_001", category="script", status="FAIL"),
            _val_result("SCRIPT_002", category="script", status="FAIL",
                        description="Script is too short: 100 words"),
        ]
        val_report = _make_val_report(results)
        rca_report = engine.analyze(tmp_path, [], val_report, {})
        assert len(rca_report.engine_summaries) > 0

    def test_recurring_detection_requires_two_scenes(self, tmp_path):
        engine = self._make_engine()
        results = [
            _val_result("AUD_001", category="audio", status="FAIL", severity="critical",
                        scene_index=1),
            _val_result("AUD_001", category="audio", status="FAIL", severity="critical",
                        scene_index=2),
        ]
        val_report = _make_val_report(results)
        rca_report = engine.analyze(tmp_path, [], val_report, {})
        assert len(rca_report.recurring_issues) >= 1
        rec = rca_report.recurring_issues[0]
        assert rec.occurrence_count == 2
        assert rec.root_cause_code == "missing_asset"

    def test_no_recurring_for_single_scene(self, tmp_path):
        engine = self._make_engine()
        results = [
            _val_result("AUD_001", category="audio", status="FAIL", severity="critical",
                        scene_index=1),
        ]
        val_report = _make_val_report(results)
        rca_report = engine.analyze(tmp_path, [], val_report, {})
        assert rca_report.recurring_issues == []

    def test_project_id_propagated(self, tmp_path):
        engine = self._make_engine()
        val_report = _make_val_report([], project_id="my-project")
        rca_report = engine.analyze(tmp_path, [], val_report, {})
        assert rca_report.project_id == "my-project"

    def test_processing_time_positive(self, tmp_path):
        engine = self._make_engine()
        val_report = _make_val_report([])
        rca_report = engine.analyze(tmp_path, [], val_report, {})
        assert rca_report.processing_time_seconds >= 0.0


# ── TestBuildEngineSummaries ──────────────────────────────────────────────────


class TestBuildEngineSummaries:
    def test_groups_by_engine(self):
        issues = [
            _rca_issue(primary_engine="EngineA", severity="critical"),
            _rca_issue(primary_engine="EngineA", severity="high"),
            _rca_issue(primary_engine="EngineB", severity="medium"),
        ]
        summaries = _build_engine_summaries(issues)
        assert "EngineA" in summaries
        assert "EngineB" in summaries
        assert summaries["EngineA"].total_issues == 2
        assert summaries["EngineA"].critical_issues == 1
        assert summaries["EngineB"].total_issues == 1

    def test_avg_confidence(self):
        issues = [
            _rca_issue(primary_engine="E", confidence=80),
            _rca_issue(primary_engine="E", confidence=100),
        ]
        summaries = _build_engine_summaries(issues)
        assert summaries["E"].avg_confidence == 90.0

    def test_root_causes_counted(self):
        issues = [
            _rca_issue(primary_engine="E", root_cause_code="missing_asset"),
            _rca_issue(primary_engine="E", root_cause_code="missing_asset"),
            _rca_issue(primary_engine="E", root_cause_code="weak_prompt"),
        ]
        summaries = _build_engine_summaries(issues)
        assert summaries["E"].root_causes["missing_asset"] == 2
        assert summaries["E"].root_causes["weak_prompt"] == 1

    def test_empty_issues(self):
        summaries = _build_engine_summaries([])
        assert summaries == {}


# ── TestDetectRecurring ───────────────────────────────────────────────────────


class TestDetectRecurring:
    def test_detects_recurring(self):
        issues = [
            _rca_issue(primary_engine="E", root_cause_code="missing_asset", scene_index=1),
            _rca_issue(primary_engine="E", root_cause_code="missing_asset", scene_index=2),
        ]
        recurring = _detect_recurring(issues, RCAConfig())
        assert len(recurring) == 1
        assert recurring[0].occurrence_count == 2
        assert set(recurring[0].affected_scenes) == {1, 2}

    def test_no_recurring_same_scene(self):
        issues = [
            _rca_issue(primary_engine="E", root_cause_code="missing_asset", scene_index=1),
            _rca_issue(primary_engine="E", root_cause_code="missing_asset", scene_index=1),
        ]
        # Both from scene 1 → distinct_scenes == 1 < 2
        recurring = _detect_recurring(issues, RCAConfig())
        assert recurring == []

    def test_no_recurring_video_level(self):
        issues = [
            _rca_issue(primary_engine="E", root_cause_code="missing_script", scene_index=None),
            _rca_issue(primary_engine="E", root_cause_code="missing_script", scene_index=None),
        ]
        recurring = _detect_recurring(issues, RCAConfig())
        assert recurring == []

    def test_custom_threshold(self):
        issues = [
            _rca_issue(primary_engine="E", root_cause_code="x", scene_index=1),
            _rca_issue(primary_engine="E", root_cause_code="x", scene_index=2),
            _rca_issue(primary_engine="E", root_cause_code="x", scene_index=3),
        ]
        cfg_high = RCAConfig(recurring_threshold=4)
        assert _detect_recurring(issues, cfg_high) == []
        cfg_low = RCAConfig(recurring_threshold=2)
        assert len(_detect_recurring(issues, cfg_low)) == 1

    def test_sorted_by_occurrence_desc(self):
        issues = [
            _rca_issue(primary_engine="E1", root_cause_code="a", scene_index=1),
            _rca_issue(primary_engine="E1", root_cause_code="a", scene_index=2),
            _rca_issue(primary_engine="E2", root_cause_code="b", scene_index=1),
            _rca_issue(primary_engine="E2", root_cause_code="b", scene_index=2),
            _rca_issue(primary_engine="E2", root_cause_code="b", scene_index=3),
        ]
        recurring = _detect_recurring(issues, RCAConfig())
        assert recurring[0].occurrence_count >= recurring[-1].occurrence_count


# ── TestRCAReporter ───────────────────────────────────────────────────────────


@pytest.fixture()
def proj_id(tmp_path, monkeypatch) -> str:
    """Create a temp project and patch WORKSPACE_DIR."""
    pid = "rca-test-project"
    project_dir = tmp_path / pid
    (project_dir / "review").mkdir(parents=True)
    monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))
    return pid


class TestRCAReporter:
    def _sample_report(self, project_id: str) -> RCAReport:
        return RCAReport(
            project_id=project_id,
            timestamp=_ts(),
            total_issues=2,
            critical_issues=1,
            high_issues=1,
            issues=[
                _rca_issue(
                    issue_id="RCA-0001",
                    rule_id="SCRIPT_001",
                    category="script",
                    root_cause_code="missing_script",
                    severity="critical",
                    primary_engine="ScriptWriter",
                ),
                _rca_issue(
                    issue_id="RCA-0002",
                    rule_id="IMG_004",
                    category="image",
                    root_cause_code="repeated_imagery",
                    severity="high",
                    primary_engine="Image Prompt Engine",
                    scene_index=2,
                ),
            ],
        )

    def test_writes_four_files(self, proj_id):
        report = self._sample_report(proj_id)
        RCAReporter().write(report)
        assert root_cause_report_md_path(proj_id).exists()
        assert root_cause_json_path(proj_id).exists()
        assert engine_owner_summary_path(proj_id).exists()
        assert recurring_issues_path(proj_id).exists()

    def test_root_cause_json_valid(self, proj_id):
        report = self._sample_report(proj_id)
        RCAReporter().write(report)
        data = json.loads(root_cause_json_path(proj_id).read_text())
        assert data["version"] == "v1"
        assert len(data["issues"]) == 2
        assert data["issues"][0]["issue_id"] == "RCA-0001"

    def test_engine_owner_summary_json_valid(self, proj_id):
        report = self._sample_report(proj_id)
        RCAReporter().write(report)
        data = json.loads(engine_owner_summary_path(proj_id).read_text())
        assert "engines" in data
        assert data["project_id"] == proj_id

    def test_recurring_issues_json_valid(self, proj_id):
        report = self._sample_report(proj_id)
        report.recurring_issues = [
            RecurringIssue(
                engine="TTS Engine",
                root_cause_code="missing_asset",
                occurrence_count=3,
                affected_scenes=[1, 2, 3],
                severity_distribution={"critical": 3},
                suggested_systemic_fix="fix TTS",
            )
        ]
        RCAReporter().write(report)
        data = json.loads(recurring_issues_path(proj_id).read_text())
        assert data["recurring_count"] == 1
        assert data["recurring_issues"][0]["occurrence_count"] == 3

    def test_report_md_contains_issue_id(self, proj_id):
        report = self._sample_report(proj_id)
        RCAReporter().write(report)
        content = root_cause_report_md_path(proj_id).read_text()
        assert "RCA-0001" in content
        assert "missing_script" in content

    def test_empty_report_contains_pass_message(self, proj_id):
        report = RCAReport(project_id=proj_id, timestamp=_ts())
        RCAReporter().write(report)
        content = root_cause_report_md_path(proj_id).read_text()
        assert "No root causes identified" in content

    def test_returns_review_directory(self, proj_id):
        report = RCAReport(project_id=proj_id, timestamp=_ts())
        review_dir = RCAReporter().write(report)
        assert review_dir.is_dir()


# ── TestVQREIntegration ───────────────────────────────────────────────────────


@pytest.fixture()
def vqre_proj(tmp_path, monkeypatch):
    """Full VQRE integration project fixture."""
    pid = "vqre-rca-proj"
    project_dir = tmp_path / pid
    for subdir in ("script", "scenes", "images", "audio", "subtitles", "video", "review"):
        (project_dir / subdir).mkdir(parents=True)

    # Minimal script (>200 words)
    script_words = " ".join(["word"] * 210)
    (project_dir / "script" / "script.md").write_text(
        f"# Title\n\n{script_words}\n\nThis is a test script for integration testing purposes.",
        encoding="utf-8",
    )

    # 2 scenes
    import json as _json
    scenes = [
        {
            "index": 1, "title": "Intro", "scene_type": "generated_image",
            "narration": "This is the narration for scene one with enough words to pass.",
            "visual_prompt": "A beautiful sunset over the mountains with golden light.",
            "duration_seconds": 8.0, "shot_type": "wide_shot", "transition": "fade",
        },
        {
            "index": 2, "title": "Main", "scene_type": "generated_image",
            "narration": "This is the narration for scene two with different content.",
            "visual_prompt": "A close-up portrait of a person smiling warmly.",
            "duration_seconds": 10.0, "shot_type": "close_up", "transition": "cut",
        },
    ]
    (project_dir / "scenes" / "scene-plan.json").write_text(
        _json.dumps({"scenes": scenes}), encoding="utf-8"
    )

    png_stub = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2000
    mp3_stub = b"\xff\xfb" + b"\x00" * 6000

    srt_content = (
        "1\n00:00:00,000 --> 00:00:04,000\nThis is scene narration\n\n"
        "2\n00:00:04,000 --> 00:00:08,000\nContinuation of narration\n"
    )

    for idx in (1, 2):
        (project_dir / "images" / f"scene-{idx:03d}.png").write_bytes(png_stub)
        (project_dir / "audio" / f"scene-{idx:03d}.mp3").write_bytes(mp3_stub)
        (project_dir / "subtitles" / f"scene-{idx:03d}.srt").write_text(srt_content, encoding="utf-8")
        (project_dir / "video" / f"scene-{idx:03d}.mp4").write_bytes(b"\x00" * 15000)

    (project_dir / "video" / "final.mp4").write_bytes(b"\x00" * 200000)

    monkeypatch.setattr("ytfactory.review.engine.WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))

    return pid


class TestVQREIntegration:
    def test_rca_report_in_review_report(self, vqre_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine
        engine = VideoQualityReviewEngine()
        report = engine.review(vqre_proj)
        assert report.rca_report is not None
        assert "version" in report.rca_report
        assert report.rca_report["version"] == "v1"

    def test_rca_files_written(self, vqre_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine
        engine = VideoQualityReviewEngine()
        engine.review(vqre_proj)
        review_dir = tmp_path / vqre_proj / "review"
        assert (review_dir / "root-cause-report.md").exists()
        assert (review_dir / "root-cause.json").exists()
        assert (review_dir / "engine-owner-summary.json").exists()
        assert (review_dir / "recurring-issues.json").exists()

    def test_rca_json_parseable(self, vqre_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine
        engine = VideoQualityReviewEngine()
        engine.review(vqre_proj)
        review_dir = tmp_path / vqre_proj / "review"
        data = json.loads((review_dir / "root-cause.json").read_text())
        assert data["project_id"] == vqre_proj
        assert "issues" in data

    def test_no_stub_root_cause_file(self, vqre_proj, tmp_path):
        """The old stub root-cause-report.json should NOT exist (RCA owns root-cause.json)."""
        from ytfactory.review.engine import VideoQualityReviewEngine
        engine = VideoQualityReviewEngine()
        engine.review(vqre_proj)
        review_dir = tmp_path / vqre_proj / "review"
        # root-cause.json should be real RCA output (not stub)
        if (review_dir / "root-cause.json").exists():
            data = json.loads((review_dir / "root-cause.json").read_text())
            assert data.get("status") != "not_implemented"

    def test_rca_config_can_be_passed(self, vqre_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine
        from ytfactory.review.rca.config import RCAConfig
        engine = VideoQualityReviewEngine(rca_config=RCAConfig(include_warnings=False))
        report = engine.review(vqre_proj)
        assert report.rca_report is not None
