"""Tests for docs/script/task-2.10-phase1.5-image-qa.md.

verify_scene()/verify_all_scenes() use the real VisionProvider.review()
interface (status/recommend_regeneration/issues), not the doc's fictional
vision_client.verify(image_b64=...) — see module docstring in verify.py.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ytfactory.images.verify import (
    QADecision,
    SceneQAResult,
    _parse_qa_response,
    verify_all_scenes,
    verify_scene,
    write_qa_report,
)
from ytfactory.two_phase.pipeline import IMAGE_GENERATION_RULES_V2


class TestParseQaResponse:
    def test_parse_keep_response(self):
        decision, reasons = _parse_qa_response("KEEP")
        assert decision == QADecision.KEEP
        assert reasons == []

    def test_parse_regenerate_response(self):
        response = "REGENERATE\nReasons:\n- Wrong shot type\n- Missing subject"
        decision, reasons = _parse_qa_response(response)
        assert decision == QADecision.REGENERATE
        assert len(reasons) == 2
        assert "Wrong shot type" in reasons[0]

    def test_parse_regenerate_caps_at_three_reasons(self):
        response = "REGENERATE\n- a\n- b\n- c\n- d"
        _, reasons = _parse_qa_response(response)
        assert len(reasons) == 3

    def test_parse_ambiguous_defaults_to_keep(self):
        decision, reasons = _parse_qa_response("I think this looks okay")
        assert decision == QADecision.KEEP
        assert reasons == []


def _mock_vision_result(status="PASS", recommend=False, issues=None, error=""):
    result = MagicMock()
    result.status = status
    result.recommend_regeneration = recommend
    result.issues = issues or []
    result.error = error
    return result


class TestVerifyScene:
    def test_missing_image_returns_missing(self, tmp_path):
        scene = {
            "scene_id": 1, "expected_filename": "scene-001.png",
            "visual_prompt": "test", "shot_type": "wide", "scene_type": "generated_image",
        }
        result = verify_scene(scene, tmp_path, MagicMock())
        assert result.decision == QADecision.MISSING

    def test_tiny_image_file_returns_missing(self, tmp_path):
        (tmp_path / "scene-001.png").write_bytes(b"x")
        scene = {
            "scene_id": 1, "expected_filename": "scene-001.png",
            "visual_prompt": "test", "shot_type": "wide", "scene_type": "generated_image",
        }
        result = verify_scene(scene, tmp_path, MagicMock())
        assert result.decision == QADecision.MISSING

    def test_brand_card_skipped(self, tmp_path):
        scene = {
            "scene_id": 30, "expected_filename": "scene-030.png",
            "visual_prompt": "Brand Card", "shot_type": "wide", "scene_type": "brand_card",
        }
        result = verify_scene(scene, tmp_path, MagicMock())
        assert result.decision == QADecision.KEEP

    def test_qa_error_defaults_to_keep(self, tmp_path):
        (tmp_path / "scene-001.png").write_bytes(b"x" * 2000)
        scene = {
            "scene_id": 1, "expected_filename": "scene-001.png",
            "visual_prompt": "test", "shot_type": "wide", "scene_type": "generated_image",
        }
        failing_provider = MagicMock()
        failing_provider.review.side_effect = RuntimeError("model crashed")
        result = verify_scene(scene, tmp_path, failing_provider)
        assert result.decision == QADecision.KEEP

    def test_recommend_regeneration_maps_to_regenerate(self, tmp_path):
        (tmp_path / "scene-001.png").write_bytes(b"x" * 2000)
        scene = {
            "scene_id": 1, "expected_filename": "scene-001.png",
            "visual_prompt": "test", "shot_type": "wide", "scene_type": "generated_image",
        }
        issue = MagicMock(description="Wrong shot type")
        provider = MagicMock()
        provider.review.return_value = _mock_vision_result(status="FAIL", recommend=True, issues=[issue])
        result = verify_scene(scene, tmp_path, provider)
        assert result.decision == QADecision.REGENERATE
        assert result.reasons == ["Wrong shot type"]

    def test_pass_maps_to_keep(self, tmp_path):
        (tmp_path / "scene-001.png").write_bytes(b"x" * 2000)
        scene = {
            "scene_id": 1, "expected_filename": "scene-001.png",
            "visual_prompt": "test", "shot_type": "wide", "scene_type": "generated_image",
        }
        provider = MagicMock()
        provider.review.return_value = _mock_vision_result(status="PASS", recommend=False)
        result = verify_scene(scene, tmp_path, provider)
        assert result.decision == QADecision.KEEP


class TestVerifyAllScenes:
    def test_scene_filter(self, tmp_path, capsys):
        manifest = {
            "scenes": [
                {"scene_id": 1, "expected_filename": "scene-001.png", "visual_prompt": "a", "shot_type": "wide", "scene_type": "generated_image"},
                {"scene_id": 2, "expected_filename": "scene-002.png", "visual_prompt": "b", "shot_type": "wide", "scene_type": "generated_image"},
            ]
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        results = verify_all_scenes(manifest_path, tmp_path, MagicMock(), scene_filter=[1])
        assert len(results) == 1
        assert results[0].scene_id == 1


class TestWriteQaReport:
    def test_write_qa_report_structure(self, tmp_path):
        results = [
            SceneQAResult(1, "scene-001.png", QADecision.KEEP, [], "", ""),
            SceneQAResult(2, "scene-002.png", QADecision.REGENERATE, ["wrong subject"], "", ""),
        ]
        report = write_qa_report(results, tmp_path / "report.json")
        assert report["summary"]["keep"] == 1
        assert report["summary"]["regenerate"] == 1
        assert (tmp_path / "report.json").is_file()


class TestImageGenerationRulesV2:
    def test_contains_storyboard_mode_markers(self):
        assert "Storyboard Mode" in IMAGE_GENERATION_RULES_V2
        assert "single source of truth" in IMAGE_GENERATION_RULES_V2
        assert "omit rather than invent" in IMAGE_GENERATION_RULES_V2

    def test_written_by_manifest_writer(self, tmp_path, monkeypatch):
        from ytfactory.two_phase.pipeline import TwoPhasePipeline

        project_id = "proj"
        project_dir = tmp_path / "workspace" / "jobs" / project_id
        (project_dir / "scenes").mkdir(parents=True)
        (project_dir / "images").mkdir(parents=True)
        scene_plan = {"scenes": [{"index": 1, "visual_prompt": "x", "scene_type": "generated_image"}]}
        (project_dir / "scenes" / "scene-plan.json").write_text(json.dumps(scene_plan), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("ytfactory.two_phase.pipeline.WORKSPACE_DIR", "workspace/jobs")

        pipeline = TwoPhasePipeline.__new__(TwoPhasePipeline)
        pipeline._write_image_prompts_manifest(project_id)

        rules_content = (project_dir / "image_generation_rules.md").read_text()
        assert "Storyboard Mode" in rules_content
