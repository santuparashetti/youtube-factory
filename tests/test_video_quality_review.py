"""Tests for Video Quality Review Engine V1.

Covers:
  - Unit tests for each stage (asset_integrity, timeline, content, production)
  - Unit tests for engine orchestration
  - Unit tests for reporter (file output)
  - Integration tests: engine works against a real project-like directory
  - Backward compatibility: existing pipeline unaffected when review dir absent
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ytfactory.review.config import ReviewConfig
from ytfactory.review.engine import VideoQualityReviewEngine, _load_scenes
from ytfactory.review.models import ReviewReport, SceneReview, StageResult
from ytfactory.review.reporter import ReviewReporter
from ytfactory.review.stages.asset_integrity import AssetIntegrityStage
from ytfactory.review.stages.base import BaseReviewStage
from ytfactory.review.stages.content import ContentReviewStage
from ytfactory.review.stages.production import ProductionQualityStage
from ytfactory.review.stages.timeline import TimelineReviewStage, _validate_srt


# ── Fixtures & helpers ────────────────────────────────────────────────────────


def _cfg(**kw) -> ReviewConfig:
    return ReviewConfig(**kw)


def _make_scene(index: int, **overrides) -> dict:
    scene = {
        "index": index,
        "title": f"Scene {index}",
        "narration": f"This is narration text for scene {index} with enough words.",
        "visual_prompt": f"Photorealistic cinematic establishing shot of scene {index}, no text, no watermark.",
        "duration_seconds": 10.0,
        "scene_type": "generated_image",
    }
    scene.update(overrides)
    return scene


def _make_scene_review(index: int, **overrides) -> SceneReview:
    sr = SceneReview(index=index)
    for k, v in overrides.items():
        setattr(sr, k, v)
    return sr


def _build_project(
    tmp_path: Path, scenes: list[dict], with_assets: bool = True
) -> Path:
    """Create a minimal project directory tree for testing."""
    proj = tmp_path / "test-project"

    # scene-plan.json
    scenes_dir = proj / "scenes"
    scenes_dir.mkdir(parents=True)
    (scenes_dir / "scene-plan.json").write_text(
        json.dumps({"scenes": scenes}), encoding="utf-8"
    )

    # script
    script_dir = proj / "script"
    script_dir.mkdir()
    (script_dir / "script.md").write_text(
        "# Test Script\n\nThis is the script.", encoding="utf-8"
    )

    if with_assets:
        for scene in scenes:
            idx = scene["index"]

            # images
            img_dir = proj / "images"
            img_dir.mkdir(exist_ok=True)
            (img_dir / f"scene-{idx:03d}.png").write_bytes(b"\x89PNG" + b"\x00" * 2000)

            # audio
            aud_dir = proj / "audio"
            aud_dir.mkdir(exist_ok=True)
            (aud_dir / f"scene-{idx:03d}.mp3").write_bytes(b"ID3" + b"\x00" * 2000)

            # subtitles (SRT)
            sub_dir = proj / "subtitles"
            sub_dir.mkdir(exist_ok=True)
            srt_content = (
                f"1\n00:00:00,000 --> 00:00:05,000\nNarration text for scene {idx}.\n\n"
            )
            (sub_dir / f"scene-{idx:03d}.srt").write_text(srt_content, encoding="utf-8")

            # video clips
            vid_dir = proj / "video"
            vid_dir.mkdir(exist_ok=True)
            (vid_dir / f"scene-{idx:03d}.mp4").write_bytes(b"\x00" * 15_000)

        # final.mp4
        vid_dir = proj / "video"
        vid_dir.mkdir(exist_ok=True)
        (vid_dir / "final.mp4").write_bytes(b"\x00" * 200_000)

    return proj


# ── TestReviewConfig ──────────────────────────────────────────────────────────


class TestReviewConfig:
    def test_defaults(self):
        cfg = ReviewConfig()
        assert cfg.min_scenes == 3
        assert cfg.max_scenes == 50
        assert cfg.min_scene_duration_seconds == 2.0
        assert cfg.max_scene_duration_seconds == 120.0
        assert cfg.min_total_duration_seconds == 60.0
        assert cfg.fail_on_warnings is False
        assert cfg.quality_score_pass_threshold == 0.7

    def test_stage_weights_sum_to_one(self):
        cfg = ReviewConfig()
        total = sum(cfg.stage_weights.values())
        assert abs(total - 1.0) < 1e-6

    def test_custom_config(self):
        cfg = ReviewConfig(min_scenes=1, fail_on_warnings=True)
        assert cfg.min_scenes == 1
        assert cfg.fail_on_warnings is True


# ── TestModels ────────────────────────────────────────────────────────────────


class TestStageResult:
    def test_passed_when_no_errors(self):
        sr = StageResult(stage_name="test", passed=True)
        assert sr.passed is True
        assert sr.errors == []
        assert sr.warnings == []

    def test_to_dict_serializable(self):
        sr = StageResult(stage_name="s", passed=False, errors=["e1"], warnings=["w1"])
        d = sr.to_dict()
        assert d["stage_name"] == "s"
        assert d["passed"] is False
        assert "e1" in d["errors"]


class TestSceneReview:
    def test_passed_when_no_issues(self):
        sr = SceneReview(index=1)
        assert sr.passed is True

    def test_failed_when_issues_present(self):
        sr = SceneReview(index=1, issues=["Missing image"])
        assert sr.passed is False

    def test_to_dict_includes_passed(self):
        sr = SceneReview(index=1)
        d = sr.to_dict()
        assert "passed" in d
        assert d["index"] == 1


class TestReviewReport:
    def test_default_verdict_is_fail(self):
        r = ReviewReport(project_id="p", verdict="FAIL", timestamp="t")
        assert r.verdict == "FAIL"

    def test_extension_point_fields_present(self):
        r = ReviewReport(project_id="p", verdict="PASS", timestamp="t")
        assert r.quality_score is None
        assert r.root_cause_hint == ""
        assert r.feedback_payload == {}

    def test_to_dict_complete(self):
        r = ReviewReport(project_id="p", verdict="PASS", timestamp="t")
        d = r.to_dict()
        assert d["project_id"] == "p"
        assert d["verdict"] == "PASS"


# ── TestBaseStage ─────────────────────────────────────────────────────────────


class _ConcreteStage(BaseReviewStage):
    name = "test_stage"

    def _run_checks(self, project_dir, scenes, scene_reviews, context):
        self._check(True, "should not appear")
        self._check(False, "this is an error")
        self._warn("this is a warning")


class TestBaseReviewStage:
    def test_run_returns_stage_result(self, tmp_path):
        stage = _ConcreteStage(_cfg())
        result = stage.run(tmp_path, [], [], {})
        assert isinstance(result, StageResult)
        assert result.stage_name == "test_stage"

    def test_errors_tracked(self, tmp_path):
        stage = _ConcreteStage(_cfg())
        result = stage.run(tmp_path, [], [], {})
        assert not result.passed
        assert "this is an error" in result.errors

    def test_warnings_tracked(self, tmp_path):
        stage = _ConcreteStage(_cfg())
        result = stage.run(tmp_path, [], [], {})
        assert "this is a warning" in result.warnings

    def test_checks_counted(self, tmp_path):
        stage = _ConcreteStage(_cfg())
        result = stage.run(tmp_path, [], [], {})
        assert result.checks_run == 2  # one ok + one error
        assert result.checks_passed == 1

    def test_exception_captured_as_error(self, tmp_path):
        class _BrokenStage(BaseReviewStage):
            name = "broken"

            def _run_checks(self, pd, sc, sr, ctx):
                raise RuntimeError("boom")

        stage = _BrokenStage(_cfg())
        result = stage.run(tmp_path, [], [], {})
        assert not result.passed
        assert any("boom" in e for e in result.errors)

    def test_duration_positive(self, tmp_path):
        stage = _ConcreteStage(_cfg())
        result = stage.run(tmp_path, [], [], {})
        assert result.duration_seconds >= 0


# ── TestAssetIntegrityStage ───────────────────────────────────────────────────


class TestAssetIntegrityStage:
    def test_passes_with_all_assets(self, tmp_path):
        scenes = [_make_scene(1), _make_scene(2), _make_scene(3)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        scene_reviews = [SceneReview(index=s["index"]) for s in scenes]
        stage = AssetIntegrityStage(_cfg())
        result = stage.run(proj, scenes, scene_reviews, {})
        # may have ffprobe warning — but should have no errors
        assert len(result.errors) == 0

    def test_fails_when_image_missing(self, tmp_path):
        scenes = [_make_scene(1)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        (proj / "images" / "scene-001.png").unlink()
        scene_reviews = [SceneReview(index=1)]
        stage = AssetIntegrityStage(_cfg())
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_fails_when_audio_missing(self, tmp_path):
        scenes = [_make_scene(1)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        (proj / "audio" / "scene-001.mp3").unlink()
        scene_reviews = [SceneReview(index=1)]
        stage = AssetIntegrityStage(_cfg())
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_fails_when_subtitle_missing(self, tmp_path):
        scenes = [_make_scene(1)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        (proj / "subtitles" / "scene-001.srt").unlink()
        scene_reviews = [SceneReview(index=1)]
        stage = AssetIntegrityStage(_cfg())
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_fails_when_video_clip_missing(self, tmp_path):
        scenes = [_make_scene(1)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        (proj / "video" / "scene-001.mp4").unlink()
        scene_reviews = [SceneReview(index=1)]
        stage = AssetIntegrityStage(_cfg())
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_fails_when_final_video_missing(self, tmp_path):
        scenes = [_make_scene(1)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        (proj / "video" / "final.mp4").unlink()
        scene_reviews = [SceneReview(index=1)]
        stage = AssetIntegrityStage(_cfg())
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed
        assert any("final.mp4" in e for e in result.errors)

    def test_scene_review_populated(self, tmp_path):
        scenes = [_make_scene(1)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        scene_reviews = [SceneReview(index=1)]
        stage = AssetIntegrityStage(_cfg())
        stage.run(proj, scenes, scene_reviews, {})
        assert scene_reviews[0].has_image is True
        assert scene_reviews[0].has_audio is True
        assert scene_reviews[0].image_size_bytes > 0

    def test_ass_subtitle_accepted(self, tmp_path):
        scenes = [_make_scene(1)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        # Replace SRT with ASS
        (proj / "subtitles" / "scene-001.srt").unlink()
        (proj / "subtitles" / "scene-001.ass").write_text(
            "[Script Info]\n", encoding="utf-8"
        )
        scene_reviews = [SceneReview(index=1)]
        stage = AssetIntegrityStage(_cfg())
        stage.run(proj, scenes, scene_reviews, {})
        assert scene_reviews[0].has_subtitle is True

    def test_asset_scene_skips_image_check(self, tmp_path):
        asset_scene = _make_scene(1, scene_type="asset", asset_path="/some/image.png")
        proj = _build_project(tmp_path, [asset_scene], with_assets=True)
        # Remove the generated image for this scene — should not cause an error
        img_path = proj / "images" / "scene-001.png"
        if img_path.exists():
            img_path.unlink()
        scene_reviews = [SceneReview(index=1, scene_type="asset")]
        stage = AssetIntegrityStage(_cfg())
        result = stage.run(proj, [asset_scene], scene_reviews, {})
        # No image-missing error for asset scenes
        image_errors = [e for e in result.errors if "image" in e.lower()]
        assert len(image_errors) == 0


# ── TestTimelineReviewStage ───────────────────────────────────────────────────


class TestTimelineReviewStage:
    def test_passes_sequential_scenes(self, tmp_path):
        scenes = [_make_scene(i, duration_seconds=25.0) for i in range(1, 4)]
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=i) for i in range(1, 4)]
        stage = TimelineReviewStage(_cfg())
        result = stage.run(proj, scenes, scene_reviews, {})
        assert result.passed

    def test_fails_on_non_sequential_indices(self, tmp_path):
        scenes = [_make_scene(1), _make_scene(3)]  # missing 2
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=1), SceneReview(index=3)]
        stage = TimelineReviewStage(_cfg())
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_fails_on_duplicate_indices(self, tmp_path):
        scenes = [_make_scene(1), _make_scene(1)]
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=1), SceneReview(index=1)]
        stage = TimelineReviewStage(_cfg())
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_fails_on_duration_below_minimum(self, tmp_path):
        scenes = [_make_scene(i, duration_seconds=0.5) for i in range(1, 4)]
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=i) for i in range(1, 4)]
        cfg = _cfg(min_scene_duration_seconds=2.0)
        stage = TimelineReviewStage(cfg)
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_fails_total_duration_below_minimum(self, tmp_path):
        scenes = [
            _make_scene(i, duration_seconds=5.0) for i in range(1, 4)
        ]  # 15s total
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=i) for i in range(1, 4)]
        cfg = _cfg(min_total_duration_seconds=60.0)
        stage = TimelineReviewStage(cfg)
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_total_duration_stored_in_context(self, tmp_path):
        scenes = [_make_scene(i, duration_seconds=10.0) for i in range(1, 4)]
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=i) for i in range(1, 4)]
        context = {}
        TimelineReviewStage(_cfg(min_total_duration_seconds=1.0)).run(
            proj, scenes, scene_reviews, context
        )
        assert context.get("total_declared_duration_seconds") == pytest.approx(30.0)

    def test_scene_review_duration_populated(self, tmp_path):
        scenes = [_make_scene(1, duration_seconds=12.5)]
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=1)]
        TimelineReviewStage(_cfg(min_total_duration_seconds=1.0)).run(
            proj, scenes, scene_reviews, {}
        )
        assert scene_reviews[0].declared_duration_seconds == pytest.approx(12.5)


class TestValidateSrt:
    def test_valid_srt_returns_no_issues(self, tmp_path):
        srt = tmp_path / "test.srt"
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:05,000\nHello world.\n\n"
            "2\n00:00:05,500 --> 00:00:10,000\nSecond cue.\n\n",
            encoding="utf-8",
        )
        assert _validate_srt(srt) == []

    def test_empty_srt_reports_no_timestamps(self, tmp_path):
        srt = tmp_path / "empty.srt"
        srt.write_text("", encoding="utf-8")
        issues = _validate_srt(srt)
        assert len(issues) > 0

    def test_end_before_start_is_reported(self, tmp_path):
        srt = tmp_path / "bad.srt"
        srt.write_text(
            "1\n00:00:05,000 --> 00:00:02,000\nBad cue.\n\n", encoding="utf-8"
        )
        issues = _validate_srt(srt)
        assert any("end" in i for i in issues)

    def test_overlap_is_reported(self, tmp_path):
        srt = tmp_path / "overlap.srt"
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:05,000\nFirst.\n\n"
            "2\n00:00:03,000 --> 00:00:08,000\nOverlap.\n\n",
            encoding="utf-8",
        )
        issues = _validate_srt(srt)
        assert any("overlap" in i for i in issues)


# ── TestContentReviewStage ────────────────────────────────────────────────────


class TestContentReviewStage:
    def test_passes_complete_scenes(self, tmp_path):
        scenes = [_make_scene(i) for i in range(1, 4)]
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=i) for i in range(1, 4)]
        cfg = _cfg(min_scenes=1, min_total_duration_seconds=1.0)
        stage = ContentReviewStage(cfg)
        result = stage.run(proj, scenes, scene_reviews, {})
        assert result.passed

    def test_fails_when_script_missing(self, tmp_path):
        scenes = [_make_scene(i) for i in range(1, 4)]
        proj = _build_project(tmp_path, scenes, with_assets=False)
        (proj / "script" / "script.md").unlink()
        scene_reviews = [SceneReview(index=i) for i in range(1, 4)]
        stage = ContentReviewStage(_cfg(min_scenes=1))
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_fails_when_narration_missing(self, tmp_path):
        scenes = [_make_scene(1, narration="")]
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=1)]
        stage = ContentReviewStage(_cfg(min_scenes=1))
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_fails_when_visual_prompt_missing(self, tmp_path):
        scenes = [_make_scene(1, visual_prompt="")]
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=1)]
        stage = ContentReviewStage(_cfg(min_scenes=1))
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_fails_too_few_scenes(self, tmp_path):
        scenes = [_make_scene(1)]
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=1)]
        cfg = _cfg(min_scenes=3)
        stage = ContentReviewStage(cfg)
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_scene_review_narration_word_count(self, tmp_path):
        scenes = [_make_scene(1, narration="one two three four five six seven")]
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=1)]
        ContentReviewStage(_cfg(min_scenes=1)).run(proj, scenes, scene_reviews, {})
        assert scene_reviews[0].narration_word_count == 7

    def test_asset_scene_skips_visual_prompt_check(self, tmp_path):
        scene = _make_scene(1, scene_type="asset", visual_prompt="")
        proj = _build_project(tmp_path, [scene], with_assets=False)
        scene_reviews = [SceneReview(index=1, scene_type="asset")]
        stage = ContentReviewStage(_cfg(min_scenes=1))
        result = stage.run(proj, [scene], scene_reviews, {})
        prompt_errors = [e for e in result.errors if "visual_prompt" in e]
        assert len(prompt_errors) == 0

    def test_script_word_count_stored_in_context(self, tmp_path):
        scenes = [_make_scene(1)]
        proj = _build_project(tmp_path, scenes, with_assets=False)
        scene_reviews = [SceneReview(index=1)]
        context = {}
        ContentReviewStage(_cfg(min_scenes=1)).run(proj, scenes, scene_reviews, context)
        assert "script_word_count" in context
        assert context["script_word_count"] > 0


# ── TestProductionQualityStage ────────────────────────────────────────────────


class TestProductionQualityStage:
    def test_passes_complete_project(self, tmp_path):
        scenes = [_make_scene(i) for i in range(1, 4)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        scene_reviews = [
            SceneReview(index=i, has_video_clip=True, video_clip_size_bytes=15_000)
            for i in range(1, 4)
        ]
        stage = ProductionQualityStage(_cfg())
        result = stage.run(
            proj, scenes, scene_reviews, {"total_declared_duration_seconds": 30.0}
        )
        assert len(result.errors) == 0

    def test_fails_when_clips_missing(self, tmp_path):
        scenes = [_make_scene(i) for i in range(1, 4)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        scene_reviews = [
            SceneReview(index=i, has_video_clip=False) for i in range(1, 4)
        ]
        stage = ProductionQualityStage(_cfg())
        result = stage.run(proj, scenes, scene_reviews, {})
        assert not result.passed

    def test_fails_on_missing_required_field(self, tmp_path):
        scene_no_title = _make_scene(1)
        del scene_no_title["title"]
        proj = _build_project(tmp_path, [scene_no_title], with_assets=True)
        scene_reviews = [
            SceneReview(index=1, has_video_clip=True, video_clip_size_bytes=15_000)
        ]
        stage = ProductionQualityStage(_cfg())
        result = stage.run(proj, [scene_no_title], scene_reviews, {})
        assert not result.passed

    def test_shot_type_coverage_warning(self, tmp_path):
        scenes = [_make_scene(i) for i in range(1, 6)]  # 5 scenes, no shot types
        proj = _build_project(tmp_path, scenes, with_assets=True)
        scene_reviews = [
            SceneReview(index=i, has_video_clip=True, video_clip_size_bytes=15_000)
            for i in range(1, 6)
        ]
        stage = ProductionQualityStage(_cfg())
        result = stage.run(proj, scenes, scene_reviews, {})
        assert any(
            "shot_type" in w.lower() or "v4" in w.lower() for w in result.warnings
        )

    def test_no_shot_warning_when_less_than_3_scenes(self, tmp_path):
        scenes = [_make_scene(i) for i in range(1, 3)]  # 2 scenes — below threshold
        proj = _build_project(tmp_path, scenes, with_assets=True)
        scene_reviews = [
            SceneReview(index=i, has_video_clip=True, video_clip_size_bytes=15_000)
            for i in range(1, 3)
        ]
        stage = ProductionQualityStage(_cfg())
        result = stage.run(proj, scenes, scene_reviews, {})
        shot_warnings = [
            w for w in result.warnings if "shot_type" in w.lower() or "v4" in w.lower()
        ]
        assert len(shot_warnings) == 0


# ── TestVideoQualityReviewEngine ──────────────────────────────────────────────


class TestVideoQualityReviewEngine:
    def _patch(self, monkeypatch, tmp_path):
        monkeypatch.setattr("ytfactory.review.engine.WORKSPACE_DIR", str(tmp_path))

    def test_returns_review_report(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        scenes = [_make_scene(i) for i in range(1, 4)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        project_id = proj.name

        engine = VideoQualityReviewEngine()
        report = engine.review(project_id)

        assert isinstance(report, ReviewReport)
        assert report.project_id == project_id
        assert report.verdict in ("PASS", "FAIL")

    def test_pass_on_complete_project(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        scenes = [_make_scene(i, duration_seconds=25.0) for i in range(1, 5)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        project_id = proj.name

        engine = VideoQualityReviewEngine()
        report = engine.review(project_id)

        assert report.verdict == "PASS"
        assert len(report.all_errors) == 0

    def test_fail_on_missing_assets(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        scenes = [_make_scene(i) for i in range(1, 4)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        (proj / "video" / "final.mp4").unlink()
        project_id = proj.name

        engine = VideoQualityReviewEngine()
        report = engine.review(project_id)

        assert report.verdict == "FAIL"

    def test_all_four_stages_run(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        scenes = [_make_scene(i, duration_seconds=25.0) for i in range(1, 4)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        project_id = proj.name

        engine = VideoQualityReviewEngine()
        report = engine.review(project_id)

        stage_names = {s.stage_name for s in report.stage_results}
        assert stage_names == {
            "asset_integrity",
            "timeline",
            "content",
            "production_quality",
        }

    def test_empty_project_dir_does_not_crash(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        project_id = "nonexistent-project"

        engine = VideoQualityReviewEngine()
        report = engine.review(project_id)

        assert report.verdict == "FAIL"
        assert isinstance(report, ReviewReport)

    def test_scene_reviews_match_scene_count(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        scenes = [_make_scene(i, duration_seconds=20.0) for i in range(1, 6)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        project_id = proj.name

        engine = VideoQualityReviewEngine()
        report = engine.review(project_id)

        assert report.total_scenes == 5
        assert len(report.scene_reviews) == 5

    def test_strict_mode_fails_on_warnings(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        scenes = [_make_scene(i, duration_seconds=25.0) for i in range(1, 5)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        project_id = proj.name

        strict_cfg = ReviewConfig(fail_on_warnings=True)
        engine = VideoQualityReviewEngine(strict_cfg)
        report = engine.review(project_id)

        if report.all_warnings:
            assert report.verdict == "FAIL"

    def test_processing_time_is_positive(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        scenes = [_make_scene(i, duration_seconds=25.0) for i in range(1, 4)]
        proj = _build_project(tmp_path, scenes, with_assets=True)
        project_id = proj.name

        report = VideoQualityReviewEngine().review(project_id)
        assert report.processing_time_seconds > 0


# ── TestLoadScenes ────────────────────────────────────────────────────────────


class TestLoadScenes:
    def test_loads_from_scene_plan_json(self, tmp_path):
        proj = tmp_path / "p"
        (proj / "scenes").mkdir(parents=True)
        scenes = [_make_scene(i) for i in range(1, 4)]
        (proj / "scenes" / "scene-plan.json").write_text(
            json.dumps({"scenes": scenes}), encoding="utf-8"
        )
        result = _load_scenes(proj)
        assert len(result) == 3

    def test_returns_empty_list_when_missing(self, tmp_path):
        proj = tmp_path / "p"
        proj.mkdir()
        assert _load_scenes(proj) == []

    def test_returns_empty_list_on_invalid_json(self, tmp_path):
        proj = tmp_path / "p"
        (proj / "scenes").mkdir(parents=True)
        (proj / "scenes" / "scene-plan.json").write_text("not-json", encoding="utf-8")
        assert _load_scenes(proj) == []


# ── TestReviewReporter ────────────────────────────────────────────────────────


class TestReviewReporter:
    def _make_report(self, project_id: str, verdict: str = "PASS") -> ReviewReport:
        from ytfactory.review.models import StageResult

        return ReviewReport(
            project_id=project_id,
            verdict=verdict,
            timestamp="2026-01-01T00:00:00+00:00",
            total_scenes=3,
            scenes_passed=3,
            scenes_failed=0,
            stage_results=[
                StageResult(
                    stage_name="asset_integrity",
                    passed=True,
                    checks_run=5,
                    checks_passed=5,
                )
            ],
            scene_reviews=[SceneReview(index=i) for i in range(1, 4)],
            all_errors=[],
            all_warnings=["Some warning"],
            final_video_path="/tmp/final.mp4",
            final_video_size_mb=10.5,
        )

    def _patch(self, monkeypatch, tmp_path):
        monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))

    def test_writes_review_report_md(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        project_id = "rpt-test"
        (tmp_path / project_id).mkdir()

        report = self._make_report(project_id)
        reporter = ReviewReporter()
        reporter.write(report)

        md_path = tmp_path / project_id / "review" / "review-report.md"
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "PASS" in content
        assert "rpt-test" in content

    def test_writes_scene_review_json(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        project_id = "sr-test"
        (tmp_path / project_id).mkdir()

        report = self._make_report(project_id)
        ReviewReporter().write(report)

        sr_path = tmp_path / project_id / "review" / "scene-review.json"
        assert sr_path.exists()
        data = json.loads(sr_path.read_text())
        assert data["total_scenes"] == 3
        assert len(data["scenes"]) == 3

    def test_writes_review_debug_json(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        project_id = "dbg-test"
        (tmp_path / project_id).mkdir()

        report = self._make_report(project_id)
        ReviewReporter().write(report)

        dbg_path = tmp_path / project_id / "review" / "review-debug.json"
        assert dbg_path.exists()
        data = json.loads(dbg_path.read_text())
        assert data["version"] == "v1"
        assert data["verdict"] == "PASS"

    def test_writes_extension_stubs(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        project_id = "stub-test"
        (tmp_path / project_id).mkdir()

        report = self._make_report(project_id)
        ReviewReporter().write(report)

        review_dir = tmp_path / project_id / "review"
        # quality-score.json is now written by QualityScoringReporter (not a stub)
        # root-cause files are now written by RCAReporter (not a stub)
        assert (review_dir / "engine-feedback.json").exists()

    def test_stubs_have_not_implemented_status(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        project_id = "stub2-test"
        (tmp_path / project_id).mkdir()

        report = self._make_report(project_id)
        ReviewReporter().write(report)

        # engine-feedback.json is the remaining stub; quality-score.json is now
        # written by QualityScoringReporter with real data
        ef = json.loads(
            (tmp_path / project_id / "review" / "engine-feedback.json").read_text()
        )
        assert ef["status"] == "not_implemented"

    def test_fail_verdict_appears_in_report_md(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        project_id = "fail-test"
        (tmp_path / project_id).mkdir()

        report = self._make_report(project_id, verdict="FAIL")
        ReviewReporter().write(report)

        md = (tmp_path / project_id / "review" / "review-report.md").read_text()
        assert "FAIL" in md

    def test_extension_points_in_report_md(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        project_id = "ext-test"
        (tmp_path / project_id).mkdir()

        report = self._make_report(project_id)
        ReviewReporter().write(report)

        md = (tmp_path / project_id / "review" / "review-report.md").read_text()
        assert "Quality Scoring Engine" in md
        assert "Root Cause Analysis Engine" in md


# ── TestBackwardCompatibility ─────────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_review_module_importable(self):
        from ytfactory.review import __init__  # noqa: F401

    def test_engine_importable_without_side_effects(self):
        from ytfactory.review.engine import VideoQualityReviewEngine

        assert VideoQualityReviewEngine is not None

    def test_pipeline_importable(self):
        from ytfactory.review.pipeline import ReviewPipeline

        assert ReviewPipeline is not None

    def test_artifacts_importable(self):
        from ytfactory.review.artifacts import review_directory, review_report_path

        assert callable(review_directory)
        assert callable(review_report_path)

    def test_config_extension_points_present(self):
        cfg = ReviewConfig()
        assert hasattr(cfg, "quality_score_pass_threshold")
        assert hasattr(cfg, "stage_weights")

    def test_report_extension_point_fields(self):
        r = ReviewReport(project_id="p", verdict="PASS", timestamp="t")
        assert hasattr(r, "quality_score")
        assert hasattr(r, "root_cause_hint")
        assert hasattr(r, "feedback_payload")

    def test_state_has_review_result(self):
        from ytfactory.agents.state import VideoState

        assert "review_result" in VideoState.__annotations__
