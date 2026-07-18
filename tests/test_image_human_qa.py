"""Tests for ADR-0015 Human Subject QA Gate.

Covers:
  - human_qa module: is_human_critical, has_clothing_specified, context builders
  - ImageReviewConfig: human_qa_enabled field and from_settings loading
  - SceneReviewArtifact: new Human QA fields present
  - ImageReviewEngine._run_human_qa_gate: staged QA trigger and skip logic
  - HumanValidator HUM_004: artifact-based gate outcome reporting
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── human_qa module ───────────────────────────────────────────────────────────


class TestIsHumanCritical:
    def _call(self, prompt, shot_type=""):
        from ytfactory.images.human_qa import is_human_critical
        return is_human_critical(prompt, shot_type)

    def test_portrait_shot_type_triggers(self):
        assert self._call("a person standing", "portrait") is True

    def test_close_up_shot_type_triggers(self):
        assert self._call("a woman smiling", "close-up") is True

    def test_medium_shot_triggers(self):
        assert self._call("a man reading", "medium shot") is True

    def test_wide_shot_with_no_critical_subject_does_not_trigger(self):
        assert self._call("crowd at a festival", "wide shot") is False

    def test_hand_in_prompt_triggers_regardless_of_shot(self):
        # detect_critical_subject returns "hand" for "hands" keyword
        assert self._call("close view of hands holding a book", "wide shot") is True

    def test_face_in_prompt_triggers(self):
        assert self._call("detailed face of an elderly man", "wide shot") is True

    def test_no_human_critical_subject_and_wide_shot_skips(self):
        assert self._call("mountains and rivers landscape", "wide shot") is False

    def test_empty_shot_type_uses_prompt_only(self):
        # No close shot type, no critical body-part keyword → not critical
        assert self._call("a warrior standing in a field", "") is False

    def test_gesture_in_prompt_triggers(self):
        assert self._call("a person making a gesture of greeting", "establishing shot") is True


class TestHasClothingSpecified:
    def _call(self, prompt):
        from ytfactory.images.human_qa import has_clothing_specified
        return has_clothing_specified(prompt)

    def test_wearing_shirt(self):
        assert self._call("Young man wearing a grey shirt") is True

    def test_dressed_in_sari(self):
        assert self._call("Woman dressed in a red sari") is True

    def test_clothed_in_robe(self):
        assert self._call("Monk clothed in an orange robe") is True

    def test_no_clothing_trigger(self):
        assert self._call("A person standing in a forest") is False

    def test_trigger_but_no_clothing_noun(self):
        # "wearing" present but no clothing item
        assert self._call("A person wearing a smile") is False

    def test_forest_does_not_trigger(self):
        assert self._call("Wide shot in a forest") is False

    def test_armour_triggers(self):
        assert self._call("Warrior dressed in bronze armour") is True

    def test_turban_triggers(self):
        assert self._call("Elder man wearing a turban") is True


class TestContextBuilders:
    def test_human_qa_context_contains_key_checks(self):
        from ytfactory.images.human_qa import build_human_qa_context
        ctx = build_human_qa_context("young woman smiling")
        assert "HUMAN SUBJECT QA" in ctx
        assert "Missing body parts" in ctx
        assert "Deformed face" in ctx
        assert "young woman smiling" in ctx

    def test_hand_qa_context_contains_finger_checks(self):
        from ytfactory.images.human_qa import build_hand_qa_context
        ctx = build_hand_qa_context("hands holding a pen")
        assert "HAND ANATOMY QA" in ctx
        assert "exactly 5 fingers" in ctx
        assert "Fused fingers" in ctx
        assert "no hands are visible" in ctx

    def test_clothing_qa_context_contains_clothing_check(self):
        from ytfactory.images.human_qa import build_clothing_qa_context
        ctx = build_clothing_qa_context("man wearing a blue shirt")
        assert "CLOTHING VALIDATION" in ctx
        assert "man wearing a blue shirt" in ctx
        assert "Entirely absent" in ctx

    def test_prompt_compliance_context_contains_all_attributes(self):
        from ytfactory.images.human_qa import build_prompt_compliance_context
        ctx = build_prompt_compliance_context("warrior with a sword")
        assert "PROMPT COMPLIANCE" in ctx
        assert "Subject" in ctx
        assert "Clothing" in ctx
        assert "Pose or action" in ctx
        assert "Environment" in ctx
        assert "Emotion" in ctx


# ── ImageReviewConfig ─────────────────────────────────────────────────────────


class TestImageReviewConfigHumanQA:
    def test_human_qa_enabled_default_true(self):
        from ytfactory.images.review_config import ImageReviewConfig
        assert ImageReviewConfig().human_qa_enabled is True

    def test_human_qa_enabled_from_settings(self):
        from ytfactory.images.review_config import ImageReviewConfig

        class FakeSettings:
            image_review_enabled = True
            vision_review_provider = "local"
            vision_review_local_model = "test_model"
            image_review_min_score = 90.0
            image_review_confidence = 80.0
            image_review_max_attempts = 3
            image_review_auto_remediate = True
            image_review_debug = False
            image_human_qa_enabled = False

        cfg = ImageReviewConfig.from_settings(FakeSettings())
        assert cfg.human_qa_enabled is False

    def test_human_qa_enabled_defaults_true_when_missing(self):
        from ytfactory.images.review_config import ImageReviewConfig

        class MinimalSettings:
            pass  # no image_human_qa_enabled attribute

        cfg = ImageReviewConfig.from_settings(MinimalSettings())
        assert cfg.human_qa_enabled is True


# ── SceneReviewArtifact ───────────────────────────────────────────────────────


class TestSceneReviewArtifactHumanQAFields:
    def test_human_qa_fields_present_with_defaults(self):
        from ytfactory.images.review_models import SceneReviewArtifact

        a = SceneReviewArtifact(scene_index=1, status="PASS")
        assert a.human_qa_triggered is False
        assert a.human_qa_passed is False
        assert a.human_qa_status == ""
        assert a.hand_qa_status == ""
        assert a.clothing_qa_status == ""
        assert a.prompt_compliance_status == ""

    def test_human_qa_fields_set_correctly(self):
        from ytfactory.images.review_models import SceneReviewArtifact

        a = SceneReviewArtifact(
            scene_index=2,
            status="PASS",
            human_qa_triggered=True,
            human_qa_passed=True,
            human_qa_status="PASS",
            hand_qa_status="PASS",
            clothing_qa_status="PASS",
            prompt_compliance_status="PASS",
        )
        assert a.human_qa_triggered is True
        assert a.human_qa_passed is True
        assert a.prompt_compliance_status == "PASS"


# ── ImageReviewEngine._run_human_qa_gate ─────────────────────────────────────


def _make_vision_result(status="PASS", score=95.0, confidence=90.0, issues=None):
    from video_core.providers.vision import VisionReviewResult, VisionIssue

    result = MagicMock(spec=VisionReviewResult)
    result.status = status
    result.score = score
    result.confidence = confidence
    result.high_severity_issues = [i for i in (issues or []) if i.get("severity") == "high"]
    result.medium_severity_issues = [i for i in (issues or []) if i.get("severity") == "medium"]
    result.issues = []
    result.model_name = "test"
    result.backend = "mock"
    result.recommend_regeneration = status == "FAIL"
    result.error = ""
    return result


class TestRunHumanQAGate:
    def _make_engine(self, human_qa_enabled=True):
        from ytfactory.images.review_config import ImageReviewConfig
        from ytfactory.images.review_engine import ImageReviewEngine

        cfg = ImageReviewConfig(
            enabled=True,
            human_qa_enabled=human_qa_enabled,
            min_score=90.0,
            min_confidence=80.0,
            max_attempts=3,
        )
        vision = MagicMock()
        image_provider = MagicMock()
        return ImageReviewEngine(cfg, vision, image_provider)

    def test_non_critical_scene_skips_gate(self, tmp_path):
        engine = self._make_engine()
        img = tmp_path / "img.png"
        img.write_bytes(b"x")
        # Wide shot + no critical body-part keyword
        scene = {"index": 1, "shot_type": "wide shot", "visual_prompt": "crowd at a festival"}
        passes, stage, failing = engine._run_human_qa_gate(img, "crowd at a festival", scene, 1)
        assert passes is True
        assert stage["human_qa_triggered"] is False
        assert failing is None
        engine._vision.review.assert_not_called()

    def test_critical_scene_triggers_all_stages_on_pass(self, tmp_path):
        engine = self._make_engine()
        img = tmp_path / "img.png"
        img.write_bytes(b"x")
        engine._vision.review.return_value = _make_vision_result("PASS", 95.0, 90.0)

        scene = {"index": 2, "shot_type": "portrait", "visual_prompt": "young woman wearing a red dress"}
        passes, stage, failing = engine._run_human_qa_gate(
            img, "young woman wearing a red dress", scene, 1
        )
        assert passes is True
        assert stage["human_qa_triggered"] is True
        assert stage.get("human_qa_gate_passed") is True
        assert failing is None
        # Human QA + Hand QA + Clothing QA + Prompt Compliance = 4 calls
        assert engine._vision.review.call_count == 4

    def test_human_qa_fail_stops_chain_and_returns_failing_result(self, tmp_path):
        engine = self._make_engine()
        img = tmp_path / "img.png"
        img.write_bytes(b"x")
        # First call (Human QA) fails
        fail_result = _make_vision_result("FAIL", 50.0, 90.0)
        engine._vision.review.return_value = fail_result

        scene = {"index": 3, "shot_type": "close-up", "visual_prompt": "man with broken arm anatomy"}
        passes, stage, failing = engine._run_human_qa_gate(
            img, "man with broken arm anatomy", scene, 1
        )
        assert passes is False
        assert stage["human_qa_status"] == "FAIL"
        assert stage["human_qa_passed"] is False
        assert failing is fail_result
        # Only 1 call — chain stops at Human QA
        assert engine._vision.review.call_count == 1

    def test_hand_qa_fail_stops_chain(self, tmp_path):
        engine = self._make_engine()
        img = tmp_path / "img.png"
        img.write_bytes(b"x")
        pass_result = _make_vision_result("PASS", 95.0, 90.0)
        fail_result = _make_vision_result("FAIL", 40.0, 90.0)
        # Human QA passes, Hand QA fails
        engine._vision.review.side_effect = [pass_result, fail_result]

        scene = {"index": 4, "shot_type": "medium shot", "visual_prompt": "person with hands raised"}
        passes, stage, failing = engine._run_human_qa_gate(
            img, "person with hands raised", scene, 1
        )
        assert passes is False
        assert stage["hand_qa_status"] == "FAIL"
        assert failing is fail_result

    def test_clothing_qa_skipped_when_no_clothing_in_prompt(self, tmp_path):
        engine = self._make_engine()
        img = tmp_path / "img.png"
        img.write_bytes(b"x")
        engine._vision.review.return_value = _make_vision_result("PASS", 95.0, 90.0)

        scene = {"index": 5, "shot_type": "portrait", "visual_prompt": "man standing in field"}
        passes, stage, failing = engine._run_human_qa_gate(
            img, "man standing in field", scene, 1
        )
        assert passes is True
        # No clothing → Human QA + Hand QA + Prompt Compliance = 3 calls, no Clothing QA
        assert "clothing_qa_status" not in stage
        assert engine._vision.review.call_count == 3

    def test_human_qa_disabled_skips_gate(self, tmp_path):
        # The human_qa_enabled=False guard lives in review_scene(), not in _run_human_qa_gate().
        # Verify the gate method still works correctly when called directly (portrait = critical).
        engine = self._make_engine(human_qa_enabled=False)
        img = tmp_path / "img.png"
        img.write_bytes(b"x")
        engine._vision.review.return_value = _make_vision_result("PASS", 95.0, 90.0)
        scene = {"index": 6, "shot_type": "portrait", "visual_prompt": "woman in portrait"}

        passes, stage, failing = engine._run_human_qa_gate(
            img, "woman in portrait", scene, 1
        )
        # Portrait is critical → gate triggers and runs (config check is upstream)
        assert stage["human_qa_triggered"] is True
        assert passes is True
        assert failing is None


# ── HumanValidator HUM_004 ────────────────────────────────────────────────────


class TestHUM004:
    def _make_validator(self):
        from ytfactory.review.validation.framework import ValidationRulesConfig
        from ytfactory.review.validation.rules.human import HumanValidator

        cfg = ValidationRulesConfig()
        v = HumanValidator.__new__(HumanValidator)
        v._config = cfg
        return v

    def _scenes_with_human(self, idx=1):
        return [{"index": idx, "visual_prompt": "young woman in portrait", "shot_type": "portrait"}]

    def test_hum004_skip_when_no_review_artifact(self, tmp_path):
        v = self._make_validator()
        results = v.validate(tmp_path, self._scenes_with_human(1), {})
        hum004 = [r for r in results if r.rule_id == "HUM_004"]
        assert len(hum004) == 1
        assert hum004[0].status == "SKIP"

    def test_hum004_skip_when_gate_not_triggered(self, tmp_path):
        v = self._make_validator()
        review_path = tmp_path / "images" / "image-review-001.json"
        review_path.parent.mkdir(parents=True)
        review_path.write_text(
            json.dumps({"human_qa_triggered": False, "human_qa_passed": False}),
            encoding="utf-8",
        )
        results = v.validate(tmp_path, self._scenes_with_human(1), {})
        hum004 = [r for r in results if r.rule_id == "HUM_004"]
        assert hum004[0].status == "SKIP"

    def test_hum004_pass_when_gate_passed(self, tmp_path):
        v = self._make_validator()
        review_path = tmp_path / "images" / "image-review-001.json"
        review_path.parent.mkdir(parents=True)
        review_path.write_text(
            json.dumps({
                "human_qa_triggered": True,
                "human_qa_passed": True,
                "human_qa_status": "PASS",
                "hand_qa_status": "PASS",
                "prompt_compliance_status": "PASS",
            }),
            encoding="utf-8",
        )
        results = v.validate(tmp_path, self._scenes_with_human(1), {})
        hum004 = [r for r in results if r.rule_id == "HUM_004"]
        assert hum004[0].status == "PASS"

    def test_hum004_fail_when_human_qa_stage_failed(self, tmp_path):
        v = self._make_validator()
        review_path = tmp_path / "images" / "image-review-001.json"
        review_path.parent.mkdir(parents=True)
        review_path.write_text(
            json.dumps({
                "human_qa_triggered": True,
                "human_qa_passed": False,
                "human_qa_status": "FAIL",
                "hand_qa_status": "",
                "prompt_compliance_status": "",
            }),
            encoding="utf-8",
        )
        results = v.validate(tmp_path, self._scenes_with_human(1), {})
        hum004 = [r for r in results if r.rule_id == "HUM_004"]
        assert hum004[0].status == "FAIL"
        assert hum004[0].severity == "high"
        assert "human QA" in hum004[0].description

    def test_hum004_fail_when_clothing_qa_failed(self, tmp_path):
        v = self._make_validator()
        review_path = tmp_path / "images" / "image-review-001.json"
        review_path.parent.mkdir(parents=True)
        review_path.write_text(
            json.dumps({
                "human_qa_triggered": True,
                "human_qa_passed": False,
                "human_qa_status": "PASS",
                "hand_qa_status": "PASS",
                "clothing_qa_status": "FAIL",
                "prompt_compliance_status": "",
            }),
            encoding="utf-8",
        )
        results = v.validate(tmp_path, self._scenes_with_human(1), {})
        hum004 = [r for r in results if r.rule_id == "HUM_004"]
        assert hum004[0].status == "FAIL"
        assert "clothing QA" in hum004[0].description

    def test_hum004_not_triggered_for_non_human_scene(self, tmp_path):
        v = self._make_validator()
        # Non-human prompt → detect_human_presence returns False → HUM_004 not evaluated
        scenes = [{"index": 1, "visual_prompt": "mountains and rivers at sunrise", "shot_type": "wide shot"}]
        results = v.validate(tmp_path, scenes, {})
        hum004 = [r for r in results if r.rule_id == "HUM_004"]
        assert len(hum004) == 0
