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
        def side_effect(image_path, visual_prompt, scene_context=None):
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
        refined = engine._refine_prompt("original prompt", result)
        assert refined.startswith("original prompt")
        assert "five fingers" in refined

    def test_appends_face_fix(self) -> None:
        engine = self._engine()
        result = VisionReviewResult(
            status="FAIL",
            issues=[VisionIssue("face", "asymmetric eyes", IssueSeverity.HIGH)],
        )
        refined = engine._refine_prompt("original", result)
        assert "natural facial expression" in refined or "symmetric face" in refined

    def test_no_issues_appends_quality(self) -> None:
        engine = self._engine()
        result = VisionReviewResult(status="FAIL")
        refined = engine._refine_prompt("original", result)
        assert "photorealistic" in refined or "no artifacts" in refined

    def test_never_replaces_original(self) -> None:
        engine = self._engine()
        result = VisionReviewResult(
            status="FAIL",
            issues=[VisionIssue("artifact", "watermark detected", IssueSeverity.HIGH)],
        )
        refined = engine._refine_prompt("cinematic landscape, golden hour", result)
        assert refined.startswith("cinematic landscape, golden hour")


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


# ── Subject Specialist Review (ADR-0013) ──────────────────────────────────────

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
        # Overall review + specialist review = 2 calls
        assert vision.review.call_count == 2

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
        def side_effect(image_path, visual_prompt, scene_context=None):
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
        def side_effect(image_path, visual_prompt, scene_context=None):
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
        assert vision.review.call_count == 2
