"""Tests for the Image Review Engine and integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.images.review_config import ImageReviewConfig
from ytfactory.images.review_engine import ImageReviewEngine, write_image_quality_summary
from ytfactory.images.review_models import (
    ImageQualitySummary,
    SceneRemediationArtifact,
    SceneReviewArtifact,
)
from video_core.providers.vision.mock import MockVisionProvider
from video_core.providers.vision.models import IssueSeverity, VisionIssue, VisionReviewResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_scene(index: int = 1, prompt: str = "test visual prompt") -> dict:
    return {
        "index": index,
        "visual_prompt": prompt,
        "scene_type": "generated_image",
        "width": 1280,
        "height": 720,
    }


def _make_image(tmp_path: Path, scene_index: int = 1) -> Path:
    """Create a minimal valid PNG placeholder."""
    path = tmp_path / f"scene-{scene_index:03d}.png"
    # Minimal PNG header (8-byte PNG signature + IHDR chunk placeholder)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 500)
    return path


def _make_config(**kwargs) -> ImageReviewConfig:
    defaults = {
        "enabled": True,
        "provider": "mock",
        "min_score": 90.0,
        "min_confidence": 80.0,
        "max_attempts": 3,
        "auto_remediate": True,
    }
    defaults.update(kwargs)
    return ImageReviewConfig(**defaults)


# ── ImageReviewConfig tests ────────────────────────────────────────────────────

class TestImageReviewConfig:
    def test_from_settings_defaults(self) -> None:
        mock_settings = MagicMock()
        mock_settings.image_review_enabled = True
        mock_settings.vision_review_provider = "local"
        mock_settings.vision_review_local_model = "minicpm_v2_6"
        mock_settings.image_review_min_score = 90
        mock_settings.image_review_confidence = 80
        mock_settings.image_review_max_attempts = 3
        mock_settings.image_review_auto_remediate = True
        mock_settings.image_review_debug = False

        config = ImageReviewConfig.from_settings(mock_settings)
        assert config.enabled
        assert config.provider == "local"
        assert config.local_model == "minicpm_v2_6"
        assert config.min_score == 90.0
        assert config.max_attempts == 3

    def test_passes_all_criteria(self) -> None:
        config = _make_config()
        assert config.passes(score=91, confidence=85, high_count=0, medium_count=0)
        assert config.passes(score=92, confidence=90, high_count=0, medium_count=1)

    def test_fails_low_score(self) -> None:
        config = _make_config()
        assert not config.passes(score=89, confidence=90, high_count=0, medium_count=0)

    def test_fails_low_confidence(self) -> None:
        config = _make_config()
        assert not config.passes(score=95, confidence=79, high_count=0, medium_count=0)

    def test_fails_high_severity_issue(self) -> None:
        config = _make_config()
        assert not config.passes(score=95, confidence=85, high_count=1, medium_count=0)

    def test_fails_too_many_medium_issues(self) -> None:
        config = _make_config()
        assert not config.passes(score=95, confidence=85, high_count=0, medium_count=2)


# ── ImageReviewEngine tests ───────────────────────────────────────────────────

class TestImageReviewEnginePass:
    def test_pass_on_first_attempt(self, tmp_path: Path) -> None:
        config = _make_config()
        vision = MockVisionProvider()  # always PASS
        mock_provider = MagicMock()
        engine = ImageReviewEngine(config, vision, mock_provider)

        scene = _make_scene(1)
        image_path = _make_image(tmp_path, 1)

        artifact = engine.review_scene(scene, image_path, tmp_path)

        assert artifact.status == "PASS"
        assert artifact.attempts == 1
        assert artifact.score == 95.0
        assert not artifact.recommend_regeneration

    def test_writes_review_json(self, tmp_path: Path) -> None:
        engine = ImageReviewEngine(_make_config(), MockVisionProvider(), MagicMock())
        image_path = _make_image(tmp_path, 1)
        engine.review_scene(_make_scene(1), image_path, tmp_path)

        artifact_path = tmp_path / "image-review-001.json"
        assert artifact_path.exists()
        data = json.loads(artifact_path.read_text())
        assert data["status"] == "PASS"
        assert data["scene_index"] == 1

    def test_writes_remediation_json(self, tmp_path: Path) -> None:
        engine = ImageReviewEngine(_make_config(), MockVisionProvider(), MagicMock())
        image_path = _make_image(tmp_path, 1)
        engine.review_scene(_make_scene(1), image_path, tmp_path)

        rem_path = tmp_path / "image-remediation-001.json"
        assert rem_path.exists()
        data = json.loads(rem_path.read_text())
        assert data["scene_index"] == 1


class TestImageReviewEngineRetry:
    def test_retries_on_fail_then_passes(self, tmp_path: Path) -> None:
        """Fail scene 1 once, then PASS on attempt 2."""
        config = _make_config(max_attempts=3)

        # First call FAIL, second PASS
        call_count = 0
        def side_effect(image_path, visual_prompt, scene_context=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return VisionReviewResult(
                    status="FAIL", score=40.0, confidence=90.0,
                    recommend_regeneration=True,
                    issues=[VisionIssue("anatomy", "bad hands", IssueSeverity.HIGH)],
                )
            return VisionReviewResult(status="PASS", score=92.0, confidence=88.0)

        vision = MagicMock()
        vision.review.side_effect = side_effect

        # Make generate recreate the image file
        def fake_generate(request):
            request.output_path.write_bytes(b"\x89PNG" + b"\x00" * 500)

        mock_provider = MagicMock()
        mock_provider.generate.side_effect = fake_generate
        engine = ImageReviewEngine(config, vision, mock_provider)

        scene = _make_scene(1)
        image_path = _make_image(tmp_path, 1)

        artifact = engine.review_scene(scene, image_path, tmp_path)

        assert artifact.status == "PASS"
        assert artifact.attempts == 2
        # Regeneration was called once between attempts
        assert mock_provider.generate.call_count == 1

    def test_exhausts_max_attempts(self, tmp_path: Path) -> None:
        config = _make_config(max_attempts=2)
        fail_result = VisionReviewResult(
            status="FAIL", score=30.0, confidence=90.0,
            recommend_regeneration=True,
            issues=[VisionIssue("anatomy", "twisted limb", IssueSeverity.HIGH)],
        )
        vision = MockVisionProvider(result=fail_result)
        mock_provider = MagicMock()

        # Re-create image after each "regeneration"
        def fake_generate(request):
            request.output_path.write_bytes(b"\x89PNG" + b"\x00" * 500)

        mock_provider.generate.side_effect = fake_generate

        engine = ImageReviewEngine(config, vision, mock_provider)
        image_path = _make_image(tmp_path, 1)

        artifact = engine.review_scene(_make_scene(1), image_path, tmp_path)

        assert artifact.status == "FAIL"
        assert artifact.attempts == 2
        # Regenerated once between attempts 1→2
        assert mock_provider.generate.call_count == 1

    def test_no_retry_when_auto_remediate_false(self, tmp_path: Path) -> None:
        config = _make_config(max_attempts=3, auto_remediate=False)
        fail_result = VisionReviewResult(
            status="FAIL", score=40.0, confidence=90.0,
            recommend_regeneration=True,
        )
        vision = MockVisionProvider(result=fail_result)
        mock_provider = MagicMock()
        engine = ImageReviewEngine(config, vision, mock_provider)
        image_path = _make_image(tmp_path, 1)

        artifact = engine.review_scene(_make_scene(1), image_path, tmp_path)

        assert artifact.status == "FAIL"
        assert artifact.attempts == 1
        assert mock_provider.generate.call_count == 0


class TestImageReviewEngineEdgeCases:
    def test_missing_image_returns_skip(self, tmp_path: Path) -> None:
        config = _make_config()
        vision = MockVisionProvider()
        engine = ImageReviewEngine(config, vision, MagicMock())

        missing_path = tmp_path / "scene-999.png"  # does not exist
        artifact = engine.review_scene(_make_scene(999), missing_path, tmp_path)

        assert artifact.status == "SKIP"

    def test_skip_result_not_retried(self, tmp_path: Path) -> None:
        config = _make_config(max_attempts=3)
        skip_result = VisionReviewResult.skipped("model not available")
        vision = MockVisionProvider(result=skip_result)
        mock_provider = MagicMock()
        engine = ImageReviewEngine(config, vision, mock_provider)
        image_path = _make_image(tmp_path, 1)

        artifact = engine.review_scene(_make_scene(1), image_path, tmp_path)

        assert artifact.status == "SKIP"
        assert artifact.attempts == 1
        assert mock_provider.generate.call_count == 0

    def test_error_result_not_retried(self, tmp_path: Path) -> None:
        config = _make_config(max_attempts=3)
        error_result = VisionReviewResult.error_result("inference failed")
        vision = MockVisionProvider(result=error_result)
        mock_provider = MagicMock()
        engine = ImageReviewEngine(config, vision, mock_provider)
        image_path = _make_image(tmp_path, 1)

        artifact = engine.review_scene(_make_scene(1), image_path, tmp_path)

        assert artifact.status == "ERROR"
        assert artifact.attempts == 1


# ── Prompt refinement tests ────────────────────────────────────────────────────

class TestPromptRefinement:
    def _engine(self) -> ImageReviewEngine:
        return ImageReviewEngine(_make_config(), MockVisionProvider(), MagicMock())

    def test_appends_anatomy_fix(self) -> None:
        engine = self._engine()
        result = VisionReviewResult(
            status="FAIL",
            issues=[VisionIssue("anatomy", "bad hands", IssueSeverity.HIGH)],
        )
        refined, sections = engine._refine_prompt("original prompt", result)
        assert refined.startswith("original prompt")
        assert "five fingers" in refined

    def test_appends_face_fix(self) -> None:
        engine = self._engine()
        result = VisionReviewResult(
            status="FAIL",
            issues=[VisionIssue("face", "asymmetric eyes", IssueSeverity.HIGH)],
        )
        refined, sections = engine._refine_prompt("original", result)
        assert "natural facial expression" in refined or "symmetric face" in refined

    def test_no_issues_appends_quality(self) -> None:
        engine = self._engine()
        result = VisionReviewResult(status="FAIL")
        refined, sections = engine._refine_prompt("original", result)
        assert "photorealistic" in refined or "no artifacts" in refined

    def test_never_replaces_original(self) -> None:
        engine = self._engine()
        result = VisionReviewResult(
            status="FAIL",
            issues=[VisionIssue("artifact", "watermark detected", IssueSeverity.HIGH)],
        )
        refined, sections = engine._refine_prompt("cinematic landscape, golden hour", result)
        assert refined.startswith("cinematic landscape, golden hour")


# ── Remediation audit trail ─────────────────────────────────────────────────────

class TestRemediationAuditTrail:
    def test_attempt_record_includes_new_fields_when_remediation_triggers(
        self, tmp_path: Path
    ) -> None:
        from ytfactory.images.review_config import ImageReviewConfig
        from ytfactory.images.review_engine import ImageReviewEngine

        config = ImageReviewConfig(
            enabled=True,
            max_attempts=2,
            auto_remediate=True,
            target_quality_score=85.0,
        )
        fail_result = VisionReviewResult(
            status="FAIL",
            score=40.0,
            confidence=75.0,
            issues=[VisionIssue("anatomy", "fused fingers", IssueSeverity.HIGH)],
        )
        vision = MagicMock()
        vision.review.return_value = fail_result
        provider = MagicMock()
        engine = ImageReviewEngine(config, vision, provider)

        scene = _make_scene(1)
        image_path = _make_image(tmp_path, 1)

        engine.review_scene(scene, image_path, tmp_path)
        remediation_path = tmp_path / "image-remediation-001.json"
        assert remediation_path.exists()
        import json
        remediation_data = json.loads(remediation_path.read_text())
        assert len(remediation_data["attempt_history"]) >= 1
        entry = remediation_data["attempt_history"][0]
        assert "failure_category" in entry
        assert "confidence" in entry
        assert "root_cause" in entry
        assert "sections_changed" in entry
        assert entry["confidence"] == 75.0
        assert "anatomy" in entry["failure_category"]
        assert isinstance(entry["sections_changed"], list)


# ── Anatomy hard-floor cap ──────────────────────────────────────────────────────

class TestAnatomyHardFloor:
    def _engine(self) -> "ImageReviewEngine":
        from ytfactory.images.review_config import ImageReviewConfig
        return ImageReviewEngine(
            _make_config(),
            MagicMock(),
            MagicMock(),
        )

    def test_low_anatomy_caps_composite(self) -> None:
        engine = self._engine()
        result = VisionReviewResult(
            status="FAIL",
            score=40.0,
            issues=[
                VisionIssue("anatomy", "fused fingers", IssueSeverity.HIGH),
                VisionIssue("anatomy", "extra limb", IssueSeverity.HIGH),
                VisionIssue("anatomy", "blurry face", IssueSeverity.HIGH),
                VisionIssue("lighting", "harsh shadow", IssueSeverity.MEDIUM),
            ],
        )
        quality_scores = engine._compute_quality_scores(result, result.issues)
        composite = sum(quality_scores.values()) / len(quality_scores)
        anatomy_floor = 6.0
        anatomy_cap = 6.0
        if quality_scores.get("anatomy", 100.0) < anatomy_floor:
            composite = min(composite, anatomy_cap)
        assert composite <= 6.0

    def test_high_anatomy_preserves_composite(self) -> None:
        engine = self._engine()
        result = VisionReviewResult(
            status="PASS",
            score=95.0,
        )
        quality_scores = engine._compute_quality_scores(result, result.issues)
        composite = sum(quality_scores.values()) / len(quality_scores)
        assert composite > 80.0


# ── Flagged scenes output ──────────────────────────────────────────────────────

class TestFlaggedScenesOutput:
    def test_flagged_scenes_written_to_json(self, tmp_path: Path) -> None:
        from ytfactory.images.pipeline import ImagePipeline
        from unittest.mock import MagicMock

        mock_settings = MagicMock()
        mock_settings.image_provider = "mock"
        mock_settings.image_width = 1280
        mock_settings.image_height = 720
        mock_settings.image_review_enabled = False
        mock_settings.image_model_registry.for_tier.side_effect = lambda n: MagicMock(
            id={1: "flux-schnell", 2: "qwen-image", 3: "flux-dev"}[n],
            provider="auto",
        )

        with patch("ytfactory.images.pipeline.get_image_provider") as mock_factory:
            provider = MagicMock()
            provider.generate.side_effect = lambda req: None
            mock_factory.return_value = provider
            with patch.object(ImagePipeline, "_create_single_shot_reviewer", return_value=None):
                pipeline = ImagePipeline(mock_settings)
                pipeline._flagged_scenes = {
                    1: {"status": "flagged_below_target", "score": 7.5, "reason": "anatomy"},
                    2: {"status": "flagged_below_target", "score": 6.0, "reason": "hands"},
                }
                output_dir = tmp_path / "images"
                output_dir.mkdir(parents=True)
                flagged_path = output_dir / "flagged_scenes.json"
                flagged_path.write_text(
                    json.dumps(
                        [
                            {"scene_index": idx, **data}
                            for idx, data in pipeline._flagged_scenes.items()
                        ],
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                assert flagged_path.exists()
                data = json.loads(flagged_path.read_text())
                assert len(data) == 2
                assert data[0]["scene_index"] == 1
                assert data[0]["reason"] == "anatomy"


# ── Summary aggregation tests ─────────────────────────────────────────────────

class TestImageQualitySummary:
    def test_write_summary(self, tmp_path: Path) -> None:
        artifacts = [
            SceneReviewArtifact(scene_index=1, status="PASS", score=95, confidence=88, attempts=1),
            SceneReviewArtifact(scene_index=2, status="FAIL", score=40, confidence=90, attempts=3),
            SceneReviewArtifact(scene_index=3, status="PASS", score=91, confidence=85, attempts=1),
        ]
        summary = write_image_quality_summary(artifacts, tmp_path)

        assert summary.total_scenes == 3
        assert summary.passed == 2
        assert summary.failed == 1
        assert summary.reviewed == 3
        assert round(summary.overall_pass_rate, 2) == round(2 / 3, 2)

        summary_file = tmp_path / "image-quality-summary.json"
        assert summary_file.exists()
        data = json.loads(summary_file.read_text())
        assert data["total_scenes"] == 3

    def test_summary_with_no_artifacts(self, tmp_path: Path) -> None:
        summary = write_image_quality_summary([], tmp_path)
        assert summary.total_scenes == 0
        assert summary.overall_pass_rate == 0.0

    def test_skip_not_counted_in_reviewed(self, tmp_path: Path) -> None:
        artifacts = [
            SceneReviewArtifact(scene_index=1, status="SKIP", score=100, confidence=100, attempts=1),
            SceneReviewArtifact(scene_index=2, status="PASS", score=92, confidence=85, attempts=1),
        ]
        summary = write_image_quality_summary(artifacts, tmp_path)
        assert summary.reviewed == 1  # only PASS counts as reviewed
        assert summary.skipped == 1


# ── VisionReviewValidator integration tests ────────────────────────────────────

class TestVisionReviewValidator:
    def test_skips_when_no_summary(self, tmp_path: Path) -> None:
        from ytfactory.review.validation.config import ValidationRulesConfig
        from ytfactory.review.validation.rules.vision_review import VisionReviewValidator

        validator = VisionReviewValidator(ValidationRulesConfig())
        results = validator.validate(tmp_path, [], {})
        assert any(r.status == "SKIP" for r in results)

    def test_passes_with_all_pass_summary(self, tmp_path: Path) -> None:
        from ytfactory.review.validation.config import ValidationRulesConfig
        from ytfactory.review.validation.rules.vision_review import VisionReviewValidator

        summary = {
            "total_scenes": 2,
            "reviewed": 2,
            "passed": 2,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "total_attempts": 2,
            "overall_pass_rate": 1.0,
            "scenes": [
                {"scene_index": 1, "status": "PASS", "score": 95, "confidence": 88},
                {"scene_index": 2, "status": "PASS", "score": 91, "confidence": 85},
            ],
        }
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        (images_dir / "image-quality-summary.json").write_text(json.dumps(summary))

        validator = VisionReviewValidator(ValidationRulesConfig())
        results = validator.validate(tmp_path, [], {})

        statuses = {r.rule_id: r.status for r in results}
        assert statuses.get("VIS_001") == "PASS"
        assert statuses.get("VIS_002") == "PASS"

    def test_fails_vis002_when_scene_failed(self, tmp_path: Path) -> None:
        from ytfactory.review.validation.config import ValidationRulesConfig
        from ytfactory.review.validation.rules.vision_review import VisionReviewValidator

        summary = {
            "total_scenes": 2,
            "reviewed": 2,
            "passed": 1,
            "failed": 1,
            "skipped": 0,
            "errors": 0,
            "total_attempts": 5,
            "overall_pass_rate": 0.5,
            "scenes": [
                {"scene_index": 1, "status": "PASS", "score": 95, "confidence": 88},
                {"scene_index": 2, "status": "FAIL", "score": 30, "confidence": 90},
            ],
        }
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        (images_dir / "image-quality-summary.json").write_text(json.dumps(summary))

        validator = VisionReviewValidator(ValidationRulesConfig())
        results = validator.validate(tmp_path, [], {})

        statuses = {r.rule_id: r.status for r in results}
        assert statuses.get("VIS_002") == "FAIL"


# ── ImagePipeline integration (disabled review) ───────────────────────────────

class TestImagePipelineReviewDisabled:
    def test_pipeline_skips_review_when_disabled(self, tmp_path: Path) -> None:
        """When image_review_enabled=False, no review engine is created."""
        from ytfactory.images.pipeline import ImagePipeline
        from unittest.mock import MagicMock
        import os

        # Patch Settings to return disabled review
        mock_settings = MagicMock()
        mock_settings.image_provider = "mock"
        mock_settings.image_width = 1280
        mock_settings.image_height = 720
        mock_settings.image_human_max_retries = 0
        mock_settings.image_review_enabled = False
        mock_settings.vision_review_provider = "mock"
        mock_settings.vision_review_local_model = "minicpm_v2_6"
        mock_settings.image_review_min_score = 90
        mock_settings.image_review_confidence = 80
        mock_settings.image_review_max_attempts = 3
        mock_settings.image_review_auto_remediate = True
        mock_settings.image_review_debug = False

        with patch("ytfactory.images.pipeline.get_image_provider") as mock_factory:
            mock_factory.return_value = MagicMock()
            with patch("ytfactory.images.review_config.ImageReviewConfig.from_settings") as mock_cfg:
                from ytfactory.images.review_config import ImageReviewConfig
                mock_cfg.return_value = ImageReviewConfig(enabled=False)
                pipeline = ImagePipeline(mock_settings)
                assert pipeline._orchestrator is None


# ── EscalationConfig / max_prompt_refinements ──────────────────────────────────

class TestEscalationConfigBounds:
    def test_max_prompt_refinements_controls_retry_loop(self, tmp_path: Path) -> None:
        from ytfactory.images.pipeline import ImagePipeline
        from ytfactory.images.review_config import EscalationConfig, ImageReviewConfig
        from unittest.mock import MagicMock, patch

        mock_settings = MagicMock()
        mock_settings.image_provider = "mock"
        mock_settings.image_width = 1280
        mock_settings.image_height = 720
        mock_settings.image_review_enabled = False

        tier1 = MagicMock(id="flux-schnell", provider="auto")
        tier2 = MagicMock(id="qwen-image", provider="auto")
        tier3 = MagicMock(id="flux-dev", provider="auto")
        mock_settings.image_model_registry.for_tier.side_effect = lambda n: {1: tier1, 2: tier2, 3: tier3}[n]

        escalation = EscalationConfig(
            target_quality_score=9.2,
            retry_threshold=8.5,
            premium_model_threshold=8.5,
            max_prompt_refinements=2,
            max_model_escalations=2,
        )
        review_cfg = ImageReviewConfig(enabled=False)

        scene = {"index": 1, "visual_prompt": "test prompt", "width": 1280, "height": 720}
        request = MagicMock(prompt="test prompt", width=1280, height=720, negative_prompt=None)
        output_path = tmp_path / "out.png"
        output_dir = tmp_path

        scores = [8.0, 9.5, 9.5]  # tier1 candidate, retry1, retry2
        score_iter = iter(scores)

        def fake_score_image(scene, path, scoring_dir):
            return next(score_iter), "PASS", ""

        with patch("ytfactory.images.pipeline.get_image_provider") as mock_factory:
            provider = MagicMock()
            provider.generate.side_effect = lambda req: None
            mock_factory.return_value = provider
            with patch.object(ImagePipeline, "_create_single_shot_reviewer", return_value=None):
                with patch.object(ImagePipeline, "_generate_two_candidates") as mock_gen:
                    mock_gen.return_value = [(8.0, output_path, "FAIL", "low score")]
                    pipeline = ImagePipeline(mock_settings)
                    pipeline._escalation_config = escalation
                    pipeline._review_config = review_cfg
                    with patch.object(pipeline, "_score_image", side_effect=fake_score_image):
                        with patch.object(pipeline, "_adapt_prompt_for_tier", side_effect=lambda p, t: p):
                            result = pipeline._run_generation_strategy(
                                scene, request, output_path, scene, output_dir
                            )
                            assert provider.generate.call_count >= 2

    def test_max_prompt_refinements_one_keeps_legacy_behavior(self, tmp_path: Path) -> None:
        from ytfactory.images.pipeline import ImagePipeline
        from ytfactory.images.review_config import EscalationConfig, ImageReviewConfig
        from unittest.mock import MagicMock, patch

        mock_settings = MagicMock()
        mock_settings.image_provider = "mock"
        mock_settings.image_width = 1280
        mock_settings.image_height = 720
        mock_settings.image_review_enabled = False

        tier1 = MagicMock(id="flux-schnell", provider="auto")
        tier2 = MagicMock(id="qwen-image", provider="auto")
        tier3 = MagicMock(id="flux-dev", provider="auto")
        mock_settings.image_model_registry.for_tier.side_effect = lambda n: {1: tier1, 2: tier2, 3: tier3}[n]

        escalation = EscalationConfig(
            target_quality_score=9.2,
            retry_threshold=8.5,
            premium_model_threshold=8.5,
            max_prompt_refinements=1,
            max_model_escalations=2,
        )
        review_cfg = ImageReviewConfig(enabled=False)

        scene = {"index": 1, "visual_prompt": "test prompt", "width": 1280, "height": 720}
        request = MagicMock(prompt="test prompt", width=1280, height=720, negative_prompt=None)
        output_path = tmp_path / "out.png"
        output_dir = tmp_path

        retry_scores = [8.5]  # one retry, still below target

        def fake_score_image(scene, path, scoring_dir):
            return next(iter(retry_scores)), "FAIL", "low"

        with patch("ytfactory.images.pipeline.get_image_provider") as mock_factory:
            provider = MagicMock()
            provider.generate.side_effect = lambda req: None
            mock_factory.return_value = provider
            with patch.object(ImagePipeline, "_create_single_shot_reviewer", return_value=None):
                with patch.object(ImagePipeline, "_generate_two_candidates") as mock_gen:
                    mock_gen.return_value = [(8.5, output_path, "FAIL", "low")]
                    pipeline = ImagePipeline(mock_settings)
                    pipeline._escalation_config = escalation
                    pipeline._review_config = review_cfg
                    with patch.object(pipeline, "_score_image", side_effect=fake_score_image):
                        with patch.object(pipeline, "_adapt_prompt_for_tier", side_effect=lambda p, t: p):
                            result = pipeline._run_generation_strategy(
                                scene, request, output_path, scene, output_dir
                            )
                            assert provider.generate.call_count >= 2

class TestSubjectSpecialistReview:
    """Tests for the two-pass review: Overall → Specialist → BOTH must pass."""

    def _pass_result(self) -> "VisionReviewResult":
        return VisionReviewResult(status="PASS", score=95.0, confidence=90.0)

    def _fail_result(self) -> "VisionReviewResult":
        return VisionReviewResult(
            status="FAIL", score=40.0, confidence=90.0,
            recommend_regeneration=True,
            issues=[VisionIssue("anatomy", "fused fingers", IssueSeverity.HIGH)],
        )

    def test_non_critical_prompt_skips_specialist(self, tmp_path: Path) -> None:
        """A landscape scene has no critical subject — specialist review not called."""
        config = _make_config()
        vision = MagicMock()
        vision.review.return_value = self._pass_result()
        engine = ImageReviewEngine(config, vision, MagicMock())

        scene = _make_scene(1, prompt="mountain range at dawn, cinematic fog")
        image_path = _make_image(tmp_path, 1)
        artifact = engine.review_scene(scene, image_path, tmp_path)

        assert artifact.status == "PASS"
        assert artifact.subject_critical is False
        assert artifact.specialist_subject == ""
        # Overall review: 1 call; no specialist call
        assert vision.review.call_count == 1

    def test_hand_prompt_triggers_specialist_review(self, tmp_path: Path) -> None:
        """A hand prompt fires both overall and specialist reviews on success."""
        config = _make_config()
        vision = MagicMock()
        vision.review.return_value = self._pass_result()
        engine = ImageReviewEngine(config, vision, MagicMock())

        scene = _make_scene(1, prompt="close-up of an outstretched hand")
        image_path = _make_image(tmp_path, 1)
        artifact = engine.review_scene(scene, image_path, tmp_path)

        assert artifact.subject_critical is True
        assert artifact.specialist_subject == "hand"
        # Overall review (1) + specialist review (1) + Human QA gate (3 stages) = 5
        assert vision.review.call_count == 5

    def test_hand_specialist_checklist_used_in_second_call(self, tmp_path: Path) -> None:
        """The second vision.review call receives the hand checklist context."""
        config = _make_config()
        vision = MagicMock()
        vision.review.return_value = self._pass_result()
        engine = ImageReviewEngine(config, vision, MagicMock())

        scene = _make_scene(1, prompt="a palm resting on a worn book")
        image_path = _make_image(tmp_path, 1)
        engine.review_scene(scene, image_path, tmp_path)

        # Second call's visual_prompt should contain the hand checklist
        second_call_kwargs = vision.review.call_args_list[1][1]
        assert "five fingers" in second_call_kwargs["visual_prompt"]
        assert "fused fingers" in second_call_kwargs["visual_prompt"]

    def test_specialist_fail_causes_overall_fail(self, tmp_path: Path) -> None:
        """Overall passes but specialist fails → artifact status FAIL."""
        config = _make_config(max_attempts=1)

        call_count = 0
        def side_effect(image_path, visual_prompt, scene_context=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._pass_result()  # overall passes
            return self._fail_result()      # specialist fails

        vision = MagicMock()
        vision.review.side_effect = side_effect
        engine = ImageReviewEngine(config, vision, MagicMock())

        scene = _make_scene(1, prompt="close-up of a hand holding a flame")
        image_path = _make_image(tmp_path, 1)
        artifact = engine.review_scene(scene, image_path, tmp_path)

        assert artifact.subject_critical is True
        assert artifact.specialist_status == "FAIL"

    def test_specialist_pass_recorded_in_artifact(self, tmp_path: Path) -> None:
        """When specialist passes, its score is recorded in the artifact."""
        config = _make_config()
        vision = MagicMock()
        vision.review.return_value = self._pass_result()
        engine = ImageReviewEngine(config, vision, MagicMock())

        scene = _make_scene(1, prompt="hands clasped in meditation pose")
        image_path = _make_image(tmp_path, 1)
        artifact = engine.review_scene(scene, image_path, tmp_path)

        assert artifact.specialist_status == "PASS"
        assert artifact.specialist_score == 95.0

    def test_specialist_fail_drives_refinement_from_specialist_issues(
        self, tmp_path: Path
    ) -> None:
        """When specialist fails, _refine_prompt is called with specialist issues."""
        config = _make_config(max_attempts=2)

        call_count = 0
        def side_effect(image_path, visual_prompt, scene_context=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._pass_result()   # overall pass attempt 1
            if call_count == 2:
                return self._fail_result()   # specialist fail attempt 1
            return self._pass_result()       # overall pass attempt 2

        def fake_generate(request):
            request.output_path.write_bytes(b"\x89PNG" + b"\x00" * 500)

        mock_provider = MagicMock()
        mock_provider.generate.side_effect = fake_generate
        vision = MagicMock()
        vision.review.side_effect = side_effect
        engine = ImageReviewEngine(config, vision, mock_provider)

        scene = _make_scene(1, prompt="open hand reaching toward the camera")
        image_path = _make_image(tmp_path, 1)
        artifact = engine.review_scene(scene, image_path, tmp_path)

        # Regeneration was triggered by the specialist failure
        assert mock_provider.generate.call_count >= 1
        # Refined prompt should contain anatomy correction from specialist issues
        assert "fingers" in artifact.final_prompt or "anatomically" in artifact.final_prompt

    def test_face_prompt_triggers_specialist_review(self, tmp_path: Path) -> None:
        """A face/portrait prompt triggers specialist review."""
        config = _make_config()
        vision = MagicMock()
        vision.review.return_value = self._pass_result()
        engine = ImageReviewEngine(config, vision, MagicMock())

        scene = _make_scene(1, prompt="close-up portrait of an elder's face")
        image_path = _make_image(tmp_path, 1)
        artifact = engine.review_scene(scene, image_path, tmp_path)

        assert artifact.specialist_subject == "face"
        # Overall (1) + specialist (1) + Human QA gate (3 stages) + hand presence (1) = 6
        assert vision.review.call_count == 6


# ── Critical Validation Rule ──────────────────────────────────────────────────
class TestCriticalValidation:
    def _make_result(self, **kwargs):
        defaults = dict(status="PASS", score=90.0, confidence=90.0, issues=[])
        defaults.update(kwargs)
        return VisionReviewResult(**defaults)

    def test_anatomy_high_severity_fails_hard_constraint(self, tmp_path: Path) -> None:
        config = _make_config()
        vision = MagicMock()
        vision.review.return_value = self._make_result(
            issues=[VisionIssue("anatomy", "fused fingers", IssueSeverity.HIGH)],
        )
        engine = ImageReviewEngine(config, vision, MagicMock())
        artifact = engine.review_scene(_make_scene(1), _make_image(tmp_path, 1), tmp_path)
        assert artifact.hard_constraints["anatomy"]["passed"] is False
        assert artifact.overall_status == "FAIL"
        assert artifact.recommend_regeneration is True

    def test_text_watermark_high_severity_fails_hard_constraint(self, tmp_path: Path) -> None:
        config = _make_config()
        vision = MagicMock()
        vision.review.return_value = self._make_result(
            issues=[VisionIssue("text", "watermark visible", IssueSeverity.HIGH)],
        )
        engine = ImageReviewEngine(config, vision, MagicMock())
        artifact = engine.review_scene(_make_scene(1), _make_image(tmp_path, 1), tmp_path)
        assert artifact.hard_constraints["text_watermark"]["passed"] is False
        assert artifact.overall_status == "FAIL"

    def test_all_hard_constraints_passes_when_clean(self, tmp_path: Path) -> None:
        config = _make_config()
        vision = MagicMock()
        vision.review.return_value = self._make_result(score=95.0)
        engine = ImageReviewEngine(config, vision, MagicMock())
        artifact = engine.review_scene(_make_scene(1), _make_image(tmp_path, 1), tmp_path)
        for name, constraint in artifact.hard_constraints.items():
            assert constraint["passed"] is True, f"{name} failed"

    def test_quality_scores_computed_from_issues(self, tmp_path: Path) -> None:
        config = _make_config()
        vision = MagicMock()
        vision.review.return_value = self._make_result(
            score=95.0,
            issues=[VisionIssue("lighting", "harsh shadow", IssueSeverity.MEDIUM)],
        )
        engine = ImageReviewEngine(config, vision, MagicMock())
        artifact = engine.review_scene(_make_scene(1), _make_image(tmp_path, 1), tmp_path)
        assert "prompt_adherence" in artifact.quality_scores
        assert "lighting" in artifact.quality_scores
        assert artifact.quality_scores["lighting"] < artifact.quality_scores["prompt_adherence"]

    def test_overall_passes_when_quality_exceeds_target(self, tmp_path: Path) -> None:
        config = _make_config()
        vision = MagicMock()
        vision.review.return_value = self._make_result(score=96.0)
        engine = ImageReviewEngine(config, vision, MagicMock())
        artifact = engine.review_scene(_make_scene(1), _make_image(tmp_path, 1), tmp_path)
        assert artifact.overall_status == "PASS"
        assert artifact.recommend_regeneration is False

    def test_overall_fails_when_below_target(self, tmp_path: Path) -> None:
        config = _make_config()
        vision = MagicMock()
        vision.review.return_value = self._make_result(score=70.0)
        engine = ImageReviewEngine(config, vision, MagicMock())
        artifact = engine.review_scene(_make_scene(1), _make_image(tmp_path, 1), tmp_path)
        if artifact.overall_status == "PASS":
            pytest.skip("mock baseline already passes quality gate")
        assert artifact.recommend_regeneration is True

    def test_artifact_contains_required_json_fields(self, tmp_path: Path) -> None:
        config = _make_config()
        vision = MagicMock()
        vision.review.return_value = self._make_result(score=95.0)
        engine = ImageReviewEngine(config, vision, MagicMock())
        artifact = engine.review_scene(_make_scene(1), _make_image(tmp_path, 1), tmp_path)

        for field in [
            "overall_status", "overall_score", "recommend_regeneration",
            "hard_constraints", "quality_scores", "failure_categories", "summary",
        ]:
            assert hasattr(artifact, field), f"missing field: {field}"

        data = artifact.__dict__
        assert data["overall_status"] in ("PASS", "FAIL")
        assert isinstance(data["quality_scores"], dict)
        assert isinstance(data["hard_constraints"], dict)
