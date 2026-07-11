"""Tests for the Vision Provider abstraction."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_core.providers.vision import (
    VisionProvider,
    VisionReviewResult,
    get_vision_provider,
)
from video_core.providers.vision.mock import MockVisionProvider
from video_core.providers.vision.models import IssueSeverity, VisionIssue


# ── VisionReviewResult tests ──────────────────────────────────────────────────

class TestVisionReviewResult:
    def test_passed_property(self) -> None:
        r = VisionReviewResult(status="PASS", score=95, confidence=90)
        assert r.passed

    def test_failed_property(self) -> None:
        r = VisionReviewResult(status="FAIL", score=40, confidence=90)
        assert not r.passed

    def test_high_severity_filter(self) -> None:
        issues = [
            VisionIssue("anatomy", "bad hands", IssueSeverity.HIGH),
            VisionIssue("face", "blur", IssueSeverity.MEDIUM),
            VisionIssue("artifact", "watermark", IssueSeverity.CRITICAL),
        ]
        r = VisionReviewResult(status="FAIL", issues=issues)
        high = r.high_severity_issues
        assert len(high) == 2
        assert all(i.severity in (IssueSeverity.HIGH, IssueSeverity.CRITICAL) for i in high)

    def test_medium_severity_filter(self) -> None:
        issues = [
            VisionIssue("lighting", "bad shadows", IssueSeverity.MEDIUM),
            VisionIssue("cinematic", "off composition", IssueSeverity.LOW),
        ]
        r = VisionReviewResult(status="FAIL", issues=issues)
        med = r.medium_severity_issues
        assert len(med) == 1
        assert med[0].severity == IssueSeverity.MEDIUM

    def test_skipped_factory(self) -> None:
        r = VisionReviewResult.skipped("no model")
        assert r.status == "SKIP"
        assert r.score == 100.0

    def test_error_result_factory(self) -> None:
        r = VisionReviewResult.error_result("boom")
        assert r.status == "ERROR"
        assert r.score == 0.0
        assert r.error == "boom"

    def test_to_dict(self) -> None:
        r = VisionReviewResult(
            status="PASS",
            score=95.0,
            confidence=88.0,
            issues=[VisionIssue("face", "slight asymmetry", IssueSeverity.LOW)],
        )
        d = r.to_dict()
        assert d["status"] == "PASS"
        assert d["score"] == 95.0
        assert len(d["issues"]) == 1
        assert d["issues"][0]["severity"] == "LOW"


# ── MockVisionProvider tests ──────────────────────────────────────────────────

class TestMockVisionProvider:
    def test_default_returns_pass(self, tmp_path: Path) -> None:
        provider = MockVisionProvider()
        dummy_image = tmp_path / "img.png"
        dummy_image.write_bytes(b"\x89PNG")
        result = provider.review(dummy_image, "test prompt")
        assert result.status == "PASS"
        assert result.score == 95.0

    def test_fixed_result(self, tmp_path: Path) -> None:
        fixed = VisionReviewResult(status="FAIL", score=30.0, confidence=90.0)
        provider = MockVisionProvider(result=fixed)
        dummy = tmp_path / "img.png"
        dummy.write_bytes(b"\x89PNG")
        result = provider.review(dummy, "prompt")
        assert result.status == "FAIL"
        assert result.score == 30.0

    def test_fail_scenes(self, tmp_path: Path) -> None:
        provider = MockVisionProvider(fail_scenes={2, 4}, fail_score=35.0)
        dummy = tmp_path / "img.png"
        dummy.write_bytes(b"\x89PNG")

        result_1 = provider.review(dummy, "p", scene_context={"index": 1})
        assert result_1.status == "PASS"

        result_2 = provider.review(dummy, "p", scene_context={"index": 2})
        assert result_2.status == "FAIL"
        assert result_2.score == 35.0

    def test_model_name_mock(self, tmp_path: Path) -> None:
        provider = MockVisionProvider()
        dummy = tmp_path / "img.png"
        dummy.write_bytes(b"\x89PNG")
        result = provider.review(dummy, "p")
        assert result.model_name == "mock"
        assert result.backend == "mock"


# ── Factory tests ─────────────────────────────────────────────────────────────

class TestVisionProviderFactory:
    def test_returns_mock_provider(self) -> None:
        provider = get_vision_provider("mock")
        assert isinstance(provider, MockVisionProvider)

    def test_returns_local_provider_for_transformers_model(self) -> None:
        from video_core.providers.vision.local import LocalVisionProvider
        provider = get_vision_provider("local", local_model="minicpm_v2_6")
        assert isinstance(provider, LocalVisionProvider)

    def test_returns_llama_cpp_provider_for_gguf_model(self) -> None:
        from video_core.providers.vision.llama_cpp_provider import LlamaCppVisionProvider
        provider = get_vision_provider("local", local_model="qwen2_5_vl_3b")
        assert isinstance(provider, LlamaCppVisionProvider)

    def test_invalid_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            get_vision_provider("invalid_provider")


# ── LocalVisionProvider JSON parsing tests ─────────────────────────────────────

class TestLocalVisionProviderParsing:
    """Unit tests for _parse_response — no model loading required."""

    def _provider(self) -> "LocalVisionProvider":
        from video_core.providers.vision.local import LocalVisionProvider
        return LocalVisionProvider(model_name="minicpm_v2_6")

    def test_parse_valid_json_pass(self) -> None:
        provider = self._provider()
        raw = json.dumps({
            "status": "PASS",
            "score": 93,
            "confidence": 85,
            "issues": [],
            "recommend_regeneration": False,
        })
        result = provider._parse_response(raw)
        assert result.status == "PASS"
        assert result.score == 93.0
        assert result.confidence == 85.0

    def test_parse_valid_json_fail_with_issues(self) -> None:
        provider = self._provider()
        raw = json.dumps({
            "status": "FAIL",
            "score": 45,
            "confidence": 80,
            "issues": [
                {"category": "anatomy", "description": "extra fingers", "severity": "HIGH", "location": "left hand"},
            ],
            "recommend_regeneration": True,
        })
        result = provider._parse_response(raw)
        assert result.status == "FAIL"
        assert result.score == 45.0
        assert len(result.issues) == 1
        assert result.issues[0].severity == IssueSeverity.HIGH
        assert result.recommend_regeneration

    def test_parse_markdown_fenced_json(self) -> None:
        provider = self._provider()
        raw = '```json\n{"status": "PASS", "score": 91, "confidence": 88, "issues": [], "recommend_regeneration": false}\n```'
        result = provider._parse_response(raw)
        assert result.status == "PASS"
        assert result.score == 91.0

    def test_parse_no_json_returns_error(self) -> None:
        provider = self._provider()
        result = provider._parse_response("This is plain text with no JSON at all.")
        assert result.status == "ERROR"
        assert "No JSON" in result.error

    def test_parse_malformed_json_returns_error(self) -> None:
        provider = self._provider()
        result = provider._parse_response("{invalid json }")
        assert result.status == "ERROR"

    def test_parse_unknown_severity_defaults_medium(self) -> None:
        provider = self._provider()
        raw = json.dumps({
            "status": "FAIL",
            "score": 50,
            "confidence": 70,
            "issues": [{"category": "face", "description": "issue", "severity": "UNKNOWN_LEVEL"}],
            "recommend_regeneration": True,
        })
        result = provider._parse_response(raw)
        assert result.issues[0].severity == IssueSeverity.MEDIUM

    def test_parse_model_agnostic_response(self) -> None:
        """Any model producing this JSON schema works the same."""
        provider = self._provider()
        # Simulate different model producing same contract
        raw = json.dumps({
            "status": "FAIL",
            "score": 60,
            "confidence": 75,
            "issues": [
                {"category": "environment", "description": "floating object", "severity": "MEDIUM"},
                {"category": "lighting", "description": "broken reflection", "severity": "HIGH"},
            ],
            "recommend_regeneration": True,
        })
        result = provider._parse_response(raw)
        assert len(result.high_severity_issues) == 1
        assert len(result.medium_severity_issues) == 1


# ── LlamaCppVisionProvider JSON parsing tests ──────────────────────────────────

class TestLlamaCppVisionProviderParsing:
    """Unit tests for _parse_response — same JSON contract as LocalVisionProvider."""

    def _provider(self) -> "LlamaCppVisionProvider":
        from video_core.providers.vision.llama_cpp_provider import LlamaCppVisionProvider
        return LlamaCppVisionProvider(model_name="qwen2_5_vl_3b")

    def test_parse_valid_json_pass(self) -> None:
        provider = self._provider()
        raw = json.dumps({
            "status": "PASS",
            "score": 91,
            "confidence": 88,
            "issues": [],
            "recommend_regeneration": False,
        })
        result = provider._parse_response(raw)
        assert result.status == "PASS"
        assert result.score == 91.0
        assert result.confidence == 88.0

    def test_parse_valid_json_fail_with_issues(self) -> None:
        provider = self._provider()
        raw = json.dumps({
            "status": "FAIL",
            "score": 50,
            "confidence": 75,
            "issues": [
                {"category": "anatomy", "description": "extra finger", "severity": "HIGH", "location": "hand"},
            ],
            "recommend_regeneration": True,
        })
        result = provider._parse_response(raw)
        assert result.status == "FAIL"
        assert len(result.issues) == 1
        assert result.issues[0].severity == IssueSeverity.HIGH

    def test_parse_markdown_fenced_json(self) -> None:
        from video_core.providers.vision.models import IssueSeverity as _IS
        provider = self._provider()
        raw = '```json\n{"status": "PASS", "score": 93, "confidence": 90, "issues": [], "recommend_regeneration": false}\n```'
        result = provider._parse_response(raw)
        assert result.status == "PASS"
        assert result.score == 93.0

    def test_parse_no_json_returns_error(self) -> None:
        provider = self._provider()
        result = provider._parse_response("No JSON at all.")
        assert result.status == "ERROR"
        assert "No JSON" in result.error

    def test_parse_malformed_json_returns_error(self) -> None:
        provider = self._provider()
        result = provider._parse_response("{invalid json}")
        assert result.status == "ERROR"

    def test_parse_unknown_severity_defaults_medium(self) -> None:
        provider = self._provider()
        raw = json.dumps({
            "status": "FAIL",
            "score": 55,
            "confidence": 70,
            "issues": [{"category": "face", "description": "issue", "severity": "UNKNOWN"}],
            "recommend_regeneration": True,
        })
        result = provider._parse_response(raw)
        assert result.issues[0].severity == IssueSeverity.MEDIUM

    def test_parse_shares_same_contract_as_local_provider(self) -> None:
        """Qwen and MiniCPM providers accept the same JSON schema."""
        from video_core.providers.vision.local import LocalVisionProvider

        raw = json.dumps({
            "status": "FAIL",
            "score": 62,
            "confidence": 78,
            "issues": [
                {"category": "environment", "description": "floating rock", "severity": "MEDIUM"},
                {"category": "lighting", "description": "broken shadow", "severity": "HIGH"},
            ],
            "recommend_regeneration": True,
        })

        qwen_result = self._provider()._parse_response(raw)
        minicpm_result = LocalVisionProvider(model_name="minicpm_v2_6")._parse_response(raw)

        assert qwen_result.status == minicpm_result.status
        assert qwen_result.score == minicpm_result.score
        assert len(qwen_result.issues) == len(minicpm_result.issues)


# ── LlamaCppVisionProvider model loading (no live model) ──────────────────────

class TestLlamaCppVisionProviderLoading:
    def test_skips_when_model_not_provisioned(self, tmp_path: Path) -> None:
        """Provider returns skipped result when model is not in LAMM cache."""
        from video_core.providers.vision.llama_cpp_provider import LlamaCppVisionProvider

        provider = LlamaCppVisionProvider(model_name="qwen2_5_vl_3b", base_dir=tmp_path)
        dummy = tmp_path / "img.png"
        dummy.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        # Patch provision to return MISSING so model isn't loaded
        from unittest.mock import patch, MagicMock
        from ytfactory.models.models import ModelStatus, ProvisionResult

        missing = ProvisionResult(
            name="qwen2_5_vl_3b",
            status=ModelStatus.MISSING,
            message="not in cache",
        )
        with patch.object(provider._manager, "provision", return_value=missing):
            result = provider.review(dummy, "test prompt")

        assert result.status == "SKIP"

    def test_error_when_image_missing(self, tmp_path: Path) -> None:
        from video_core.providers.vision.llama_cpp_provider import LlamaCppVisionProvider

        provider = LlamaCppVisionProvider(model_name="qwen2_5_vl_3b", base_dir=tmp_path)
        missing_image = tmp_path / "nonexistent.png"

        result = provider.review(missing_image, "test prompt")
        assert result.status == "ERROR"
        assert "not found" in result.error.lower()


# ── is_hand_focal() regression tests ─────────────────────────────────────────

# Real visual prompts from the Plato project that exhibit the two-thumb glitch.
_SCENE_034_PROMPT = (
    "Low-angle shot looking upward at an open palm, fingers gently spread, "
    "against a pale sky at late afternoon. The hand belongs to a figure in "
    "simple cream linen, but only the hand and wrist are visible in frame. "
    "A single worn coin rests in the center of the palm—small, ancient-looking, "
    "catching warm light."
)

_SCENE_035_PROMPT = (
    "High-angle shot looking down at a figure standing alone in the center of "
    "a modest courtyard, arms at their sides, palms open and facing forward—empty. "
    "The figure wears simple earth-toned clothing. The courtyard is paved with worn "
    "stone, cracks visible, weeds pushing through in places. Soft pre-dawn light."
)

_NON_HAND_PROMPT = (
    "Wide establishing shot of an ancient Athenian agora at golden hour. "
    "Marble columns cast long shadows across the cobblestones. A lone figure "
    "in a white robe walks in the distance toward a temple entrance."
)


class TestIsHandFocal:
    """Unit tests for is_hand_focal() keyword detector."""

    def test_scene_034_palm_and_fingers_detected(self) -> None:
        from video_core.providers.vision.base import is_hand_focal
        assert is_hand_focal(_SCENE_034_PROMPT), "scene-034 prompt has palm/fingers/wrist"

    def test_scene_035_palms_detected(self) -> None:
        from video_core.providers.vision.base import is_hand_focal
        assert is_hand_focal(_SCENE_035_PROMPT), "scene-035 prompt has palms"

    def test_non_hand_scene_returns_false(self) -> None:
        from video_core.providers.vision.base import is_hand_focal
        assert not is_hand_focal(_NON_HAND_PROMPT), "no hand keywords in agora prompt"

    def test_each_hand_keyword_individually(self) -> None:
        from video_core.providers.vision.base import is_hand_focal
        keywords = ["hand", "hands", "palm", "palms", "finger", "fingers",
                    "knuckle", "knuckles", "digit", "digits", "fist", "wrist", "wrists"]
        for kw in keywords:
            assert is_hand_focal(f"A scene featuring {kw} prominently."), kw

    def test_no_false_positive_on_landscape_or_landmark(self) -> None:
        from video_core.providers.vision.base import is_hand_focal
        non_hand_prompts = [
            "Rocky landscape with no people",
            "A digital clock face on the wall",
            "An island floating above the clouds",
            "Close-up of scattered parchment and ink",
        ]
        for p in non_hand_prompts:
            assert not is_hand_focal(p), f"false positive on: {p!r}"

    def test_case_insensitive_match(self) -> None:
        from video_core.providers.vision.base import is_hand_focal
        assert is_hand_focal("HAND reaching toward the sky")
        assert is_hand_focal("PALMS open wide")
        assert is_hand_focal("Fingers intertwined")


# ── _build_prompt() hand-anatomy injection tests ──────────────────────────────


class TestBuildPromptHandAnatomy:
    """Verify that HAND_ANATOMY_PROMPT is injected iff the prompt is hand-focal."""

    def _local_provider(self):
        from video_core.providers.vision.local import LocalVisionProvider
        return LocalVisionProvider(model_name="minicpm_v2_6")

    def _llama_provider(self):
        from video_core.providers.vision.llama_cpp_provider import LlamaCppVisionProvider
        return LlamaCppVisionProvider(model_name="qwen2_5_vl_3b")

    def test_local_provider_injects_hand_block_for_scene_034(self) -> None:
        from video_core.providers.vision.base import HAND_ANATOMY_PROMPT
        provider = self._local_provider()
        result = provider._build_prompt(_SCENE_034_PROMPT)
        assert HAND_ANATOMY_PROMPT in result

    def test_local_provider_injects_hand_block_for_scene_035(self) -> None:
        from video_core.providers.vision.base import HAND_ANATOMY_PROMPT
        provider = self._local_provider()
        result = provider._build_prompt(_SCENE_035_PROMPT)
        assert HAND_ANATOMY_PROMPT in result

    def test_local_provider_no_hand_block_for_non_hand_scene(self) -> None:
        from video_core.providers.vision.base import HAND_ANATOMY_PROMPT
        provider = self._local_provider()
        result = provider._build_prompt(_NON_HAND_PROMPT)
        assert HAND_ANATOMY_PROMPT not in result, "hand block must not appear in non-hand scene"

    def test_llama_provider_injects_hand_block_for_scene_034(self) -> None:
        from video_core.providers.vision.base import HAND_ANATOMY_PROMPT
        provider = self._llama_provider()
        result = provider._build_prompt(_SCENE_034_PROMPT)
        assert HAND_ANATOMY_PROMPT in result

    def test_llama_provider_injects_hand_block_for_scene_035(self) -> None:
        from video_core.providers.vision.base import HAND_ANATOMY_PROMPT
        provider = self._llama_provider()
        result = provider._build_prompt(_SCENE_035_PROMPT)
        assert HAND_ANATOMY_PROMPT in result

    def test_llama_provider_no_hand_block_for_non_hand_scene(self) -> None:
        from video_core.providers.vision.base import HAND_ANATOMY_PROMPT
        provider = self._llama_provider()
        result = provider._build_prompt(_NON_HAND_PROMPT)
        assert HAND_ANATOMY_PROMPT not in result

    def test_hand_block_contains_duplicated_thumb_criterion(self) -> None:
        """The HAND_ANATOMY_PROMPT must explicitly name the duplicated-thumb failure mode."""
        from video_core.providers.vision.base import HAND_ANATOMY_PROMPT
        assert "duplicated thumb" in HAND_ANATOMY_PROMPT.lower() or \
               "both outer edges" in HAND_ANATOMY_PROMPT.lower(), \
               "duplicated-thumb criterion must be explicit in HAND_ANATOMY_PROMPT"

    def test_base_prompt_includes_hand_in_anatomy_section(self) -> None:
        """VISION_REVIEW_PROMPT base must mention 5 digits and thumb placement."""
        from video_core.providers.vision.base import VISION_REVIEW_PROMPT
        assert "5 digits" in VISION_REVIEW_PROMPT or "5 fingers" in VISION_REVIEW_PROMPT or \
               "thumb" in VISION_REVIEW_PROMPT.lower(), \
               "Base prompt must mention hand anatomy (5 digits / thumb)"

    def test_visual_prompt_is_forwarded_in_built_prompt(self) -> None:
        """The original visual_prompt string must appear verbatim in the built prompt."""
        provider = self._local_provider()
        result = provider._build_prompt(_SCENE_034_PROMPT)
        assert _SCENE_034_PROMPT in result

    def test_both_providers_produce_identical_structure_for_non_hand(self) -> None:
        """For a non-hand scene, both providers produce the same base prompt."""
        local = self._local_provider()
        llama = self._llama_provider()
        local_result = local._build_prompt(_NON_HAND_PROMPT)
        llama_result = llama._build_prompt(_NON_HAND_PROMPT)
        assert local_result == llama_result
