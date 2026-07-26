"""Tests for docs/script/task-2.7-narrative-visual-bridge.md.

Narrative-visual bridge: a batch LLM pass derives a concrete visual_anchor
per scene from its narration before prompt generation, so abstract/
empty-chars scenes get a specific literal directive instead of drifting to
generic "spiritual documentary aesthetic object" imagery.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ytfactory.agents.nodes.scene_planner import (
    _build_anchor_batch_prompt,
    _build_visual_anchors,
)
from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt
from ytfactory.config.settings import Settings


class TestBuildAnchorBatchPrompt:
    def test_brand_card_excluded_from_anchor_batch(self):
        scenes = [
            {"index": 28, "narration": "content narration", "scene_type": "generated_image"},
            {"index": 29, "narration": "Brand Card", "scene_type": "brand_card"},
        ]
        prompt = _build_anchor_batch_prompt(scenes)
        assert "Scene 029" not in prompt
        assert "Scene 028" in prompt

    def test_few_shot_examples_present(self):
        prompt = _build_anchor_batch_prompt([{"index": 1, "narration": "test", "scene_type": "generated_image"}])
        assert "EXAMPLES" in prompt
        assert "potter's wheel" in prompt

    def test_forbids_generic_spiritual_objects(self):
        prompt = _build_anchor_batch_prompt([{"index": 1, "narration": "test", "scene_type": "generated_image"}])
        assert "journal, candle, stone, sandal" in prompt


class TestBuildVisualAnchors:
    def _mock_llm(self, response_text: str) -> MagicMock:
        llm = MagicMock()
        llm.generate.return_value = MagicMock(text=response_text)
        return llm

    def test_visual_anchor_batch_returns_per_scene(self):
        scenes = [
            {"index": 1, "narration": "parents smiling, children smile", "scene_type": "generated_image"},
            {"index": 2, "narration": "eagle soared in open sky", "scene_type": "generated_image"},
        ]
        llm = self._mock_llm(
            json.dumps(
                {
                    "001": "A mother kneeling to her child at dawn, both smiling",
                    "002": "An eagle in full flight, wings spread against open sky",
                }
            )
        )
        anchors = _build_visual_anchors(scenes, llm)
        assert 1 in anchors
        assert 2 in anchors
        assert isinstance(anchors[1], str)
        assert len(anchors[1]) > 10

    def test_parse_failure_returns_empty_dict(self):
        llm = self._mock_llm("not valid json")
        anchors = _build_visual_anchors(
            [{"index": 1, "narration": "test", "scene_type": "generated_image"}], llm
        )
        assert anchors == {}

    def test_exception_returns_empty_dict(self):
        llm = MagicMock()
        llm.generate.side_effect = RuntimeError("network error")
        anchors = _build_visual_anchors(
            [{"index": 1, "narration": "test", "scene_type": "generated_image"}], llm
        )
        assert anchors == {}

    def test_non_string_values_filtered_out(self):
        llm = self._mock_llm(json.dumps({"001": "a valid anchor sentence here", "002": 123, "003": ""}))
        anchors = _build_visual_anchors(
            [
                {"index": 1, "narration": "n1", "scene_type": "generated_image"},
                {"index": 2, "narration": "n2", "scene_type": "generated_image"},
                {"index": 3, "narration": "n3", "scene_type": "generated_image"},
            ],
            llm,
        )
        assert anchors == {1: "a valid anchor sentence here"}

    def test_uses_json_mode(self):
        llm = self._mock_llm(json.dumps({"001": "anchor sentence text"}))
        _build_visual_anchors([{"index": 1, "narration": "n", "scene_type": "generated_image"}], llm)
        assert llm.generate.call_args.kwargs.get("json_mode") is True


class TestAnchorInjectedIntoPrompt:
    def test_visual_anchor_injected_into_prompt(self):
        prompt = build_visual_prompts_prompt(
            [
                {
                    "index": 1,
                    "narration": "test narration",
                    "shot_type": "wide shot",
                    "visual_anchor": "A parent smiling at a child",
                }
            ],
            style=None,
        )
        assert "A parent smiling at a child" in prompt
        assert "REQUIRED VISUAL" in prompt

    def test_narration_always_in_prompt(self):
        prompt = build_visual_prompts_prompt(
            [{"index": 1, "narration": "test narration text", "shot_type": "wide shot"}],
            style=None,
        )
        assert "test narration text" in prompt
        assert "NARRATION FOR THIS SCENE" in prompt

    def test_anchor_missing_does_not_break(self):
        prompt = build_visual_prompts_prompt(
            [{"index": 1, "narration": "test", "shot_type": "wide shot", "visual_anchor": ""}],
            style=None,
        )
        assert prompt
        assert "REQUIRED VISUAL" not in prompt


class TestVisualAnchorSettingsGate:
    def test_visual_anchor_enabled_default_true(self):
        assert Settings().visual_anchor_enabled is True

    def test_visual_anchor_enabled_false(self):
        assert Settings(visual_anchor_enabled=False).visual_anchor_enabled is False
