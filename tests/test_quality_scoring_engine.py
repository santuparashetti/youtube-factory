"""Tests for the Quality Scoring Engine V1.

Covers:
  - RuleContribution, CategoryScore, QualityScoreReport models
  - QualityScoringConfig (thresholds, grades, verdict, weights)
  - BaseCategoryScorer (aggregation, absent/skip/pass/fail/warning logic)
  - All 8 category scorers
  - QualityScoringEngine orchestration (overall score, grade, verdict, recs)
  - QualityScoringReporter (4 output files, history accumulation)
  - Integration: VQRE runs QSE and populates quality_score_report
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ytfactory.review.rca.models import RCAReport
from ytfactory.review.scoring.config import DEFAULT_WEIGHTS, QualityScoringConfig
from ytfactory.review.scoring.engine import QualityScoringEngine, _recommendations, _weighted_average
from ytfactory.review.scoring.framework import BaseCategoryScorer
from ytfactory.review.scoring.models import CategoryScore, QualityScoreReport, RuleContribution
from ytfactory.review.scoring.reporter import (
    QualityScoringReporter,
    quality_report_md_path,
    quality_score_path,
    score_breakdown_path,
    score_history_path,
)
from ytfactory.review.scoring.scorers.audio import AudioScorer
from ytfactory.review.scoring.scorers.image import ImageScorer
from ytfactory.review.scoring.scorers.motion import MotionScorer
from ytfactory.review.scoring.scorers.narration import NarrationScorer
from ytfactory.review.scoring.scorers.rendering import RenderingScorer
from ytfactory.review.scoring.scorers.script import ScriptScorer
from ytfactory.review.scoring.scorers.storytelling import StorytellingScorer
from ytfactory.review.scoring.scorers.subtitle import SubtitleScorer
from ytfactory.review.validation.models import ValidationReport, ValidationResult


# ── Shared helpers ────────────────────────────────────────────────────────────


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vr(
    rule_id: str,
    category: str,
    status: str = "PASS",
    severity: str = "high",
    description: str = "test",
    scene_index: int | None = None,
) -> ValidationResult:
    return ValidationResult(
        rule_id=rule_id,
        category=category,
        status=status,
        severity=severity,
        description=description,
        evidence="evidence",
        confidence=0.9,
        responsible_engine="TestEngine",
        timestamp=_ts(),
        scene_index=scene_index,
    )


def _val_report(results: list[ValidationResult], project_id: str = "p") -> ValidationReport:
    return ValidationReport(
        project_id=project_id,
        timestamp=_ts(),
        total_rules_run=len(results),
        results=results,
    )


def _rca_report(project_id: str = "p") -> RCAReport:
    return RCAReport(project_id=project_id, timestamp=_ts())


def _cat_score(
    category: str,
    raw_score: float = 85.0,
    weight: float = 0.10,
    confidence: float = 1.0,
    failed_rules: list[str] | None = None,
) -> CategoryScore:
    return CategoryScore(
        category=category,
        raw_score=raw_score,
        weighted_score=round(raw_score * weight, 4),
        weight=weight,
        confidence=confidence,
        evidence=[],
        summary="test",
        failed_rules=failed_rules or [],
    )


# ── TestRuleContribution ──────────────────────────────────────────────────────


class TestRuleContribution:
    def test_to_dict_keys(self):
        rc = RuleContribution(
            rule_id="SCRIPT_001",
            points_available=40.0,
            points_earned=40.0,
            status="pass",
            evidence="",
        )
        d = rc.to_dict()
        assert d["rule_id"] == "SCRIPT_001"
        assert d["points_available"] == 40.0
        assert d["points_earned"] == 40.0
        assert d["status"] == "pass"

    def test_zero_earned(self):
        rc = RuleContribution(
            rule_id="X", points_available=50.0, points_earned=0.0,
            status="fail", evidence="failed"
        )
        assert rc.points_earned == 0.0


# ── TestCategoryScore ─────────────────────────────────────────────────────────


class TestCategoryScore:
    def test_to_dict_keys(self):
        cs = _cat_score("script")
        d = cs.to_dict()
        for key in ("category", "raw_score", "weighted_score", "weight",
                    "confidence", "evidence", "summary", "failed_rules", "contributions"):
            assert key in d

    def test_weighted_score_product(self):
        cs = _cat_score("script", raw_score=80.0, weight=0.10)
        assert abs(cs.weighted_score - 8.0) < 0.01

    def test_contributions_serialised(self):
        cs = _cat_score("script")
        cs.contributions = [
            RuleContribution("R", 10.0, 10.0, "pass", "")
        ]
        assert len(cs.to_dict()["contributions"]) == 1


# ── TestQualityScoreReport ────────────────────────────────────────────────────


class TestQualityScoreReport:
    def test_defaults(self):
        report = QualityScoreReport(project_id="x", timestamp=_ts())
        assert report.overall_score == 0.0
        assert report.letter_grade == "F"
        assert report.verdict == "FAIL"

    def test_to_dict_version(self):
        report = QualityScoreReport(project_id="x", timestamp=_ts())
        d = report.to_dict()
        assert d["version"] == "v1"
        assert "overall_score" in d
        assert "letter_grade" in d
        assert "verdict" in d
        assert "category_scores" in d

    def test_to_dict_rounds_score(self):
        report = QualityScoreReport(
            project_id="x", timestamp=_ts(), overall_score=85.123456
        )
        d = report.to_dict()
        assert d["overall_score"] == 85.12


# ── TestQualityScoringConfig ──────────────────────────────────────────────────


class TestQualityScoringConfig:
    def test_defaults(self):
        cfg = QualityScoringConfig()
        assert cfg.publish_threshold == 70.0
        assert cfg.warning_threshold == 60.0
        assert cfg.critical_threshold == 50.0
        assert abs(sum(cfg.weights.values()) - 1.0) < 0.001

    def test_letter_grade_a_plus(self):
        cfg = QualityScoringConfig()
        assert cfg.letter_grade(97.0) == "A+"

    def test_letter_grade_a(self):
        cfg = QualityScoringConfig()
        assert cfg.letter_grade(92.0) == "A"

    def test_letter_grade_b(self):
        cfg = QualityScoringConfig()
        assert cfg.letter_grade(85.0) == "B"

    def test_letter_grade_c(self):
        cfg = QualityScoringConfig()
        assert cfg.letter_grade(75.0) == "C"

    def test_letter_grade_d(self):
        cfg = QualityScoringConfig()
        assert cfg.letter_grade(65.0) == "D"

    def test_letter_grade_f(self):
        cfg = QualityScoringConfig()
        assert cfg.letter_grade(45.0) == "F"

    def test_verdict_pass(self):
        cfg = QualityScoringConfig()
        assert cfg.verdict_for(80.0, {}) == "PASS"

    def test_verdict_fail_below_threshold(self):
        cfg = QualityScoringConfig()
        assert cfg.verdict_for(65.0, {}) == "FAIL"

    def test_verdict_fail_category_minimum(self):
        cfg = QualityScoringConfig(category_minimums={"rendering": 60.0})
        assert cfg.verdict_for(80.0, {"rendering": 50.0}) == "FAIL"

    def test_verdict_pass_category_minimum_met(self):
        cfg = QualityScoringConfig(category_minimums={"rendering": 60.0})
        assert cfg.verdict_for(80.0, {"rendering": 75.0}) == "PASS"

    def test_default_weights_sum_to_one(self):
        assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 0.001


# ── TestBaseCategoryScorer (via concrete scorer) ──────────────────────────────


class TestBaseCategoryScorer:
    """Test the framework logic through the concrete ScriptScorer."""

    def _run(self, results, tmp_path):
        return ScriptScorer(QualityScoringConfig()).score(
            tmp_path, [], _val_report(results), _rca_report(), {}
        )

    def test_all_pass_gives_100(self, tmp_path):
        results = [_vr(rid, "script", "PASS") for rid in
                   ("SCRIPT_001", "SCRIPT_002", "SCRIPT_003", "SCRIPT_004", "SCRIPT_005")]
        cs = self._run(results, tmp_path)
        assert cs.raw_score == 100.0

    def test_all_fail_gives_0(self, tmp_path):
        results = [_vr(rid, "script", "FAIL") for rid in
                   ("SCRIPT_001", "SCRIPT_002", "SCRIPT_003", "SCRIPT_004", "SCRIPT_005")]
        cs = self._run(results, tmp_path)
        assert cs.raw_score == 0.0

    def test_single_critical_fail_reduces_score(self, tmp_path):
        # Only SCRIPT_001 fails (40 pts out of 100)
        results = [
            _vr("SCRIPT_001", "script", "FAIL"),
            _vr("SCRIPT_002", "script", "PASS"),
            _vr("SCRIPT_003", "script", "PASS"),
            _vr("SCRIPT_004", "script", "PASS"),
            _vr("SCRIPT_005", "script", "PASS"),
        ]
        cs = self._run(results, tmp_path)
        assert cs.raw_score < 100.0
        assert cs.raw_score == 60.0  # 60/100 earned

    def test_warning_gives_half_penalty(self, tmp_path):
        # SCRIPT_001 WARNING — 50% of 40 pts lost → 20 pts lost → score = 80
        results = [
            _vr("SCRIPT_001", "script", "WARNING"),
            _vr("SCRIPT_002", "script", "PASS"),
            _vr("SCRIPT_003", "script", "PASS"),
            _vr("SCRIPT_004", "script", "PASS"),
            _vr("SCRIPT_005", "script", "PASS"),
        ]
        cs = self._run(results, tmp_path)
        assert cs.raw_score == 80.0

    def test_no_results_gives_100_neutral(self, tmp_path):
        # Empty results → all rules absent → neutral 100
        cs = self._run([], tmp_path)
        assert cs.raw_score == 100.0

    def test_all_skip_gives_100_confidence_reduced(self, tmp_path):
        results = [_vr(rid, "script", "SKIP") for rid in
                   ("SCRIPT_001", "SCRIPT_002", "SCRIPT_003", "SCRIPT_004", "SCRIPT_005")]
        cs = self._run(results, tmp_path)
        assert cs.raw_score == 100.0
        assert cs.confidence < 1.0

    def test_failed_rules_populated(self, tmp_path):
        results = [_vr("SCRIPT_001", "script", "FAIL")]
        cs = self._run(results, tmp_path)
        assert "SCRIPT_001" in cs.failed_rules

    def test_evidence_populated_on_fail(self, tmp_path):
        results = [_vr("SCRIPT_001", "script", "FAIL",
                        description="Script file is missing")]
        cs = self._run(results, tmp_path)
        assert len(cs.evidence) > 0
        assert "SCRIPT_001" in cs.evidence[0]

    def test_weighted_score_uses_weight(self, tmp_path):
        results = [_vr("SCRIPT_001", "script", "PASS")]
        cs = self._run(results, tmp_path)
        assert abs(cs.weighted_score - cs.raw_score * cs.weight) < 0.01

    def test_category_set_correctly(self, tmp_path):
        cs = self._run([], tmp_path)
        assert cs.category == "script"

    def test_exception_in_scorer_produces_skip_contribution(self, tmp_path):
        """Exception in _score_category produces a skip contribution, not a crash."""
        class BrokenScorer(BaseCategoryScorer):
            category = "script"
            def _score_category(self, *a, **kw):
                raise RuntimeError("deliberate")
        cs = BrokenScorer(QualityScoringConfig()).score(
            tmp_path, [], _val_report([]), _rca_report(), {}
        )
        # Score defaults to 100 (neutral) because the error contribution is a skip
        assert cs.raw_score == 100.0


# ── TestScriptScorer ──────────────────────────────────────────────────────────


class TestScriptScorer:
    def _score(self, results, tmp_path):
        return ScriptScorer(QualityScoringConfig()).score(
            tmp_path, [], _val_report(results), _rca_report(), {}
        )

    def test_perfect_score_all_pass(self, tmp_path):
        results = [_vr(rid, "script", "PASS") for rid in
                   ("SCRIPT_001", "SCRIPT_002", "SCRIPT_003", "SCRIPT_004", "SCRIPT_005")]
        assert self._score(results, tmp_path).raw_score == 100.0

    def test_script_001_fail_dominant(self, tmp_path):
        results = [_vr("SCRIPT_001", "script", "FAIL")]
        cs = self._score(results, tmp_path)
        # 40 pts lost from 40 available (other rules absent = neutral)
        assert cs.raw_score < 100.0
        assert "SCRIPT_001" in cs.failed_rules

    def test_script_002_fail(self, tmp_path):
        results = [_vr("SCRIPT_002", "script", "FAIL")]
        cs = self._score(results, tmp_path)
        assert cs.raw_score < 100.0

    def test_mixed_pass_fail(self, tmp_path):
        results = [
            _vr("SCRIPT_001", "script", "PASS"),
            _vr("SCRIPT_002", "script", "FAIL"),
        ]
        cs = self._score(results, tmp_path)
        assert 0 < cs.raw_score < 100


# ── TestNarrationScorer ───────────────────────────────────────────────────────


class TestNarrationScorer:
    def _score(self, results, tmp_path):
        return NarrationScorer(QualityScoringConfig()).score(
            tmp_path, [], _val_report(results), _rca_report(), {}
        )

    def test_all_pass(self, tmp_path):
        results = [_vr(rid, "narration", "PASS") for rid in
                   ("NARR_001", "NARR_002", "NARR_003", "NARR_004")]
        assert self._score(results, tmp_path).raw_score == 100.0

    def test_narr_001_fail_per_scene(self, tmp_path):
        results = [
            _vr("NARR_001", "narration", "FAIL", scene_index=1),
            _vr("NARR_001", "narration", "PASS", scene_index=2),
        ]
        cs = self._score(results, tmp_path)
        # 1 of 2 checks pass for NARR_001 (40 pts) → 20 pts earned for that rule
        assert cs.raw_score < 100.0

    def test_narr_004_warning(self, tmp_path):
        results = [_vr("NARR_004", "narration", "WARNING")]
        cs = self._score(results, tmp_path)
        assert cs.raw_score < 100.0
        assert cs.raw_score > 0.0


# ── TestSubtitleScorer ────────────────────────────────────────────────────────


class TestSubtitleScorer:
    def _score(self, results, tmp_path):
        return SubtitleScorer(QualityScoringConfig()).score(
            tmp_path, [], _val_report(results), _rca_report(), {}
        )

    def test_all_pass(self, tmp_path):
        results = [_vr(rid, "subtitle", "PASS") for rid in
                   ("SUBT_001", "SUBT_002", "SUBT_003", "SUBT_004", "SUBT_005", "SUBT_006")]
        assert self._score(results, tmp_path).raw_score == 100.0

    def test_missing_srt_dominant_penalty(self, tmp_path):
        results = [_vr("SUBT_001", "subtitle", "FAIL")]
        cs = self._score(results, tmp_path)
        assert "SUBT_001" in cs.failed_rules

    def test_all_skip(self, tmp_path):
        results = [_vr(rid, "subtitle", "SKIP") for rid in
                   ("SUBT_001", "SUBT_002", "SUBT_003", "SUBT_004", "SUBT_005", "SUBT_006")]
        cs = self._score(results, tmp_path)
        assert cs.raw_score == 100.0
        assert cs.confidence < 1.0


# ── TestImageScorer ───────────────────────────────────────────────────────────


class TestImageScorer:
    def _score(self, results, tmp_path):
        return ImageScorer(QualityScoringConfig()).score(
            tmp_path, [], _val_report(results), _rca_report(), {}
        )

    def test_all_pass(self, tmp_path):
        results = [_vr(rid, "image", "PASS") for rid in
                   ("IMG_001", "IMG_002", "IMG_003", "IMG_004", "IMG_005", "IMG_006")]
        assert self._score(results, tmp_path).raw_score == 100.0

    def test_missing_image_dominant(self, tmp_path):
        results = [_vr("IMG_001", "image", "FAIL")]
        cs = self._score(results, tmp_path)
        assert "IMG_001" in cs.failed_rules

    def test_partial_scene_failure(self, tmp_path):
        results = [
            _vr("IMG_001", "image", "FAIL", scene_index=1),
            _vr("IMG_001", "image", "PASS", scene_index=2),
            _vr("IMG_001", "image", "PASS", scene_index=3),
        ]
        cs = self._score(results, tmp_path)
        # 2/3 pass for IMG_001 → partial credit
        assert 0 < cs.raw_score < 100


# ── TestMotionScorer ──────────────────────────────────────────────────────────


class TestMotionScorer:
    def _score(self, results, tmp_path):
        return MotionScorer(QualityScoringConfig()).score(
            tmp_path, [], _val_report(results), _rca_report(), {}
        )

    def test_all_pass(self, tmp_path):
        results = [_vr(rid, "motion", "PASS") for rid in
                   ("MOT_001", "MOT_002", "MOT_003", "MOT_004")]
        assert self._score(results, tmp_path).raw_score == 100.0

    def test_zero_duration_critical(self, tmp_path):
        results = [_vr("MOT_002", "motion", "FAIL", severity="critical")]
        cs = self._score(results, tmp_path)
        assert "MOT_002" in cs.failed_rules

    def test_transition_warning(self, tmp_path):
        results = [_vr("MOT_004", "motion", "WARNING")]
        cs = self._score(results, tmp_path)
        assert cs.raw_score < 100.0


# ── TestAudioScorer ───────────────────────────────────────────────────────────


class TestAudioScorer:
    def _score(self, results, tmp_path):
        return AudioScorer(QualityScoringConfig()).score(
            tmp_path, [], _val_report(results), _rca_report(), {}
        )

    def test_all_pass(self, tmp_path):
        results = [_vr(rid, "audio", "PASS") for rid in
                   ("AUD_001", "AUD_002", "AUD_003")]
        assert self._score(results, tmp_path).raw_score == 100.0

    def test_aud_004_always_skip_is_neutral(self, tmp_path):
        results = [
            _vr("AUD_001", "audio", "PASS"),
            _vr("AUD_004", "audio", "SKIP"),
        ]
        cs = self._score(results, tmp_path)
        # AUD_004 SKIP → excluded from scoring; AUD_001 PASS → no penalty
        assert "AUD_004" not in cs.failed_rules

    def test_missing_audio_dominant(self, tmp_path):
        results = [_vr("AUD_001", "audio", "FAIL", severity="critical")]
        cs = self._score(results, tmp_path)
        assert "AUD_001" in cs.failed_rules

    def test_partial_audio_failure(self, tmp_path):
        results = [
            _vr("AUD_001", "audio", "FAIL", scene_index=1),
            _vr("AUD_001", "audio", "PASS", scene_index=2),
        ]
        cs = self._score(results, tmp_path)
        assert 0 < cs.raw_score < 100


# ── TestRenderingScorer ───────────────────────────────────────────────────────


class TestRenderingScorer:
    def _score(self, results, tmp_path):
        return RenderingScorer(QualityScoringConfig()).score(
            tmp_path, [], _val_report(results), _rca_report(), {}
        )

    def test_all_pass(self, tmp_path):
        results = [_vr(rid, "rendering", "PASS") for rid in
                   ("REND_001", "REND_002", "REND_003", "REND_004", "REND_005")]
        assert self._score(results, tmp_path).raw_score == 100.0

    def test_final_missing_dominant(self, tmp_path):
        results = [_vr("REND_003", "rendering", "FAIL", severity="critical")]
        cs = self._score(results, tmp_path)
        assert "REND_003" in cs.failed_rules

    def test_all_fail_gives_0(self, tmp_path):
        results = [_vr(rid, "rendering", "FAIL") for rid in
                   ("REND_001", "REND_002", "REND_003", "REND_004", "REND_005")]
        assert self._score(results, tmp_path).raw_score == 0.0

    def test_highest_weight_in_default_config(self):
        cfg = QualityScoringConfig()
        assert cfg.weights["rendering"] == max(cfg.weights.values())


# ── TestStorytellingScorer ────────────────────────────────────────────────────


class TestStorytellingScorer:
    def _score(self, results, tmp_path):
        return StorytellingScorer(QualityScoringConfig()).score(
            tmp_path, [], _val_report(results), _rca_report(), {}
        )

    def test_all_pass(self, tmp_path):
        results = [_vr(rid, "story", "PASS") for rid in
                   ("STOR_001", "STOR_002", "STOR_003", "STOR_004", "STOR_005")]
        assert self._score(results, tmp_path).raw_score == 100.0

    def test_uses_story_category(self, tmp_path):
        # Results with "script" category should NOT affect storytelling score
        results = [_vr("SCRIPT_001", "script", "FAIL")]
        cs = self._score(results, tmp_path)
        assert cs.raw_score == 100.0  # no story-category results → all absent → neutral

    def test_stor_004_repeated_narration_dominant(self, tmp_path):
        results = [_vr("STOR_004", "story", "WARNING")]
        cs = self._score(results, tmp_path)
        assert cs.raw_score < 100.0

    def test_category_name_is_storytelling(self, tmp_path):
        cs = self._score([], tmp_path)
        assert cs.category == "storytelling"


# ── TestWeightedAverage ───────────────────────────────────────────────────────


class TestWeightedAverage:
    def test_empty_gives_zero(self):
        assert _weighted_average({}) == 0.0

    def test_single_category(self):
        cat = _cat_score("script", raw_score=80.0, weight=1.0)
        cat.weighted_score = 80.0
        scores = {"script": cat}
        assert abs(_weighted_average(scores) - 80.0) < 0.01

    def test_two_equal_weight_categories(self):
        s1 = _cat_score("a", raw_score=100.0, weight=0.5)
        s1.weighted_score = 50.0
        s2 = _cat_score("b", raw_score=60.0, weight=0.5)
        s2.weighted_score = 30.0
        scores = {"a": s1, "b": s2}
        assert abs(_weighted_average(scores) - 80.0) < 0.01

    def test_weighted_average_reflects_category_weights(self):
        # Rendering (0.20) scoring 0 should drag overall down more than script (0.10) scoring 0
        cfg = QualityScoringConfig()
        rendering_zero = _cat_score("rendering", raw_score=0.0, weight=0.20)
        rendering_zero.weighted_score = 0.0
        other_perfect = {
            cat: _cat_score(cat, raw_score=100.0, weight=w)
            for cat, w in cfg.weights.items()
            if cat != "rendering"
        }
        for cs in other_perfect.values():
            cs.weighted_score = cs.raw_score * cs.weight
        all_scores = {**other_perfect, "rendering": rendering_zero}
        result = _weighted_average(all_scores)
        assert result < 100.0
        assert result > 0.0


# ── TestRecommendations ───────────────────────────────────────────────────────


class TestRecommendations:
    def test_no_recs_when_all_good(self):
        cfg = QualityScoringConfig()
        scores = {
            cat: _cat_score(cat, raw_score=90.0, weight=w)
            for cat, w in cfg.weights.items()
        }
        recs = _recommendations(scores, cfg)
        assert recs == []

    def test_recs_for_low_score(self):
        cfg = QualityScoringConfig()
        scores = {
            cat: _cat_score(cat, raw_score=40.0, weight=w)
            for cat, w in cfg.weights.items()
        }
        recs = _recommendations(scores, cfg)
        assert len(recs) > 0

    def test_max_five_recs(self):
        cfg = QualityScoringConfig()
        scores = {
            cat: _cat_score(cat, raw_score=30.0, weight=w)
            for cat, w in cfg.weights.items()
        }
        recs = _recommendations(scores, cfg)
        assert len(recs) <= 5

    def test_highest_impact_first(self):
        cfg = QualityScoringConfig()
        # Rendering has highest weight (0.20), so it should be first
        scores = {
            cat: _cat_score(cat, raw_score=50.0, weight=w)
            for cat, w in cfg.weights.items()
        }
        recs = _recommendations(scores, cfg)
        assert "rendering" in recs[0].lower()

    def test_rec_contains_category_name(self):
        cfg = QualityScoringConfig()
        scores = {"rendering": _cat_score("rendering", raw_score=30.0, weight=0.20)}
        recs = _recommendations(scores, cfg)
        assert any("rendering" in r.lower() for r in recs)


# ── TestQualityScoringEngine ──────────────────────────────────────────────────


class TestQualityScoringEngine:
    def _engine(self, **cfg_kwargs):
        return QualityScoringEngine(QualityScoringConfig(**cfg_kwargs))

    def test_produces_all_8_categories(self, tmp_path):
        engine = self._engine()
        report = engine.score(tmp_path, [], _val_report([]), _rca_report(), {})
        assert len(report.category_scores) == 8
        for cat in ("script", "narration", "subtitle", "image",
                    "motion", "audio", "rendering", "storytelling"):
            assert cat in report.category_scores

    def test_overall_score_100_on_all_pass(self, tmp_path):
        engine = self._engine()
        all_pass = [
            _vr(rid, cat, "PASS")
            for cat, rules in {
                "script": ("SCRIPT_001", "SCRIPT_002"),
                "narration": ("NARR_001",),
                "subtitle": ("SUBT_001",),
                "image": ("IMG_001",),
                "motion": ("MOT_001",),
                "audio": ("AUD_001",),
                "rendering": ("REND_001", "REND_003"),
                "story": ("STOR_001",),
            }.items()
            for rid in rules
        ]
        report = engine.score(tmp_path, [], _val_report(all_pass), _rca_report(), {})
        assert report.overall_score == 100.0

    def test_empty_input_scores_100(self, tmp_path):
        engine = self._engine()
        report = engine.score(tmp_path, [], _val_report([]), _rca_report(), {})
        assert report.overall_score == 100.0
        assert report.verdict == "PASS"

    def test_critical_failure_lowers_score(self, tmp_path):
        engine = self._engine()
        results = [_vr("REND_003", "rendering", "FAIL", severity="critical")]
        report = engine.score(tmp_path, [], _val_report(results), _rca_report(), {})
        assert report.overall_score < 100.0

    def test_verdict_pass_above_threshold(self, tmp_path):
        engine = self._engine(publish_threshold=70.0)
        report = engine.score(tmp_path, [], _val_report([]), _rca_report(), {})
        assert report.verdict == "PASS"

    def test_verdict_fail_below_threshold(self, tmp_path):
        engine = self._engine(publish_threshold=70.0)
        all_fail = [
            _vr(rid, cat, "FAIL")
            for cat, rules in {
                "rendering": ("REND_001", "REND_002", "REND_003", "REND_004", "REND_005"),
                "audio": ("AUD_001", "AUD_002", "AUD_003"),
                "image": ("IMG_001", "IMG_002", "IMG_003"),
            }.items()
            for rid in rules
        ]
        report = engine.score(tmp_path, [], _val_report(all_fail), _rca_report(), {})
        assert report.verdict == "FAIL"

    def test_letter_grade_assigned(self, tmp_path):
        engine = self._engine()
        report = engine.score(tmp_path, [], _val_report([]), _rca_report(), {})
        assert report.letter_grade in ("A+", "A", "B", "C", "D", "F")

    def test_thresholds_in_report(self, tmp_path):
        engine = self._engine(publish_threshold=75.0, warning_threshold=55.0)
        report = engine.score(tmp_path, [], _val_report([]), _rca_report(), {})
        assert report.publish_threshold == 75.0
        assert report.warning_threshold == 55.0

    def test_processing_time_positive(self, tmp_path):
        engine = self._engine()
        report = engine.score(tmp_path, [], _val_report([]), _rca_report(), {})
        assert report.processing_time_seconds >= 0.0

    def test_project_id_propagated(self, tmp_path):
        engine = self._engine()
        val_report = _val_report([], project_id="my-project")
        report = engine.score(tmp_path, [], val_report, _rca_report("my-project"), {})
        assert report.project_id == "my-project"

    def test_improvement_recommendations_list(self, tmp_path):
        engine = self._engine()
        results = [_vr(rid, cat, "FAIL") for cat, rules in {
            "rendering": ("REND_003",),
            "audio": ("AUD_001",),
        }.items() for rid in rules]
        report = engine.score(tmp_path, [], _val_report(results), _rca_report(), {})
        assert isinstance(report.improvement_recommendations, list)


# ── TestQualityScoringReporter ────────────────────────────────────────────────


@pytest.fixture()
def proj_id(tmp_path, monkeypatch) -> str:
    pid = "score-test-project"
    project_dir = tmp_path / pid
    (project_dir / "review").mkdir(parents=True)
    monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))
    return pid


def _sample_score_report(project_id: str) -> QualityScoreReport:
    cfg = QualityScoringConfig()
    category_scores = {
        cat: _cat_score(cat, raw_score=85.0, weight=w)
        for cat, w in cfg.weights.items()
    }
    for cs in category_scores.values():
        cs.weighted_score = cs.raw_score * cs.weight
    return QualityScoreReport(
        project_id=project_id,
        timestamp=_ts(),
        category_scores=category_scores,
        overall_score=85.0,
        letter_grade="B",
        verdict="PASS",
        publish_threshold=70.0,
        warning_threshold=60.0,
        critical_threshold=50.0,
        improvement_recommendations=["Fix rendering"],
        processing_time_seconds=0.05,
    )


class TestQualityScoringReporter:
    def test_writes_four_files(self, proj_id):
        report = _sample_score_report(proj_id)
        QualityScoringReporter().write(report)
        assert quality_score_path(proj_id).exists()
        assert quality_report_md_path(proj_id).exists()
        assert score_breakdown_path(proj_id).exists()
        assert score_history_path(proj_id).exists()

    def test_quality_score_json_valid(self, proj_id):
        report = _sample_score_report(proj_id)
        QualityScoringReporter().write(report)
        data = json.loads(quality_score_path(proj_id).read_text())
        assert data["version"] == "v1"
        assert data["overall_score"] == 85.0
        assert data["letter_grade"] == "B"
        assert data["verdict"] == "PASS"

    def test_quality_score_not_stub(self, proj_id):
        report = _sample_score_report(proj_id)
        QualityScoringReporter().write(report)
        data = json.loads(quality_score_path(proj_id).read_text())
        assert data.get("status") != "not_implemented"

    def test_score_breakdown_has_categories(self, proj_id):
        report = _sample_score_report(proj_id)
        QualityScoringReporter().write(report)
        data = json.loads(score_breakdown_path(proj_id).read_text())
        assert "categories" in data
        assert "weights" in data
        assert "weight_distribution" in data
        assert "confidence_distribution" in data
        assert "failed_category_summary" in data

    def test_quality_report_md_contains_score(self, proj_id):
        report = _sample_score_report(proj_id)
        QualityScoringReporter().write(report)
        content = quality_report_md_path(proj_id).read_text()
        assert "85.0" in content
        assert "PASS" in content
        assert "Grade" in content

    def test_quality_report_md_contains_recommendations(self, proj_id):
        report = _sample_score_report(proj_id)
        QualityScoringReporter().write(report)
        content = quality_report_md_path(proj_id).read_text()
        assert "Fix rendering" in content

    def test_score_history_first_run(self, proj_id):
        report = _sample_score_report(proj_id)
        QualityScoringReporter().write(report)
        data = json.loads(score_history_path(proj_id).read_text())
        assert data["total_runs"] == 1
        assert len(data["history"]) == 1
        assert data["history"][0]["run_number"] == 1
        assert data["history"][0]["overall_score"] == 85.0

    def test_score_history_accumulates(self, proj_id):
        reporter = QualityScoringReporter()
        r1 = _sample_score_report(proj_id)
        reporter.write(r1)
        r2 = _sample_score_report(proj_id)
        r2.overall_score = 90.0
        r2.letter_grade = "A"
        reporter.write(r2)
        data = json.loads(score_history_path(proj_id).read_text())
        assert data["total_runs"] == 2
        assert data["history"][1]["run_number"] == 2
        assert data["history"][1]["overall_score"] == 90.0

    def test_score_history_corrupt_file_resets(self, proj_id):
        score_history_path(proj_id).write_text("not json", encoding="utf-8")
        report = _sample_score_report(proj_id)
        QualityScoringReporter().write(report)
        data = json.loads(score_history_path(proj_id).read_text())
        assert data["total_runs"] == 1

    def test_returns_review_directory(self, proj_id):
        report = _sample_score_report(proj_id)
        review_dir = QualityScoringReporter().write(report)
        assert review_dir.is_dir()


# ── TestVQREIntegration ───────────────────────────────────────────────────────


@pytest.fixture()
def vqre_proj(tmp_path, monkeypatch):
    """Full VQRE project fixture with all required assets."""
    import json as _json
    pid = "vqre-scoring-proj"
    project_dir = tmp_path / pid
    for subdir in ("script", "scenes", "images", "audio", "subtitles", "video", "review"):
        (project_dir / subdir).mkdir(parents=True)

    words = " ".join(["word"] * 210)
    (project_dir / "script" / "script.md").write_text(
        f"# Title\n\n{words}\n\nThis is a test script.",
        encoding="utf-8",
    )

    scenes = [
        {
            "index": i, "title": f"Scene {i}", "scene_type": "generated_image",
            "narration": f"Narration for scene {i} with enough words to pass the checks here.",
            "visual_prompt": f"Visual prompt {i} with style: cinematic, wide shot, sunset.",
            "duration_seconds": 8.0, "shot_type": "wide_shot", "transition": "fade",
        }
        for i in range(1, 4)
    ]
    (project_dir / "scenes" / "scene-plan.json").write_text(
        _json.dumps({"scenes": scenes}), encoding="utf-8"
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
    def test_quality_score_report_in_review_report(self, vqre_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine
        report = VideoQualityReviewEngine().review(vqre_proj)
        assert report.quality_score_report is not None
        assert report.quality_score_report["version"] == "v1"

    def test_quality_score_float_set(self, vqre_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine
        report = VideoQualityReviewEngine().review(vqre_proj)
        assert report.quality_score is not None
        assert 0.0 <= report.quality_score <= 100.0

    def test_four_scoring_files_written(self, vqre_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine
        VideoQualityReviewEngine().review(vqre_proj)
        review_dir = tmp_path / vqre_proj / "review"
        assert (review_dir / "quality-score.json").exists()
        assert (review_dir / "quality-report.md").exists()
        assert (review_dir / "score-breakdown.json").exists()
        assert (review_dir / "score-history.json").exists()

    def test_quality_score_json_not_stub(self, vqre_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine
        VideoQualityReviewEngine().review(vqre_proj)
        data = json.loads(
            (tmp_path / vqre_proj / "review" / "quality-score.json").read_text()
        )
        assert data.get("status") != "not_implemented"
        assert "overall_score" in data

    def test_all_8_categories_scored(self, vqre_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine
        report = VideoQualityReviewEngine().review(vqre_proj)
        scores = report.quality_score_report["category_scores"]
        for cat in ("script", "narration", "subtitle", "image",
                    "motion", "audio", "rendering", "storytelling"):
            assert cat in scores

    def test_score_history_written_on_each_run(self, vqre_proj, tmp_path):
        from ytfactory.review.engine import VideoQualityReviewEngine
        engine = VideoQualityReviewEngine()
        engine.review(vqre_proj)
        engine.review(vqre_proj)
        data = json.loads(
            (tmp_path / vqre_proj / "review" / "score-history.json").read_text()
        )
        assert data["total_runs"] == 2

    def test_scoring_config_passable(self, vqre_proj):
        from ytfactory.review.engine import VideoQualityReviewEngine
        from ytfactory.review.scoring.config import QualityScoringConfig
        engine = VideoQualityReviewEngine(
            scoring_config=QualityScoringConfig(publish_threshold=50.0)
        )
        report = engine.review(vqre_proj)
        assert report.quality_score_report["publish_threshold"] == 50.0
