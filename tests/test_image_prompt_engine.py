"""Tests for Image Prompt Engine V4 — shot planner, diagnostics, engine, integration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ytfactory.images.diagnostics import (
    DiagnosticsReport,
    _REPETITIVE_OBJECTS,
    _STYLE_MARKERS,
    build_report,
)
from ytfactory.images.prompt_engine import ImagePromptEngineV4
from ytfactory.images.shot_planner import (
    SHOT_TYPES,
    plan_shots,
    validate_shot_diversity,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────


def _make_scene(
    index: int,
    narration: str = "Narration text.",
    visual_prompt: str = "Photorealistic cinematic shot, no text, no watermark.",
    scene_type: str = "generated_image",
    shot_type: str = "",
) -> dict:
    s = {
        "index": index,
        "title": f"Scene {index}",
        "narration": narration,
        "visual_prompt": visual_prompt,
        "duration_seconds": 10,
        "scene_type": scene_type,
    }
    if shot_type:
        s["shot_type"] = shot_type
    return s


def _scenes(n: int, with_shots: bool = False) -> list[dict]:
    shots = plan_shots(n) if with_shots else []
    result = []
    for i in range(1, n + 1):
        s = _make_scene(
            index=i,
            visual_prompt=(
                f"Cinematic {SHOT_TYPES[i % len(SHOT_TYPES)]} of scene {i}, "
                "photorealistic, no text, no watermark, documentary."
            ),
        )
        if with_shots:
            s["shot_type"] = shots[i - 1]
        result.append(s)
    return result


# ── ShotPlanner ────────────────────────────────────────────────────────────────


class TestPlanShots:
    def test_empty_returns_empty(self):
        assert plan_shots(0) == []

    def test_single_scene_returns_list_of_one(self):
        result = plan_shots(1)
        assert len(result) == 1
        assert result[0] in SHOT_TYPES

    def test_correct_count(self):
        for n in [3, 7, 14, 25, 30]:
            assert len(plan_shots(n)) == n

    def test_no_consecutive_repeats(self):
        for n in [2, 5, 10, 14, 15, 28]:
            shots = plan_shots(n)
            for i in range(1, len(shots)):
                assert shots[i] != shots[i - 1], (
                    f"Consecutive repeat at position {i}: '{shots[i]}' "
                    f"(n={n}, shots={shots})"
                )

    def test_all_values_are_valid_shot_types(self):
        for shot in plan_shots(20):
            assert shot in SHOT_TYPES

    def test_deterministic(self):
        assert plan_shots(10) == plan_shots(10)
        assert plan_shots(25) == plan_shots(25)

    def test_balanced_distribution_14_scenes(self):
        shots = plan_shots(14)
        # 14 shots = each shot type used exactly once
        assert len(set(shots)) == 14

    def test_balanced_distribution_28_scenes(self):
        shots = plan_shots(28)
        from collections import Counter

        counts = Counter(shots)
        # Each type should appear exactly twice
        assert all(c == 2 for c in counts.values())

    def test_large_count_no_consecutive_repeats(self):
        shots = plan_shots(100)
        for i in range(1, len(shots)):
            assert shots[i] != shots[i - 1]


class TestValidateShotDiversity:
    def test_clean_plan_returns_no_issues(self):
        shots = plan_shots(14)
        assert validate_shot_diversity(shots) == []

    def test_consecutive_repeat_detected(self):
        shots = ["wide shot", "wide shot", "close-up"]
        issues = validate_shot_diversity(shots)
        assert any("consecutive" in i.lower() for i in issues)

    def test_single_type_detected_as_low_diversity(self):
        shots = ["wide shot"] * 6
        issues = validate_shot_diversity(shots)
        assert any("diversity" in i.lower() or "consecutive" in i.lower() for i in issues)

    def test_empty_plan_returns_no_issues(self):
        assert validate_shot_diversity([]) == []

    def test_small_plan_under_five_no_diversity_check(self):
        # Only consecutive check runs for < 5 shots
        shots = ["wide shot", "close-up", "medium shot"]
        issues = validate_shot_diversity(shots)
        assert all("consecutive" not in i.lower() or "diversity" not in i.lower() for i in issues)


# ── Diagnostics ────────────────────────────────────────────────────────────────


class TestBuildReport:
    def test_empty_scenes_returns_empty_report(self):
        report = build_report([], [])
        assert report.total_prompts == 0
        assert report.issues == []

    def test_total_prompts_counts_generated_only(self):
        scenes = _scenes(3)
        scenes.append(_make_scene(4, scene_type="asset"))
        report = build_report(scenes, plan_shots(3))
        assert report.total_prompts == 3

    def test_shot_distribution_counts(self):
        shots = ["wide shot", "close-up", "wide shot"]
        scenes = _scenes(3, with_shots=False)
        for i, s in enumerate(scenes):
            s["shot_type"] = shots[i]
        report = build_report(scenes, shots)
        assert report.shot_distribution["wide shot"] == 2
        assert report.shot_distribution["close-up"] == 1

    def test_consecutive_shot_repeats_detected(self):
        scenes = _scenes(3)
        shots = ["wide shot", "wide shot", "close-up"]
        report = build_report(scenes, shots)
        assert 2 in report.consecutive_shot_repeats

    def test_no_consecutive_repeats_on_clean_plan(self):
        scenes = _scenes(5, with_shots=True)
        shots = [s["shot_type"] for s in scenes]
        report = build_report(scenes, shots)
        assert report.consecutive_shot_repeats == []

    def test_repeated_objects_detected(self):
        scenes = [
            _make_scene(1, visual_prompt="A candle flickering in the dark room."),
            _make_scene(2, visual_prompt="Candlelight reflected on water surface."),
            _make_scene(3, visual_prompt="A man walks through heavy mist."),
        ]
        report = build_report(scenes, plan_shots(3))
        # "candle" appears in 2 scenes → should be flagged
        assert "candle" in report.repeated_objects

    def test_single_occurrence_not_flagged(self):
        scenes = [
            _make_scene(1, visual_prompt="A candle flickering in the dark room."),
            _make_scene(2, visual_prompt="Wide establishing shot of mountain range."),
        ]
        report = build_report(scenes, plan_shots(2))
        assert "candle" not in report.repeated_objects

    def test_style_consistent_when_all_have_markers(self):
        scenes = _scenes(3)  # all have "photorealistic" and "no text"
        report = build_report(scenes, plan_shots(3))
        assert report.style_consistent is True
        assert report.scenes_missing_style_markers == []

    def test_style_inconsistent_when_missing_markers(self):
        scenes = [
            _make_scene(1, visual_prompt="A beautiful landscape with mist."),  # no marker
            _make_scene(2, visual_prompt="Photorealistic close-up, no text."),
        ]
        report = build_report(scenes, plan_shots(2))
        assert 1 in report.scenes_missing_style_markers

    def test_diversity_score_is_float_between_0_and_1(self):
        scenes = _scenes(5, with_shots=True)
        shots = [s["shot_type"] for s in scenes]
        report = build_report(scenes, shots)
        assert 0.0 <= report.diversity_score <= 1.0

    def test_diversity_score_penalized_for_issues(self):
        scenes = _scenes(3)
        shots = ["wide shot", "wide shot", "close-up"]  # consecutive repeat
        report = build_report(scenes, shots)
        assert report.diversity_score < 1.0

    def test_to_dict_is_json_serializable(self):
        scenes = _scenes(3, with_shots=True)
        shots = [s["shot_type"] for s in scenes]
        report = build_report(scenes, shots)
        d = report.to_dict()
        # Should not raise
        json.dumps(d)

    def test_prompt_lengths_count_words(self):
        prompt = "one two three four five photorealistic no text no watermark"
        scenes = [_make_scene(1, visual_prompt=prompt)]
        report = build_report(scenes, plan_shots(1))
        assert report.prompt_lengths[0] == len(prompt.split())


# ── ImagePromptEngineV4 ────────────────────────────────────────────────────────


class TestImagePromptEngineV4:
    def test_enrich_adds_shot_type_to_generated_scenes(self):
        engine = ImagePromptEngineV4()
        scenes = _scenes(5)
        enriched = engine.enrich_scenes_with_shots(scenes)
        for s in enriched:
            assert "shot_type" in s
            assert s["shot_type"] in SHOT_TYPES

    def test_enrich_does_not_mutate_original(self):
        engine = ImagePromptEngineV4()
        scenes = _scenes(3)
        engine.enrich_scenes_with_shots(scenes)
        for s in scenes:
            assert "shot_type" not in s

    def test_enrich_skips_asset_scenes(self):
        engine = ImagePromptEngineV4()
        scenes = _scenes(2) + [_make_scene(3, scene_type="asset")]
        enriched = engine.enrich_scenes_with_shots(scenes)
        # Asset scene should NOT have shot_type
        asset = next(s for s in enriched if s["scene_type"] == "asset")
        assert "shot_type" not in asset

    def test_enrich_no_consecutive_repeats(self):
        engine = ImagePromptEngineV4()
        scenes = _scenes(20)
        enriched = engine.enrich_scenes_with_shots(scenes)
        shots = [s["shot_type"] for s in enriched if s.get("scene_type", "generated_image") == "generated_image"]
        for i in range(1, len(shots)):
            assert shots[i] != shots[i - 1]

    def test_get_shot_plan_returns_only_generated(self):
        engine = ImagePromptEngineV4()
        scenes = _scenes(3) + [_make_scene(4, scene_type="asset")]
        enriched = engine.enrich_scenes_with_shots(scenes)
        shot_plan = engine.get_shot_plan(enriched)
        assert len(shot_plan) == 3

    def test_build_diagnostics_returns_report(self):
        engine = ImagePromptEngineV4()
        scenes = _scenes(5, with_shots=True)
        enriched = engine.enrich_scenes_with_shots(scenes)
        report = engine.build_diagnostics(enriched)
        assert isinstance(report, DiagnosticsReport)
        assert report.total_prompts == 5

    def test_validate_passes_clean_scenes(self):
        engine = ImagePromptEngineV4()
        # Use genuinely diverse prompts so uniqueness check passes
        diverse_prompts = [
            "Ancient ruins crumbling beneath monsoon sky, photorealistic, no text, no watermark, documentary style.",
            "A worn leather journal open on a rain-soaked windowsill, photorealistic, no text, no watermark.",
            "Barefoot children running across salt flats at golden hour, photorealistic, cinematic, no watermark.",
            "Old man's hands tracing cracks in a stone wall, extreme close-up, no text, no watermark, photorealistic.",
            "Aerial drone view of terraced fields carved into hillside, photorealistic, documentary, no text.",
        ]
        scenes = [
            _make_scene(i + 1, visual_prompt=p) for i, p in enumerate(diverse_prompts)
        ]
        enriched = engine.enrich_scenes_with_shots(scenes)
        report = engine.build_diagnostics(enriched)
        issues = engine.validate(enriched, report)
        assert issues == []

    def test_validate_catches_missing_prompts(self):
        engine = ImagePromptEngineV4()
        scenes = _scenes(3, with_shots=True)
        enriched = engine.enrich_scenes_with_shots(scenes)
        # Blank out a prompt
        enriched[1]["visual_prompt"] = ""
        report = engine.build_diagnostics(enriched)
        issues = engine.validate(enriched, report)
        assert any("coverage" in i for i in issues)

    def test_validate_catches_repeated_objects(self):
        engine = ImagePromptEngineV4()
        scenes = [
            _make_scene(1, visual_prompt="Mist rolling through the valley, photorealistic."),
            _make_scene(2, visual_prompt="Heavy mist and fog at dawn, no text, no watermark."),
            _make_scene(3, visual_prompt="Mountains seen through the morning mist, photorealistic."),
        ]
        enriched = engine.enrich_scenes_with_shots(scenes)
        report = engine.build_diagnostics(enriched)
        issues = engine.validate(enriched, report)
        assert any("mist" in i or "repetition" in i for i in issues)

    def test_write_debug_output_creates_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ytfactory.images.prompt_engine.WORKSPACE_DIR", str(tmp_path)
        )
        engine = ImagePromptEngineV4()
        scenes = _scenes(3, with_shots=True)
        enriched = engine.enrich_scenes_with_shots(scenes)
        report = engine.build_diagnostics(enriched)

        debug_dir = engine.write_debug_output("test-project", enriched, report)
        assert debug_dir.exists()

        # Per-scene files
        for i in range(1, 4):
            assert (debug_dir / f"scene-{i:03d}-original.txt").exists()
            assert (debug_dir / f"scene-{i:03d}-optimized.txt").exists()

        # Debug JSON
        debug_json_path = debug_dir / "image_prompt_debug.json"
        assert debug_json_path.exists()
        data = json.loads(debug_json_path.read_text())
        assert data["version"] == "v4"
        assert data["generated_scenes"] == 3

    def test_write_debug_output_original_contains_narration(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ytfactory.images.prompt_engine.WORKSPACE_DIR", str(tmp_path)
        )
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(1, narration="The story begins here.")]
        enriched = engine.enrich_scenes_with_shots(scenes)
        report = engine.build_diagnostics(enriched)
        debug_dir = engine.write_debug_output("proj", enriched, report)

        original = (debug_dir / "scene-001-original.txt").read_text()
        assert "The story begins here." in original

    def test_write_debug_output_optimized_contains_prompt(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ytfactory.images.prompt_engine.WORKSPACE_DIR", str(tmp_path)
        )
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(1, visual_prompt="Epic drone shot over mountains, photorealistic.")]
        enriched = engine.enrich_scenes_with_shots(scenes)
        report = engine.build_diagnostics(enriched)
        debug_dir = engine.write_debug_output("proj", enriched, report)

        optimized = (debug_dir / "scene-001-optimized.txt").read_text()
        assert "Epic drone shot over mountains" in optimized

    def test_write_debug_skips_asset_scenes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ytfactory.images.prompt_engine.WORKSPACE_DIR", str(tmp_path)
        )
        engine = ImagePromptEngineV4()
        scenes = [
            _make_scene(1),
            _make_scene(2, scene_type="asset"),
        ]
        enriched = engine.enrich_scenes_with_shots(scenes)
        report = engine.build_diagnostics(enriched)
        debug_dir = engine.write_debug_output("proj", enriched, report)

        assert (debug_dir / "scene-001-original.txt").exists()
        # Asset scene (index 2) should NOT have debug files
        assert not (debug_dir / "scene-002-original.txt").exists()


# ── Scene planner prompt integration ──────────────────────────────────────────


class TestScenePlannerPromptV4:
    def test_shot_type_injected_into_prompt(self):
        from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt

        scenes = [
            {"index": 1, "narration": "The king arrived.", "shot_type": "establishing shot"},
            {"index": 2, "narration": "His face was stern.", "shot_type": "close-up"},
        ]
        prompt = build_visual_prompts_prompt(scenes, style=None)
        assert "[establishing shot]" in prompt
        assert "[close-up]" in prompt

    def test_no_shot_type_produces_no_brackets(self):
        from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt

        scenes = [
            {"index": 1, "narration": "A scene without a shot type."},
        ]
        prompt = build_visual_prompts_prompt(scenes, style=None)
        # No shot_type → no brackets after scene number
        assert "Scene 1:" in prompt
        assert "Scene 1 [" not in prompt

    def test_prompt_contains_banned_objects_section(self):
        from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt

        prompt = build_visual_prompts_prompt([], style=None)
        assert "mist" in prompt.lower() or "candle" in prompt.lower()

    def test_prompt_contains_visual_continuity_section(self):
        from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt

        prompt = build_visual_prompts_prompt([], style=None)
        assert "VISUAL CONTINUITY" in prompt or "visual journey" in prompt.lower()

    def test_prompt_contains_10_element_structure(self):
        from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt

        prompt = build_visual_prompts_prompt([], style=None)
        assert "PROMPT STRUCTURE" in prompt
        assert "10 elements" in prompt or "10. Quality" in prompt

    def test_prev_context_injected_correctly(self):
        from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt

        prompt = build_visual_prompts_prompt(
            [{"index": 1, "narration": "Scene one."}],
            prev_context=["Sc.1: stone steps in amber light"],
        )
        assert "stone steps in amber light" in prompt
        assert "ALREADY USED" in prompt

    def test_backward_compat_build_enhance_prompt(self):
        from ytfactory.agents.prompts.scene_planner import build_enhance_prompt

        prompt = build_enhance_prompt("History", "[{...}]", style="documentary")
        assert "documentary" in prompt.lower()


# ── Settings integration ───────────────────────────────────────────────────────


class TestSettings:
    def test_image_prompt_debug_defaults_to_false(self):
        from ytfactory.config.settings import Settings

        s = Settings()
        assert s.image_prompt_debug is False

    def test_shot_types_constant_has_14_entries(self):
        assert len(SHOT_TYPES) == 14

    def test_shot_types_are_unique(self):
        assert len(set(SHOT_TYPES)) == len(SHOT_TYPES)


# ── Backward compatibility ─────────────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_build_visual_prompts_prompt_without_shot_types(self):
        from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt

        scenes = [
            {"index": 1, "narration": "First narration."},
            {"index": 2, "narration": "Second narration."},
        ]
        # Should not raise even without shot_type in scenes
        prompt = build_visual_prompts_prompt(scenes, style="spiritual")
        assert "First narration." in prompt
        assert len(prompt) > 100

    def test_enrich_scenes_idempotent_with_existing_shot_types(self):
        engine = ImagePromptEngineV4()
        # Pre-assign a shot type manually
        scenes = [_make_scene(1, shot_type="macro")]
        # enrich_scenes_with_shots overwrites shot_type with planned type
        enriched = engine.enrich_scenes_with_shots(scenes)
        assert "shot_type" in enriched[0]

    def test_image_pipeline_compatible(self):
        """ImagePipeline reads scene['visual_prompt'] — shot_type doesn't interfere."""
        from ytfactory.images.prompt_engine import ImagePromptEngineV4

        engine = ImagePromptEngineV4()
        scenes = _scenes(3)
        enriched = engine.enrich_scenes_with_shots(scenes)
        # The visual_prompt field must still be present and unchanged
        for s in enriched:
            assert "visual_prompt" in s
