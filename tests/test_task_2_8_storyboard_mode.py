"""Tests for docs/script/task-2.8-storyboard-mode.md.

Storyboard Mode + Strict Scene Fidelity blocks prepended to the generation
template (position 0), and the condensed STORYBOARD_HEADER prepended to every
non-brand-card visual_prompt written to image_prompts_manifest.json and
IMAGE_PROMPTS.md — the manual-image-gen output path never sees the generation
template, so the instruction has to travel with the prompt text itself.
"""

from __future__ import annotations

import json

from ytfactory.agents.prompts.scene_planner import (
    _VISUAL_PROMPTS_TEMPLATE,
    build_visual_prompts_prompt,
    prepend_storyboard_header,
)


class TestTemplateOrdering:
    def test_storyboard_mode_first_in_template(self):
        assert _VISUAL_PROMPTS_TEMPLATE.strip().startswith("STORYBOARD MODE")

    def test_storyboard_before_fidelity_before_absolute_constraints(self):
        storyboard_pos = _VISUAL_PROMPTS_TEMPLATE.index("STORYBOARD MODE")
        fidelity_pos = _VISUAL_PROMPTS_TEMPLATE.index("STRICT SCENE FIDELITY")
        constraints_pos = _VISUAL_PROMPTS_TEMPLATE.index("⚠ ABSOLUTE CONSTRAINTS")
        assert storyboard_pos < fidelity_pos < constraints_pos

    def test_anchor_and_narration_follow_the_two_new_blocks(self):
        """REQUIRED VISUAL / NARRATION FOR THIS SCENE are injected per-scene
        (in the scene list, near the end) — they must still land after both
        new header blocks in the fully-built prompt."""
        prompt = build_visual_prompts_prompt(
            [{"index": 1, "narration": "test", "shot_type": "wide shot", "visual_anchor": "A single anchor"}],
            style=None,
        )
        storyboard_pos = prompt.index("STORYBOARD MODE")
        fidelity_pos = prompt.index("STRICT SCENE FIDELITY")
        anchor_pos = prompt.index("REQUIRED VISUAL")
        narration_pos = prompt.index("NARRATION FOR THIS SCENE")
        assert storyboard_pos < fidelity_pos < anchor_pos
        assert storyboard_pos < fidelity_pos < narration_pos

    def test_omit_rather_than_invent_present(self):
        assert "omit rather than invent" in _VISUAL_PROMPTS_TEMPLATE

    def test_independent_storyboard_frame_present(self):
        assert "independent storyboard frame" in _VISUAL_PROMPTS_TEMPLATE

    def test_single_source_of_truth_present(self):
        assert "single source of truth" in _VISUAL_PROMPTS_TEMPLATE

    def test_narration_context_only_present(self):
        assert "emotional context only" in _VISUAL_PROMPTS_TEMPLATE


class TestPrependStoryboardHeader:
    def test_prepends_header(self):
        result = prepend_storyboard_header("A cliff at dawn.")
        assert result.startswith("16:9 aspect ratio. Storyboard Mode")
        assert result.endswith("A cliff at dawn.")

    def test_idempotent(self):
        prompt = "16:9 aspect ratio. Storyboard Mode. Already has header. Some scene content."
        result = prepend_storyboard_header(prompt)
        assert result.count("Storyboard Mode") == 1
        assert result == prompt


class TestDownstreamOutputs:
    def test_manifest_prepends_header_to_non_brand_card(self, tmp_path, monkeypatch):
        from ytfactory.two_phase.pipeline import TwoPhasePipeline

        project_id = "proj"
        project_dir = tmp_path / "workspace" / "jobs" / project_id
        (project_dir / "scenes").mkdir(parents=True)
        (project_dir / "images").mkdir(parents=True)
        scene_plan = {
            "scenes": [
                {"index": 1, "visual_prompt": "A cliff at dawn.", "scene_type": "generated_image"},
                {"index": 2, "visual_prompt": "Brand Card prompt", "scene_type": "brand_card"},
            ]
        }
        (project_dir / "scenes" / "scene-plan.json").write_text(json.dumps(scene_plan), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("ytfactory.two_phase.pipeline.WORKSPACE_DIR", "workspace/jobs")

        pipeline = TwoPhasePipeline.__new__(TwoPhasePipeline)
        pipeline._write_image_prompts_manifest(project_id)

        manifest = json.loads((project_dir / "image_prompts_manifest.json").read_text())
        scenes = {s["scene_id"]: s for s in manifest["scenes"]}
        assert scenes[1]["visual_prompt"].startswith("16:9 aspect ratio. Storyboard Mode")
        assert not scenes[2]["visual_prompt"].startswith("16:9 aspect ratio. Storyboard Mode")

    def test_image_prompts_md_prepends_header_to_non_brand_card(self, tmp_path, monkeypatch):
        from ytfactory.agents.nodes.scene_planner import _write_prompts_file
        from ytfactory.config.settings import Settings

        monkeypatch.chdir(tmp_path)
        project_id = "proj"
        scenes = [
            {"index": 1, "title": "t", "narration": "n", "visual_prompt": "A cliff at dawn.", "scene_type": "generated_image"},
            {"index": 2, "title": "Brand Card", "narration": "n", "visual_prompt": "Brand Card prompt", "scene_type": "brand_card"},
        ]
        _write_prompts_file(project_id, scenes, None, Settings())

        content = (tmp_path / "workspace" / "jobs" / project_id / "images" / "IMAGE_PROMPTS.md").read_text()
        assert "> 16:9 aspect ratio. Storyboard Mode." in content
        assert "> Brand Card prompt" in content
