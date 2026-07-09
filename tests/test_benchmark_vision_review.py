"""Unit tests for the vision review benchmark framework."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.benchmark.dataset import BenchmarkDataset
from ytfactory.benchmark.engine import BenchmarkEngine, _qa_scores, _scene_index
from ytfactory.benchmark.hard_fails import RULE_MATCHERS, HardFailMatcher, detect_hard_fails
from ytfactory.benchmark.models import (
    BenchmarkReport,
    BenchmarkScene,
    HardFailMatch,
    ModelMetrics,
    SceneResult,
)
from ytfactory.benchmark.reporter import BenchmarkReporter
from ytfactory.providers.vision.models import IssueSeverity, VisionIssue


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_image(tmp_path: Path, name: str = "scene-001.png") -> Path:
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 512)
    return p


def _make_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "benchmark.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def _result(
    scene: str = "scene-001",
    model: str = "qwen2_5_vl_3b",
    recommendation: str = "PASS",
    expected_failures: list[str] | None = None,
    detected_failures: list[str] | None = None,
    latency_ms: float = 500.0,
    narrative: float = 95.0,
    technical: float = 95.0,
    cinematic: float = 95.0,
    overall: float = 95.0,
) -> SceneResult:
    return SceneResult(
        scene=scene,
        model=model,
        narrative_score=narrative,
        technical_score=technical,
        cinematic_score=cinematic,
        overall_score=overall,
        recommendation=recommendation,
        hard_fail=recommendation == "REGENERATE",
        detected_failures=detected_failures or [],
        expected_failures=expected_failures or [],
        hard_fail_matches=[],
        latency_ms=latency_ms,
        confidence=85.0,
    )


# ── Dataset loading ───────────────────────────────────────────────────────────


class TestBenchmarkDatasetLoading:
    def test_loads_bad_and_good_scenes(self, tmp_path: Path) -> None:
        img_bad = _make_image(tmp_path, "bad.png")
        img_good = _make_image(tmp_path, "good.png")
        yaml_path = _make_yaml(
            tmp_path,
            f"""
scenes:
  - id: scene-bad
    image: bad.png
    expected_failures:
      - hands_invalid
    visual_prompt: "test prompt"
    notes: "bad scene"
  - id: scene-good
    image: good.png
    expected_failures: []
    visual_prompt: "another prompt"
""",
        )
        ds = BenchmarkDataset.load(yaml_path)
        assert len(ds.scenes) == 2
        assert len(ds.bad_scenes) == 1
        assert len(ds.good_scenes) == 1
        assert ds.bad_scenes[0].id == "scene-bad"
        assert ds.bad_scenes[0].expected_failures == ["hands_invalid"]
        assert ds.good_scenes[0].id == "scene-good"

    def test_scene_image_path_is_absolute(self, tmp_path: Path) -> None:
        _make_image(tmp_path, "img.png")
        yaml_path = _make_yaml(
            tmp_path,
            """
scenes:
  - id: s1
    image: img.png
    expected_failures: []
""",
        )
        ds = BenchmarkDataset.load(yaml_path)
        assert ds.scenes[0].image.is_absolute()

    def test_missing_yaml_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            BenchmarkDataset.load(tmp_path / "nonexistent.yaml")

    def test_empty_expected_failures_is_good_scene(self, tmp_path: Path) -> None:
        _make_image(tmp_path, "img.png")
        yaml_path = _make_yaml(
            tmp_path,
            """
scenes:
  - id: s1
    image: img.png
    expected_failures: []
""",
        )
        ds = BenchmarkDataset.load(yaml_path)
        assert not ds.scenes[0].is_bad

    def test_visual_prompt_defaults_to_empty(self, tmp_path: Path) -> None:
        _make_image(tmp_path, "img.png")
        yaml_path = _make_yaml(
            tmp_path,
            """
scenes:
  - id: s1
    image: img.png
    expected_failures: []
