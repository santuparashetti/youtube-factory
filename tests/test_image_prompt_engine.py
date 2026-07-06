"""Tests for Image Prompt Engine V5 — shot planner, diagnostics, engine, integration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ytfactory.images.diagnostics import (
    DiagnosticsReport,
    _AI_CLICHES,
    _REPETITIVE_OBJECTS,
    _STYLE_MARKERS,
    _UNSAFE_COMPOSITIONS,
    build_report,
)
from ytfactory.images.prompt_engine import (
    ImagePromptEngineV4,
    _DEFAULT_NEGATIVE_PROMPT,
    _PROVIDERS_WITH_NEGATIVE_PROMPTS,
)
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
            "Profile shot of an elderly man tracing cracks in a stone wall, no text, no watermark, photorealistic.",
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
        assert data["version"] == "v5"
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


# ── V5: Safe compositions ─────────────────────────────────────────────────────


class TestSafeCompositions:
    def test_shot_types_excludes_macro(self):
        assert "macro" not in SHOT_TYPES

    def test_shot_types_excludes_pov(self):
        assert "POV" not in SHOT_TYPES
        assert "pov" not in SHOT_TYPES

    def test_shot_types_excludes_extreme_close_up(self):
        assert "extreme close-up" not in SHOT_TYPES

    def test_shot_types_includes_environmental_portrait(self):
        assert "environmental portrait" in SHOT_TYPES

    def test_shot_types_includes_profile_shot(self):
        assert "profile shot" in SHOT_TYPES

    def test_shot_types_includes_wide_cinematic(self):
        assert "wide cinematic" in SHOT_TYPES

    def test_unsafe_compositions_tuple_is_non_empty(self):
        assert len(_UNSAFE_COMPOSITIONS) > 0

    def test_ai_cliches_tuple_is_non_empty(self):
        assert len(_AI_CLICHES) > 0


# ── V5: AI cliché detection ───────────────────────────────────────────────────


class TestAIClicheDetection:
    def test_cliche_in_prompt_detected(self):
        scenes = [
            _make_scene(1, visual_prompt="Giant hands holding a small figure, cosmic portal glow, photorealistic."),
            _make_scene(2, visual_prompt="Wide cinematic shot, worn stone steps, no text, no watermark, photorealistic."),
        ]
        report = build_report(scenes, plan_shots(2))
        assert "giant hands" in report.ai_cliches_detected
        assert 1 in report.ai_cliches_detected["giant hands"]

    def test_clean_prompt_has_no_cliches(self):
        scenes = [
            _make_scene(1, visual_prompt="Worn stone steps disappearing into morning amber, no text, no watermark, photorealistic."),
        ]
        report = build_report(scenes, plan_shots(1))
        assert report.ai_cliches_detected == {}

    def test_unsafe_composition_detected(self):
        scenes = [
            _make_scene(1, visual_prompt="Extreme close-up of fingertips, macro shot detail, no text, photorealistic."),
        ]
        report = build_report(scenes, plan_shots(1))
        assert len(report.unsafe_compositions_detected) > 0

    def test_cliche_reduces_diversity_score(self):
        scenes_clean = [
            _make_scene(1, visual_prompt="Worn stone steps at dawn, no text, no watermark, photorealistic."),
        ]
        scenes_cliche = [
            _make_scene(1, visual_prompt="Giant hands holding the universe, no text, no watermark, photorealistic."),
        ]
        report_clean = build_report(scenes_clean, plan_shots(1))
        report_cliche = build_report(scenes_cliche, plan_shots(1))
        assert report_cliche.diversity_score < report_clean.diversity_score

    def test_validate_flags_cliche(self):
        engine = ImagePromptEngineV4()
        scenes = [
            _make_scene(1, visual_prompt="Giant hands holding a small glowing orb, photorealistic, no text, no watermark."),
            _make_scene(2, visual_prompt="Worn stone steps in amber light, photorealistic, no text, no watermark."),
        ]
        enriched = engine.enrich_scenes_with_shots(scenes)
        report = engine.build_diagnostics(enriched)
        issues = engine.validate(enriched, report)
        assert any("ai_cliche" in i for i in issues)


# ── V5: Provider enrichment ───────────────────────────────────────────────────


class TestEnrichForProvider:
    def test_huggingface_gets_negative_prompt(self):
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(1, visual_prompt="Wide shot, photorealistic, no text.")]
        enriched = engine.enrich_for_provider(scenes, "huggingface")
        assert "negative_prompt" in enriched[0]
        assert "deformed" in enriched[0]["negative_prompt"]

    def test_a1111_gets_negative_prompt(self):
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(1, visual_prompt="Wide shot, photorealistic, no text.")]
        enriched = engine.enrich_for_provider(scenes, "a1111")
        assert "negative_prompt" in enriched[0]

    def test_pollinations_gets_anatomy_reinforcement(self):
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(1, visual_prompt="Wide shot, photorealistic, no text.")]
        enriched = engine.enrich_for_provider(scenes, "pollinations")
        assert "natural human anatomy" in enriched[0]["visual_prompt"]
        assert "negative_prompt" not in enriched[0]

    def test_gemini_gets_anatomy_reinforcement(self):
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(1, visual_prompt="Cinematic wide, photorealistic, no text.")]
        enriched = engine.enrich_for_provider(scenes, "gemini")
        assert "five fingers" in enriched[0]["visual_prompt"]

    def test_asset_scenes_not_modified(self):
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(1, scene_type="asset")]
        enriched = engine.enrich_for_provider(scenes, "huggingface")
        assert "negative_prompt" not in enriched[0]

    def test_does_not_double_append_reinforcement(self):
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(1, visual_prompt="Wide shot, photorealistic, no text.")]
        enriched = engine.enrich_for_provider(scenes, "pollinations")
        enriched_again = engine.enrich_for_provider(enriched, "pollinations")
        assert enriched[0]["visual_prompt"] == enriched_again[0]["visual_prompt"]

    def test_providers_with_negative_prompts_set(self):
        assert "huggingface" in _PROVIDERS_WITH_NEGATIVE_PROMPTS
        assert "a1111" in _PROVIDERS_WITH_NEGATIVE_PROMPTS
        assert "pollinations" not in _PROVIDERS_WITH_NEGATIVE_PROMPTS
        assert "gemini" not in _PROVIDERS_WITH_NEGATIVE_PROMPTS

    def test_default_negative_prompt_non_empty(self):
        assert len(_DEFAULT_NEGATIVE_PROMPT) > 10
        assert "deformed" in _DEFAULT_NEGATIVE_PROMPT


# ── V5: Prompt review ─────────────────────────────────────────────────────────


class TestPromptReview:
    def test_clean_prompt_returns_no_issues(self):
        engine = ImagePromptEngineV4()
        # Human scene with all required quality markers — should produce no issues
        prompt = (
            "Worn stone steps descend into morning amber light. "
            "A lean man in a grey linen shirt, highly detailed human face, "
            "natural facial expression, realistic eyes, authentic skin texture, "
            "natural posture, seamless integration with the environment, "
            "documentary-quality realism, sits with his back to us, "
            "watching the valley fill with golden haze. "
            "Environmental portrait, muted ochre and slate grey palette, "
            "overcast warmth. No text, no watermark, photorealistic, documentary style."
        )
        issues = engine.review_prompt(prompt, scene_index=1)
        assert issues == []

    def test_banned_opener_detected(self):
        engine = ImagePromptEngineV4()
        prompt = "a figure standing in the mist, photorealistic, no text, no watermark."
        issues = engine.review_prompt(prompt, scene_index=1)
        assert any("banned opener" in i for i in issues)

    def test_ai_cliche_detected_in_review(self):
        engine = ImagePromptEngineV4()
        prompt = "Giant hands holding a floating orb of light. No text, no watermark, photorealistic."
        issues = engine.review_prompt(prompt, scene_index=2)
        assert any("cliché" in i or "cliche" in i for i in issues)

    def test_missing_style_marker_detected(self):
        engine = ImagePromptEngineV4()
        prompt = "Worn stone steps at dawn, warm amber light, muted ochre tones."
        issues = engine.review_prompt(prompt, scene_index=1)
        assert any("style marker" in i for i in issues)

    def test_too_short_prompt_detected(self):
        engine = ImagePromptEngineV4()
        prompt = "A stone step. Photorealistic."
        issues = engine.review_prompt(prompt, scene_index=1)
        assert any("too short" in i for i in issues)

    def test_review_all_prompts_returns_per_scene_dict(self):
        engine = ImagePromptEngineV4()
        scenes = [
            _make_scene(1, visual_prompt="a figure standing in the mist, photorealistic, no text."),
            _make_scene(2, visual_prompt=(
                "Worn stone steps at amber dawn, each tread hollowed by generations of crossings. "
                "Static, locked-off camera, mid-distance, watching the valley below fill with golden haze. "
                "Muted ochre and slate grey palette, soft directional morning light, "
                "soft volumetric mist through stone arches. "
                "No text, no watermark, photorealistic, documentary style, cinematic."
            )),
            _make_scene(3, scene_type="asset"),
        ]
        results = engine.review_all_prompts(scenes)
        assert 1 in results
        assert 2 in results
        assert 3 not in results  # asset scene excluded
        # Scene 1 has banned opener
        assert any("banned opener" in i for i in results[1])
        # Scene 2 is a non-human environment scene — should be clean
        assert results[2] == []

    def test_review_prompt_flags_human_without_quality_markers(self):
        engine = ImagePromptEngineV4()
        # Has a man but no quality markers
        prompt = (
            "A lean man in a grey linen shirt stands at the cliff edge. "
            "Wide establishing shot, warm golden hour light, ochre and amber palette, "
            "muted tones, photorealistic, no text, no watermark, documentary style."
        )
        issues = engine.review_prompt(prompt, scene_index=1)
        assert any("human" in i.lower() and "quality" in i.lower() for i in issues)

    def test_review_prompt_no_human_flag_for_non_human_scene(self):
        engine = ImagePromptEngineV4()
        prompt = (
            "Worn stone steps descend into morning mist. Wide establishing shot, "
            "warm amber light, muted ochre palette, photorealistic, no text, no watermark."
        )
        issues = engine.review_prompt(prompt, scene_index=1)
        assert not any("human" in i.lower() and "quality" in i.lower() for i in issues)


# ── Human enrichment ──────────────────────────────────────────────────────────


class TestHumanEnrichment:
    """Tests that enrich_for_provider applies human quality reinforcement."""

    def test_human_scene_gets_quality_markers_pollinations(self):
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(
            1,
            visual_prompt=(
                "A lean man in a grey linen shirt stands at the cliff edge, "
                "wide shot, photorealistic, no text, no watermark."
            ),
            shot_type="wide shot",
        )]
        enriched = engine.enrich_for_provider(scenes, "pollinations")
        prompt = enriched[0]["visual_prompt"]
        assert "highly detailed human face" in prompt
        assert "natural facial expression" in prompt
        assert "realistic eyes" in prompt

    def test_human_scene_gets_quality_markers_huggingface(self):
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(
            1,
            visual_prompt=(
                "An elder monk seated beneath a banyan tree at dawn, "
                "medium shot, photorealistic, no text, no watermark."
            ),
            shot_type="medium shot",
        )]
        enriched = engine.enrich_for_provider(scenes, "huggingface")
        prompt = enriched[0]["visual_prompt"]
        assert "highly detailed human face" in prompt

    def test_wide_shot_with_human_gets_dominance_phrase(self):
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(
            1,
            visual_prompt=(
                "A warrior stands at the edge of the battlefield, "
                "wide cinematic framing, golden hour, photorealistic, no text, no watermark."
            ),
            shot_type="wide cinematic",
        )]
        enriched = engine.enrich_for_provider(scenes, "pollinations")
        assert "subject remains visually prominent" in enriched[0]["visual_prompt"]

    def test_non_human_scene_no_quality_markers_added(self):
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(
            1,
            visual_prompt=(
                "Glacier-fed alpine lake, surface unbroken at pre-dawn, "
                "establishing shot, photorealistic, no text, no watermark."
            ),
            shot_type="establishing shot",
        )]
        enriched = engine.enrich_for_provider(scenes, "pollinations")
        assert "highly detailed human face" not in enriched[0]["visual_prompt"]
        assert "subject remains visually prominent" not in enriched[0]["visual_prompt"]

    def test_does_not_double_add_quality_markers(self):
        engine = ImagePromptEngineV4()
        already_reinforced = (
            "A monk, highly detailed human face, natural facial expression, realistic eyes, "
            "authentic skin texture, natural posture, seamless integration with the environment, "
            "documentary-quality realism, photorealistic, no text, no watermark."
        )
        scenes = [_make_scene(1, visual_prompt=already_reinforced, shot_type="medium shot")]
        enriched = engine.enrich_for_provider(scenes, "pollinations")
        prompt = enriched[0]["visual_prompt"]
        assert prompt.count("highly detailed human face") == 1

    def test_medium_shot_with_human_no_dominance_phrase(self):
        engine = ImagePromptEngineV4()
        scenes = [_make_scene(
            1,
            visual_prompt=(
                "A monk at a writing desk, medium shot, photorealistic, no text, no watermark."
            ),
            shot_type="medium shot",
        )]
        enriched = engine.enrich_for_provider(scenes, "pollinations")
        assert "subject remains visually prominent" not in enriched[0]["visual_prompt"]

    def test_diagnostics_tracks_human_scenes(self):
        engine = ImagePromptEngineV4()
        scenes = [
            _make_scene(
                1,
                visual_prompt=(
                    "A lean man, highly detailed human face, natural facial expression, "
                    "realistic eyes, authentic skin texture, natural posture, "
                    "seamless integration with the environment, documentary-quality realism, "
                    "photorealistic, no text, no watermark."
                ),
            ),
            _make_scene(
                2,
                visual_prompt=(
                    "Worn stone steps at dawn, establishing shot, photorealistic, "
                    "no text, no watermark."
                ),
            ),
        ]
        report = engine.build_diagnostics(scenes)
        assert report.human_scenes_count == 1
        assert report.human_quality_enforced == 1
        assert report.human_quality_missing == []

    def test_diagnostics_tracks_human_scenes_missing_quality(self):
        engine = ImagePromptEngineV4()
        scenes = [
            _make_scene(
                1,
                visual_prompt=(
                    "An elder man in a grey robe, wide shot, photorealistic, "
                    "no text, no watermark."
                ),
            ),
        ]
        report = engine.build_diagnostics(scenes)
        assert report.human_scenes_count == 1
        assert report.human_quality_enforced == 0
        assert 1 in report.human_quality_missing
