"""Unit tests for ImageRemediationOrchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from ytfactory.images.review_config import ImageReviewConfig
from ytfactory.images.review_models import SceneReviewArtifact
from ytfactory.prompts.prompt_remediation_builder import PromptRemediationBuilder, RemediationInput
from ytfactory.workflow.image_remediation_orchestrator import (
    ImageRemediationOrchestrator,
    _dict_to_vision_issue,
    _qa_scores,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _config(max_attempts: int = 3, auto_remediate: bool = True) -> ImageReviewConfig:
    return ImageReviewConfig(
        enabled=True,
        provider="local",
        local_model="minicpm_v2_6",
        min_score=90.0,
        min_confidence=80.0,
        max_attempts=max_attempts,
        auto_remediate=auto_remediate,
    )


def _scene(idx: int = 1, prompt: str = "Ancient Greek philosopher walking along a stone road.") -> dict:
    return {"index": idx, "visual_prompt": prompt, "width": 1920, "height": 1080}


def _pass_artifact(idx: int = 1) -> SceneReviewArtifact:
    return SceneReviewArtifact(
        scene_index=idx,
        status="PASS",
        score=95.0,
        confidence=90.0,
        attempts=1,
        final_prompt="",
    )


def _fail_artifact(idx: int = 1, issues: list[dict] | None = None) -> SceneReviewArtifact:
    return SceneReviewArtifact(
        scene_index=idx,
        status="FAIL",
        score=55.0,
        confidence=85.0,
        issues=issues or [{"category": "anatomy", "severity": "HIGH", "description": "bad hand"}],
        attempts=1,
        final_prompt="",
    )


def _make_orchestrator(
    *,
    max_attempts: int = 3,
    auto_remediate: bool = True,
    side_effects: list[SceneReviewArtifact] | None = None,
    builder: PromptRemediationBuilder | None = None,
) -> tuple[ImageRemediationOrchestrator, MagicMock, MagicMock]:
    """Return (orchestrator, mock_review_engine, mock_image_provider)."""
    config = _config(max_attempts=max_attempts, auto_remediate=auto_remediate)
    vision = MagicMock()
    image_prov = MagicMock()

    with patch("ytfactory.workflow.image_remediation_orchestrator.ImageReviewEngine") as MockEngine:
        engine_instance = MockEngine.return_value
        if side_effects:
            engine_instance.review_scene.side_effect = side_effects
        else:
            engine_instance.review_scene.return_value = _pass_artifact()
        orch = ImageRemediationOrchestrator(config, vision, image_prov, builder=builder)
        orch._review_engine = engine_instance
        return orch, engine_instance, image_prov


# ── _qa_scores helper ──────────────────────────────────────────────────────────


class TestQaScores:
    def test_no_issues_all_100(self) -> None:
        n, t, c = _qa_scores([])
        assert n == 100.0 and t == 100.0 and c == 100.0

    def test_anatomy_high_deducts_technical(self) -> None:
        issues = [{"category": "anatomy", "severity": "HIGH"}]
        _, t, _ = _qa_scores(issues)
        assert t == 70.0  # 100 - 30

    def test_environment_high_deducts_narrative(self) -> None:
        issues = [{"category": "environment", "severity": "HIGH"}]
        n, _, _ = _qa_scores(issues)
        assert n == 70.0

    def test_lighting_critical_deducts_cinematic(self) -> None:
        issues = [{"category": "lighting", "severity": "CRITICAL"}]
        _, _, c = _qa_scores(issues)
        assert c == 50.0

    def test_scores_clamped_at_zero(self) -> None:
        issues = [{"category": "anatomy", "severity": "CRITICAL"}] * 10
        _, t, _ = _qa_scores(issues)
        assert t == 0.0


# ── _dict_to_vision_issue helper ──────────────────────────────────────────────


class TestDictToVisionIssue:
    def test_basic_conversion(self) -> None:
        from ytfactory.providers.vision.models import IssueSeverity
        issue = _dict_to_vision_issue({"category": "face", "description": "bad eye", "severity": "HIGH"})
        assert issue.category == "face"
        assert issue.severity == IssueSeverity.HIGH

    def test_unknown_severity_defaults_to_medium(self) -> None:
        from ytfactory.providers.vision.models import IssueSeverity
        issue = _dict_to_vision_issue({"severity": "UNKNOWN"})
        assert issue.severity == IssueSeverity.MEDIUM


# ── Pass on first attempt ─────────────────────────────────────────────────────


class TestPassOnFirstAttempt:
    def test_returns_pass_artifact(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        orch, engine, _ = _make_orchestrator(side_effects=[_pass_artifact()])
        result = orch.review_scene(_scene(), image, tmp_path)
        assert result.status == "PASS"

    def test_engine_called_once(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        orch, engine, _ = _make_orchestrator(side_effects=[_pass_artifact()])
        orch.review_scene(_scene(), image, tmp_path)
        assert engine.review_scene.call_count == 1

    def test_no_regeneration_on_pass(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        orch, engine, image_prov = _make_orchestrator(side_effects=[_pass_artifact()])
        orch.review_scene(_scene(), image, tmp_path)
        image_prov.generate.assert_not_called()

    def test_attempt_count_is_one(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        orch, engine, _ = _make_orchestrator(side_effects=[_pass_artifact()])
        result = orch.review_scene(_scene(), image, tmp_path)
        assert result.attempts == 1


# ── Pass after remediation ────────────────────────────────────────────────────


class TestPassAfterRemediation:
    def test_returns_pass_after_one_fail(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        side = [_fail_artifact(), _pass_artifact()]
        orch, engine, image_prov = _make_orchestrator(side_effects=side)

        # _regenerate will unlink then call generate; recreate the file after unlink
        def fake_generate(req: Any) -> None:
            req.output_path.write_bytes(b"png")

        image_prov.generate.side_effect = fake_generate
        result = orch.review_scene(_scene(), image, tmp_path)
        assert result.status == "PASS"

    def test_attempts_reflect_orchestrator_total(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        side = [_fail_artifact(), _pass_artifact()]
        orch, engine, image_prov = _make_orchestrator(side_effects=side)

        def fake_generate(req: Any) -> None:
            req.output_path.write_bytes(b"png")

        image_prov.generate.side_effect = fake_generate
        result = orch.review_scene(_scene(), image, tmp_path)
        assert result.attempts == 2


# ── Max attempts exhausted ────────────────────────────────────────────────────


class TestMaxAttemptsExhausted:
    def test_returns_fail_after_max_attempts(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        side = [_fail_artifact()] * 3
        orch, engine, image_prov = _make_orchestrator(max_attempts=3, side_effects=side)

        def fake_generate(req: Any) -> None:
            req.output_path.write_bytes(b"png")

        image_prov.generate.side_effect = fake_generate
        result = orch.review_scene(_scene(), image, tmp_path)
        assert result.status == "FAIL"

    def test_engine_called_max_attempts_times(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        side = [_fail_artifact()] * 3
        orch, engine, image_prov = _make_orchestrator(max_attempts=3, side_effects=side)

        def fake_generate(req: Any) -> None:
            req.output_path.write_bytes(b"png")

        image_prov.generate.side_effect = fake_generate
        orch.review_scene(_scene(), image, tmp_path)
        assert engine.review_scene.call_count == 3


# ── auto_remediate=False ──────────────────────────────────────────────────────


class TestAutoRemediateDisabled:
    def test_no_regeneration_when_disabled(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        orch, engine, image_prov = _make_orchestrator(
            auto_remediate=False, side_effects=[_fail_artifact()]
        )
        orch.review_scene(_scene(), image, tmp_path)
        image_prov.generate.assert_not_called()

    def test_engine_called_only_once_when_disabled(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        orch, engine, _ = _make_orchestrator(
            auto_remediate=False, side_effects=[_fail_artifact()]
        )
        orch.review_scene(_scene(), image, tmp_path)
        assert engine.review_scene.call_count == 1


# ── SKIP status not retried ───────────────────────────────────────────────────


class TestSkipNotRetried:
    def test_skip_terminates_immediately(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        skip_art = SceneReviewArtifact(
            scene_index=1, status="SKIP", score=100.0, confidence=100.0, attempts=1
        )
        orch, engine, image_prov = _make_orchestrator(side_effects=[skip_art])
        result = orch.review_scene(_scene(), image, tmp_path)
        assert result.status == "SKIP"
        image_prov.generate.assert_not_called()
        assert engine.review_scene.call_count == 1


# ── Missing image ─────────────────────────────────────────────────────────────


class TestMissingImage:
    def test_returns_skip_when_image_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.png"
        orch, engine, _ = _make_orchestrator()
        result = orch.review_scene(_scene(), missing, tmp_path)
        assert result.status == "SKIP"

    def test_engine_not_called_when_image_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.png"
        orch, engine, _ = _make_orchestrator()
        orch.review_scene(_scene(), missing, tmp_path)
        engine.review_scene.assert_not_called()


# ── Per-attempt history files ──────────────────────────────────────────────────


class TestAttemptHistoryFiles:
    def test_attempt_dir_created(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        side = [_fail_artifact(), _pass_artifact()]
        orch, engine, image_prov = _make_orchestrator(max_attempts=3, side_effects=side)

        def fake_generate(req: Any) -> None:
            req.output_path.write_bytes(b"png")

        image_prov.generate.side_effect = fake_generate
        orch.review_scene(_scene(idx=1), image, tmp_path)

        attempt_dir = tmp_path / "remediation" / "scene-001" / "attempt-1"
        assert attempt_dir.exists()

    def test_prompt_md_written(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        side = [_fail_artifact(), _pass_artifact()]
        orch, engine, image_prov = _make_orchestrator(max_attempts=3, side_effects=side)

        def fake_generate(req: Any) -> None:
            req.output_path.write_bytes(b"png")

        image_prov.generate.side_effect = fake_generate
        orch.review_scene(_scene(idx=1), image, tmp_path)

        prompt_file = tmp_path / "remediation" / "scene-001" / "attempt-1" / "prompt.md"
        assert prompt_file.exists()

    def test_review_json_written(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        side = [_fail_artifact(), _pass_artifact()]
        orch, engine, image_prov = _make_orchestrator(max_attempts=3, side_effects=side)

        def fake_generate(req: Any) -> None:
            req.output_path.write_bytes(b"png")

        image_prov.generate.side_effect = fake_generate
        orch.review_scene(_scene(idx=1), image, tmp_path)

        review_file = tmp_path / "remediation" / "scene-001" / "attempt-1" / "review.json"
        assert review_file.exists()


# ── Final directory ───────────────────────────────────────────────────────────


class TestFinalDirectory:
    def test_final_review_json_written(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        side = [_fail_artifact(), _pass_artifact()]
        orch, engine, image_prov = _make_orchestrator(max_attempts=3, side_effects=side)

        def fake_generate(req: Any) -> None:
            req.output_path.write_bytes(b"png")

        image_prov.generate.side_effect = fake_generate
        orch.review_scene(_scene(idx=1), image, tmp_path)

        final_dir = tmp_path / "remediation" / "scene-001" / "final"
        assert (final_dir / "review.json").exists()

    def test_final_metadata_json_written(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")
        side = [_fail_artifact(), _pass_artifact()]
        orch, engine, image_prov = _make_orchestrator(max_attempts=3, side_effects=side)

        def fake_generate(req: Any) -> None:
            req.output_path.write_bytes(b"png")

        image_prov.generate.side_effect = fake_generate
        orch.review_scene(_scene(idx=1), image, tmp_path)

        meta = tmp_path / "remediation" / "scene-001" / "final" / "metadata.json"
        assert meta.exists()
        data = json.loads(meta.read_text())
        assert data["total_attempts"] == 2
        assert data["remediation_applied"] is True


# ── Refined prompt passed to regeneration ─────────────────────────────────────


class TestRefinedPromptUsed:
    def test_refined_prompt_used_in_regeneration(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")

        original_prompt = "Ancient Greek philosopher."
        custom_refined = f"{original_prompt}\n\nImprove only the following while preserving the original scene:\n- Natural five-finger hands."

        mock_builder = MagicMock(spec=PromptRemediationBuilder)
        mock_builder.build.return_value = custom_refined

        side = [_fail_artifact(), _pass_artifact()]
        orch, engine, image_prov = _make_orchestrator(
            side_effects=side, builder=mock_builder
        )

        captured_prompts: list[str] = []

        def fake_generate(req: Any) -> None:
            captured_prompts.append(req.prompt)
            req.output_path.write_bytes(b"png")

        image_prov.generate.side_effect = fake_generate
        orch.review_scene(_scene(prompt=original_prompt), image, tmp_path)

        assert len(captured_prompts) == 1
        assert captured_prompts[0] == custom_refined

    def test_builder_called_with_vision_result(self, tmp_path: Path) -> None:
        image = tmp_path / "scene-001.png"
        image.write_bytes(b"png")

        mock_builder = MagicMock(spec=PromptRemediationBuilder)
        mock_builder.build.return_value = "refined prompt"

        side = [_fail_artifact(), _pass_artifact()]
        orch, engine, image_prov = _make_orchestrator(
            side_effects=side, builder=mock_builder
        )

        def fake_generate(req: Any) -> None:
            req.output_path.write_bytes(b"png")

        image_prov.generate.side_effect = fake_generate
        orch.review_scene(_scene(), image, tmp_path)

        mock_builder.build.assert_called_once()
        call_arg = mock_builder.build.call_args[0][0]
        assert isinstance(call_arg, RemediationInput)
        assert call_arg.result.status == "FAIL"