""",
        )
        ds = BenchmarkDataset.load(yaml_path)
        assert ds.scenes[0].visual_prompt == ""


# ── Hard fail detection ───────────────────────────────────────────────────────


class TestHardFailDetection:
    def _issues(self, *specs: tuple[str, str, IssueSeverity]) -> list[VisionIssue]:
        return [VisionIssue(category=c, description=d, severity=s) for c, d, s in specs]

    def test_hands_invalid_fires_on_anatomy_hand(self) -> None:
        issues = self._issues(("anatomy", "badly formed hand with extra finger", IssueSeverity.HIGH))
        detected, _ = detect_hard_fails(issues, ["hands_invalid"])
        assert "hands_invalid" in detected

    def test_finger_count_fires_on_fused_finger(self) -> None:
        issues = self._issues(("anatomy", "merged finger joints unclear", IssueSeverity.HIGH))
        detected, _ = detect_hard_fails(issues, ["finger_count_invalid"])
        assert "finger_count_invalid" in detected

    def test_impossible_walk_fires_on_gait(self) -> None:
        issues = self._issues(
            ("anatomy", "impossible walking gait, both feet on ground", IssueSeverity.HIGH)
        )
        detected, _ = detect_hard_fails(issues, ["impossible_walk_cycle"])
        assert "impossible_walk_cycle" in detected

    def test_face_distorted_fires_on_face_category_high(self) -> None:
        issues = self._issues(("face", "distorted jaw and asymmetric eyes", IssueSeverity.HIGH))
        detected, _ = detect_hard_fails(issues, ["face_distorted"])
        assert "face_distorted" in detected

    def test_content_mismatch_fires_on_wrong_subject(self) -> None:
        issues = self._issues(("environment", "wrong scene content, different from expected", IssueSeverity.HIGH))
        detected, _ = detect_hard_fails(issues, ["content_mismatch"])
        assert "content_mismatch" in detected

    def test_below_min_severity_does_not_fire(self) -> None:
        # impossible_walk_cycle requires HIGH; LOW should not trigger
        issues = self._issues(("anatomy", "walk gait slightly off", IssueSeverity.LOW))
        detected, _ = detect_hard_fails(issues, ["impossible_walk_cycle"])
        assert "impossible_walk_cycle" not in detected

    def test_no_issues_detects_nothing(self) -> None:
        detected, _ = detect_hard_fails([], ["hands_invalid"])
        assert detected == []

    def test_tp_fn_classification(self) -> None:
        # Expected rule fires → TP; expected rule doesn't fire → FN
        issues = self._issues(("anatomy", "bad hand", IssueSeverity.HIGH))
        detected, matches = detect_hard_fails(issues, ["hands_invalid", "face_distorted"])
        match_map = {m.rule: m for m in matches}
        assert match_map["hands_invalid"].is_tp
        assert match_map["face_distorted"].is_fn

    def test_fp_when_model_fires_unexpected_rule(self) -> None:
        # Model fires for hands_invalid but scene has no expected failures
        issues = self._issues(("anatomy", "extra finger on hand", IssueSeverity.HIGH))
        detected, matches = detect_hard_fails(issues, [])
        fp_matches = [m for m in matches if m.is_fp]
        assert any(m.rule == "hands_invalid" for m in fp_matches)

    def test_unknown_expected_rule_becomes_fn(self) -> None:
        _, matches = detect_hard_fails([], ["unknown_future_rule"])
        fn_matches = [m for m in matches if m.rule == "unknown_future_rule"]
        assert len(fn_matches) == 1
        assert fn_matches[0].is_fn

    def test_all_rule_matchers_are_callable(self) -> None:
        for name, matcher in RULE_MATCHERS.items():
            assert isinstance(matcher, HardFailMatcher), f"Bad matcher for {name}"
            result = matcher.matches([])
            assert result is False  # no issues → never fires


# ── QA sub-score derivation ───────────────────────────────────────────────────


class TestQAScoreDerivation:
    def test_no_issues_returns_100_for_all(self) -> None:
        n, t, c = _qa_scores([])
        assert n == 100.0
        assert t == 100.0
        assert c == 100.0

    def test_anatomy_issue_reduces_technical(self) -> None:
        issues = [{"category": "anatomy", "severity": "HIGH", "description": "bad hands"}]
        n, t, c = _qa_scores(issues)
        assert t < 100.0
        assert n == 100.0  # narrative unchanged
        assert c == 100.0  # cinematic unchanged

    def test_lighting_issue_reduces_cinematic(self) -> None:
        issues = [{"category": "lighting", "severity": "MEDIUM", "description": "bad shadows"}]
        n, t, c = _qa_scores(issues)
        assert c < 100.0
        assert t == 100.0

    def test_environment_issue_reduces_narrative(self) -> None:
        issues = [{"category": "environment", "severity": "HIGH", "description": "wrong content"}]
        n, t, c = _qa_scores(issues)
        assert n < 100.0

    def test_score_floor_at_zero(self) -> None:
        # 4 CRITICAL anatomy issues → technical deducted 4×50 = 200 → floor at 0
        issues = [
            {"category": "anatomy", "severity": "CRITICAL", "description": f"issue {i}"}
            for i in range(4)
        ]
        n, t, c = _qa_scores(issues)
        assert t == 0.0

    def test_unknown_severity_treated_as_medium(self) -> None:
        issues = [{"category": "anatomy", "severity": "UNKNOWN", "description": "test"}]
        n, t, c = _qa_scores(issues)
        assert t == 85.0  # 100 - 15 (MEDIUM default)

    def test_face_reduces_technical(self) -> None:
        issues = [{"category": "face", "severity": "HIGH", "description": "distorted"}]
        _, t, _ = _qa_scores(issues)
        assert t < 100.0

    def test_cinematic_category_reduces_cinematic(self) -> None:
        issues = [{"category": "cinematic", "severity": "LOW", "description": "poor framing"}]
        _, _, c = _qa_scores(issues)
        assert c == 95.0  # 100 - 5


# ── Scene index extraction ─────────────────────────────────────────────────────


class TestSceneIndex:
    def test_scene_002(self) -> None:
        assert _scene_index("scene-002") == 2

    def test_scene_037(self) -> None:
        assert _scene_index("scene-037") == 37

    def test_no_number_returns_1(self) -> None:
        assert _scene_index("my-scene") == 1

    def test_multi_segment(self) -> None:
        assert _scene_index("project-abc-scene-015") == 15


# ── Metrics aggregation ───────────────────────────────────────────────────────


class TestModelMetrics:
    def test_precision_recall_f1(self) -> None:
        m = ModelMetrics(model="test", tp=3, fp=1, tn=2, fn=2, scene_count=8)
        assert m.precision == pytest.approx(0.75)
        assert m.recall == pytest.approx(0.6)
        assert m.f1 == pytest.approx(2 * 0.75 * 0.6 / (0.75 + 0.6))

    def test_accuracy(self) -> None:
        m = ModelMetrics(model="test", tp=3, fp=1, tn=3, fn=1, scene_count=8)
        assert m.accuracy == pytest.approx(6 / 8)

    def test_zero_denominators_return_zero(self) -> None:
        m = ModelMetrics(model="test")
        assert m.precision == 0.0
        assert m.recall == 0.0
        assert m.f1 == 0.0
        assert m.accuracy == 0.0

    def test_avg_scores(self) -> None:
        m = ModelMetrics(
            model="test",
            scene_count=2,
            total_latency_ms=1000.0,
            total_narrative=180.0,
            total_technical=160.0,
            total_cinematic=190.0,
        )
        assert m.avg_latency_ms == pytest.approx(500.0)
        assert m.avg_narrative == pytest.approx(90.0)
        assert m.avg_technical == pytest.approx(80.0)
        assert m.avg_cinematic == pytest.approx(95.0)


# ── SceneResult serialisation ─────────────────────────────────────────────────


class TestSceneResultSerialization:
    def test_to_dict_has_all_keys(self) -> None:
        r = _result()
        d = r.to_dict()
        for key in (
            "scene", "model", "narrative_score", "technical_score",
            "cinematic_score", "overall_score", "recommendation",
            "hard_fail", "detected_failures", "expected_failures",
            "latency_ms", "confidence", "issues", "error",
        ):
            assert key in d, f"Missing key: {key}"

    def test_hard_fail_true_when_regenerate(self) -> None:
        r = _result(recommendation="REGENERATE", expected_failures=["hands_invalid"])
        assert r.hard_fail is True
        assert r.to_dict()["hard_fail"] is True

    def test_hard_fail_false_when_pass(self) -> None:
        r = _result(recommendation="PASS")
        assert r.hard_fail is False


# ── BenchmarkEngine (mocked ImageReviewEngine) ────────────────────────────────


class TestBenchmarkEngine:
    def _make_scenes(self, tmp_path: Path) -> list[BenchmarkScene]:
        img = _make_image(tmp_path)
        return [
            BenchmarkScene(
                id="scene-001",
                image=img,
                expected_failures=["hands_invalid"],
                visual_prompt="test",
            ),
            BenchmarkScene(
                id="scene-002",
                image=img,
                expected_failures=[],
                visual_prompt="test good",
            ),
        ]

    def test_run_produces_report(self, tmp_path: Path) -> None:
        from ytfactory.benchmark.dataset import BenchmarkDataset

        scenes = self._make_scenes(tmp_path)
        ds = BenchmarkDataset(path=tmp_path / "benchmark.yaml", scenes=scenes)
        out = tmp_path / "results"

        engine = BenchmarkEngine(base_dir=tmp_path)

        # Patch vision provider + ImageReviewEngine to avoid real model calls
        mock_artifact = MagicMock()
        mock_artifact.status = "FAIL"
        mock_artifact.score = 40.0
        mock_artifact.confidence = 75.0
        mock_artifact.recommend_regeneration = True
        mock_artifact.issues = [
            {"category": "anatomy", "description": "bad hand finger", "severity": "HIGH"}
        ]
        mock_artifact.error = ""

        with (
            patch("ytfactory.benchmark.engine.get_vision_provider") as mock_prov,
            patch("ytfactory.benchmark.engine.ImageReviewEngine") as mock_engine_cls,
        ):
            mock_prov.return_value = MagicMock()
            mock_re = MagicMock()
            mock_re.review_scene.return_value = mock_artifact
            mock_engine_cls.return_value = mock_re

            report = engine.run(ds, ["qwen2_5_vl_3b"], out)

        assert report.total_scenes == 2
        assert report.bad_scenes == 1
        assert report.good_scenes == 1
        assert "qwen2_5_vl_3b" in report.metrics
        assert "qwen2_5_vl_3b" in report.scene_results

    def test_missing_image_yields_error_result(self, tmp_path: Path) -> None:
        from ytfactory.benchmark.dataset import BenchmarkDataset

        scenes = [
            BenchmarkScene(
                id="scene-missing",
                image=tmp_path / "nonexistent.png",
                expected_failures=["hands_invalid"],
            )
        ]
        ds = BenchmarkDataset(path=tmp_path / "benchmark.yaml", scenes=scenes)

        with patch("ytfactory.benchmark.engine.get_vision_provider") as mock_prov:
            mock_prov.return_value = MagicMock()
            engine = BenchmarkEngine(base_dir=tmp_path)
            report = engine.run(ds, ["qwen2_5_vl_3b"], tmp_path / "results")

        result = report.scene_results["qwen2_5_vl_3b"][0]
        assert result.recommendation == "ERROR"
        assert result.error != ""

    def test_provider_init_failure_yields_error_results(self, tmp_path: Path) -> None:
        from ytfactory.benchmark.dataset import BenchmarkDataset

        img = _make_image(tmp_path)
        scenes = [BenchmarkScene(id="s1", image=img, expected_failures=[])]
        ds = BenchmarkDataset(path=tmp_path / "benchmark.yaml", scenes=scenes)

        with patch(
            "ytfactory.benchmark.engine.get_vision_provider",
            side_effect=RuntimeError("no model"),
        ):
            engine = BenchmarkEngine(base_dir=tmp_path)
            report = engine.run(ds, ["bad_model"], tmp_path / "out")

        result = report.scene_results["bad_model"][0]
        assert result.recommendation == "ERROR"

    def test_tp_fn_metrics_computed_correctly(self, tmp_path: Path) -> None:
        from ytfactory.benchmark.dataset import BenchmarkDataset

        img = _make_image(tmp_path)
        # bad scene — will be predicted REGENERATE → TP
        bad = BenchmarkScene(id="scene-bad", image=img, expected_failures=["hands_invalid"])
        # good scene — will be predicted PASS → TN
        good = BenchmarkScene(id="scene-good", image=img, expected_failures=[])
        ds = BenchmarkDataset(path=tmp_path / "benchmark.yaml", scenes=[bad, good])
        out = tmp_path / "results"

        fail_artifact = MagicMock(
            status="FAIL", score=30.0, confidence=70.0,
            recommend_regeneration=True, issues=[], error=""
        )
        pass_artifact = MagicMock(
            status="PASS", score=95.0, confidence=90.0,
            recommend_regeneration=False, issues=[], error=""
        )

        call_count = 0

        def alternating_review(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return fail_artifact if call_count == 1 else pass_artifact

        with (
            patch("ytfactory.benchmark.engine.get_vision_provider"),
            patch("ytfactory.benchmark.engine.ImageReviewEngine") as mock_cls,
        ):
            mock_re = MagicMock()
            mock_re.review_scene.side_effect = alternating_review
            mock_cls.return_value = mock_re
            engine = BenchmarkEngine(base_dir=tmp_path)
            report = engine.run(ds, ["qwen2_5_vl_3b"], out)

        m = report.metrics["qwen2_5_vl_3b"]
        assert m.tp == 1
        assert m.tn == 1
        assert m.fp == 0
        assert m.fn == 0
        assert m.accuracy == pytest.approx(1.0)

    def test_json_files_written_per_scene(self, tmp_path: Path) -> None:
        from ytfactory.benchmark.dataset import BenchmarkDataset

        img = _make_image(tmp_path)
        scenes = [BenchmarkScene(id="scene-001", image=img, expected_failures=[])]
        ds = BenchmarkDataset(path=tmp_path / "benchmark.yaml", scenes=scenes)
        out = tmp_path / "results"

        artifact = MagicMock(
            status="PASS", score=95.0, confidence=85.0,
            recommend_regeneration=False, issues=[], error=""
        )

        with (
            patch("ytfactory.benchmark.engine.get_vision_provider"),
            patch("ytfactory.benchmark.engine.ImageReviewEngine") as mock_cls,
        ):
            mock_cls.return_value.review_scene.return_value = artifact
            BenchmarkEngine(base_dir=tmp_path).run(ds, ["qwen2_5_vl_3b"], out)

        json_path = out / "qwen2_5_vl_3b" / "scene-001.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert data["scene"] == "scene-001"
        assert data["model"] == "qwen2_5_vl_3b"


# ── Markdown report generation ────────────────────────────────────────────────


class TestBenchmarkReporter:
    def _make_report(self) -> BenchmarkReport:
        r1 = _result("scene-001", "model_a", "REGENERATE", ["hands_invalid"], ["hands_invalid"], 500)
        r2 = _result("scene-002", "model_a", "PASS", [], [], 400)
        m_a = ModelMetrics(
            model="model_a", tp=1, fp=0, tn=1, fn=0,
            scene_count=2, total_latency_ms=900,
            total_narrative=190, total_technical=170, total_cinematic=185,
        )
        return BenchmarkReport(
            dataset_path="/tmp/benchmark.yaml",
            total_scenes=2,
            bad_scenes=1,
            good_scenes=1,
            models=["model_a"],
            scene_results={"model_a": [r1, r2]},
            metrics={"model_a": m_a},
            winner=None,
        )

    def test_writes_markdown_file(self, tmp_path: Path) -> None:
        report = self._make_report()
        reporter = BenchmarkReporter()
        md_path = reporter.write(report, tmp_path)
        assert md_path.exists()
        assert md_path.name == "report.md"
        content = md_path.read_text()
        assert "Vision Review Benchmark" in content
        assert "model_a" in content.lower() or "Model A" in content

    def test_writes_json_summary(self, tmp_path: Path) -> None:
        report = self._make_report()
        BenchmarkReporter().write(report, tmp_path)
        json_path = tmp_path / "report-summary.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert "metrics" in data
        assert "model_a" in data["metrics"]

    def test_markdown_contains_per_scene_rows(self, tmp_path: Path) -> None:
        report = self._make_report()
        BenchmarkReporter().write(report, tmp_path)
        content = (tmp_path / "report.md").read_text()
        assert "scene-001" in content
        assert "scene-002" in content

    def test_markdown_contains_precision_recall(self, tmp_path: Path) -> None:
        report = self._make_report()
        BenchmarkReporter().write(report, tmp_path)
        content = (tmp_path / "report.md").read_text()
        assert "Precision" in content
        assert "Recall" in content
        assert "F1" in content

    def test_winner_in_markdown_when_two_models(self, tmp_path: Path) -> None:
        r_a = _result("s1", "model_a", "REGENERATE", ["hands_invalid"])
        r_b = _result("s1", "model_b", "PASS", ["hands_invalid"])
        m_a = ModelMetrics(model="model_a", tp=1, fp=0, tn=0, fn=0, scene_count=1)
        m_b = ModelMetrics(model="model_b", tp=0, fp=0, tn=0, fn=1, scene_count=1)
        report = BenchmarkReport(
            dataset_path="/tmp/b.yaml",
            total_scenes=1,
            bad_scenes=1,
            good_scenes=0,
            models=["model_a", "model_b"],
            scene_results={"model_a": [r_a], "model_b": [r_b]},
            metrics={"model_a": m_a, "model_b": m_b},
            winner="model_a",
        )
        BenchmarkReporter().write(report, tmp_path)
        content = (tmp_path / "report.md").read_text()
        assert "Winner" in content
        assert "Model A" in content  # _display_name("model_a") → "Model A"

    def test_comparison_table_shows_detected_vs_missed(self, tmp_path: Path) -> None:
        r_a = _result("scene-bad", "model_a", "REGENERATE", ["hands_invalid"], ["hands_invalid"])
        r_b = _result("scene-bad", "model_b", "PASS", ["hands_invalid"], [])
        m_a = ModelMetrics(model="model_a", tp=1, scene_count=1)
        m_b = ModelMetrics(model="model_b", fn=1, scene_count=1)
        report = BenchmarkReport(
            dataset_path="/tmp/b.yaml",
            total_scenes=1,
            bad_scenes=1,
            good_scenes=0,
            models=["model_a", "model_b"],
            scene_results={"model_a": [r_a], "model_b": [r_b]},
            metrics={"model_a": m_a, "model_b": m_b},
            winner="model_a",
        )
        BenchmarkReporter().write(report, tmp_path)
        content = (tmp_path / "report.md").read_text()
        assert "detected" in content
        assert "missed" in content


# ── Resolve installed models ───────────────────────────────────────────────────


class TestResolveInstalledModels:
    def test_returns_list(self) -> None:
        from ytfactory.benchmark.engine import resolve_installed_vision_models

        result = resolve_installed_vision_models()
        assert isinstance(result, list)

    def test_qwen_present_when_enabled(self) -> None:
        from ytfactory.benchmark.engine import resolve_installed_vision_models

        models = resolve_installed_vision_models()
        # qwen2_5_vl_3b has image_review capability and is enabled
        assert "qwen2_5_vl_3b" in models


# ── BenchmarkScore property ───────────────────────────────────────────────────


class TestBenchmarkScore:
    def test_perfect_score_equals_100(self) -> None:
        m = ModelMetrics(
            model="test", tp=4, fp=0, tn=4, fn=0, scene_count=8,
            total_technical=800.0, total_narrative=800.0, total_cinematic=800.0,
        )
        # f1=1.0 → 60; avg_t/n/c = 100 → 20+10+10 = 40
        assert m.benchmark_score == pytest.approx(100.0)

    def test_zero_f1_still_scores_qa(self) -> None:
        m = ModelMetrics(
            model="test", tp=0, fp=0, tn=4, fn=4, scene_count=8,
            total_technical=800.0, total_narrative=800.0, total_cinematic=800.0,
        )
        # f1=0.0 → 0; avg=100 → 40
        assert m.benchmark_score == pytest.approx(40.0)

    def test_partial_f1_and_partial_qa(self) -> None:
        m = ModelMetrics(
            model="test", tp=2, fp=2, fn=2, tn=2, scene_count=8,
            total_technical=640.0,   # avg = 80
            total_narrative=720.0,   # avg = 90
            total_cinematic=760.0,   # avg = 95
        )
        # precision=0.5, recall=0.5, f1=0.5
        expected = round(0.5 * 60.0 + 80 * 0.20 + 90 * 0.10 + 95 * 0.10, 1)
        assert m.benchmark_score == pytest.approx(expected)

    def test_score_does_not_exceed_100(self) -> None:
        m = ModelMetrics(
            model="test", tp=4, fp=0, tn=4, fn=0, scene_count=4,
            total_technical=400.0, total_narrative=400.0, total_cinematic=400.0,
        )
        assert m.benchmark_score <= 100.0


# ── Scene winner determination ────────────────────────────────────────────────


class TestSceneWinner:
    def test_correct_model_wins_over_wrong(self) -> None:
        from ytfactory.benchmark.reporter import _scene_winner

        r_a = _result("s1", "model_a", "REGENERATE", expected_failures=["hands_invalid"])
        r_b = _result("s1", "model_b", "PASS", expected_failures=["hands_invalid"])
        winner, reason = _scene_winner({"model_a": r_a, "model_b": r_b}, ["model_a", "model_b"])
        assert winner == "model_a"
        assert len(reason) > 0

    def test_both_wrong_is_tie(self) -> None:
        from ytfactory.benchmark.reporter import _scene_winner

        r_a = _result("s1", "model_a", "PASS", expected_failures=["hands_invalid"])
        r_b = _result("s1", "model_b", "PASS", expected_failures=["hands_invalid"])
        winner, _ = _scene_winner({"model_a": r_a, "model_b": r_b}, ["model_a", "model_b"])
        assert winner is None

    def test_both_correct_winner_by_technical(self) -> None:
        from ytfactory.benchmark.reporter import _scene_winner

        r_a = _result("s1", "model_a", "REGENERATE", expected_failures=["hands_invalid"], technical=90.0)
        r_b = _result("s1", "model_b", "REGENERATE", expected_failures=["hands_invalid"], technical=80.0)
        winner, reason = _scene_winner({"model_a": r_a, "model_b": r_b}, ["model_a", "model_b"])
        assert winner == "model_a"
        assert "Technical" in reason

    def test_tie_when_both_correct_equal_quality(self) -> None:
        from ytfactory.benchmark.reporter import _scene_winner

        # Both correctly PASS a good scene with identical scores (95, 95, 95)
        r_a = _result("s1", "model_a", "PASS", expected_failures=[])
        r_b = _result("s1", "model_b", "PASS", expected_failures=[])
        winner, reason = _scene_winner({"model_a": r_a, "model_b": r_b}, ["model_a", "model_b"])
        assert winner is None
        assert "equal" in reason.lower()

    def test_false_positive_loses_to_correct_pass(self) -> None:
        from ytfactory.benchmark.reporter import _scene_winner

        # Good scene: model_a correctly PASS; model_b false-alarm REGENERATE
        r_a = _result("s1", "model_a", "PASS", expected_failures=[])
        r_b = _result("s1", "model_b", "REGENERATE", expected_failures=[])
        winner, reason = _scene_winner({"model_a": r_a, "model_b": r_b}, ["model_a", "model_b"])
        assert winner == "model_a"
        assert "false alarm" in reason.lower()


# ── Visual comparison report ──────────────────────────────────────────────────


class TestVisualComparisonReport:
    def _make_report(self) -> BenchmarkReport:
        r_a = _result("scene-024", "model_a", "PASS", expected_failures=["hands_invalid"])
        r_b = _result(
            "scene-024", "model_b", "REGENERATE",
            expected_failures=["hands_invalid"],
            detected_failures=["finger_count_invalid"],
        )
        m_a = ModelMetrics(model="model_a", fn=1, scene_count=1)
        m_b = ModelMetrics(model="model_b", tp=1, scene_count=1)
        return BenchmarkReport(
            dataset_path="/tmp/benchmark.yaml",
            total_scenes=1, bad_scenes=1, good_scenes=0,
            models=["model_a", "model_b"],
            scene_results={"model_a": [r_a], "model_b": [r_b]},
            metrics={"model_a": m_a, "model_b": m_b},
            winner="model_b",
        )

    def test_comparison_file_written(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        assert (tmp_path / "comparison.md").exists()

    def test_comparison_contains_scene_id(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        assert "scene-024" in (tmp_path / "comparison.md").read_text()

    def test_comparison_shows_expected_regenerate(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        content = (tmp_path / "comparison.md").read_text()
        assert "REGENERATE" in content
        assert "Expected Result" in content

    def test_comparison_shows_false_negative(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        assert "FALSE NEGATIVE" in (tmp_path / "comparison.md").read_text()

    def test_comparison_shows_true_positive(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        assert "TRUE POSITIVE" in (tmp_path / "comparison.md").read_text()

    def test_comparison_shows_winner(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        content = (tmp_path / "comparison.md").read_text()
        assert "Winner" in content
        assert "🏆" in content

    def test_write_comparison_standalone_returns_path(self, tmp_path: Path) -> None:
        path = BenchmarkReporter().write_comparison(self._make_report(), tmp_path)
        assert path.name == "comparison.md"
        assert path.exists()


# ── Visual gallery report ─────────────────────────────────────────────────────


class TestGalleryReport:
    def _make_report(self) -> BenchmarkReport:
        r_a = _result(
            "scene-001", "model_a", "REGENERATE",
            expected_failures=["hands_invalid"], detected_failures=["hands_invalid"],
            technical=90.0,
        )
        r_b = _result("scene-001", "model_b", "PASS", expected_failures=["hands_invalid"], technical=80.0)
        m_a = ModelMetrics(
            model="model_a", tp=1, fp=0, tn=0, fn=0, scene_count=1,
            total_technical=90.0, total_narrative=95.0, total_cinematic=92.0,
        )
        m_b = ModelMetrics(
            model="model_b", tp=0, fp=0, tn=0, fn=1, scene_count=1,
            total_technical=80.0, total_narrative=90.0, total_cinematic=88.0,
        )
        return BenchmarkReport(
            dataset_path="/tmp/benchmark.yaml",
            total_scenes=1, bad_scenes=1, good_scenes=0,
            models=["model_a", "model_b"],
            scene_results={"model_a": [r_a], "model_b": [r_b]},
            metrics={"model_a": m_a, "model_b": m_b},
            winner="model_a",
        )

    def test_gallery_file_written(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        assert (tmp_path / "gallery.md").exists()

    def test_gallery_contains_image_embed(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        content = (tmp_path / "gallery.md").read_text()
        assert "![scene-001]" in content
        assert "scene-001.png" in content

    def test_gallery_contains_leaderboard(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        assert "Leaderboard" in (tmp_path / "gallery.md").read_text()

    def test_gallery_leaderboard_has_gold_medal(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        assert "🥇" in (tmp_path / "gallery.md").read_text()

    def test_gallery_shows_benchmark_winner(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        content = (tmp_path / "gallery.md").read_text()
        assert "Benchmark Winner" in content
        assert "🏆" in content

    def test_gallery_tp_fp_fn_counts(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        content = (tmp_path / "gallery.md").read_text()
        assert "True Positives" in content
        assert "False Positives" in content
        assert "False Negatives" in content

    def test_write_gallery_standalone_returns_path(self, tmp_path: Path) -> None:
        path = BenchmarkReporter().write_gallery(self._make_report(), tmp_path)
        assert path.name == "gallery.md"
        assert path.exists()

    def test_json_summary_contains_benchmark_score(self, tmp_path: Path) -> None:
        BenchmarkReporter().write(self._make_report(), tmp_path)
        data = json.loads((tmp_path / "report-summary.json").read_text())
        for model in ["model_a", "model_b"]:
            assert "benchmark_score" in data["metrics"][model]
