"""Tests for Visual Intelligence Prompt Builder (Phase 2)."""

from __future__ import annotations

import json

import pytest

from video_core.domain.visual_metadata import (
    Environment,
    Era,
    Mood,
    NarrativeRole,
    VisualMetadata,
    VisualStyle,
)
from video_core.visual_intelligence.prompt_builder import PromptBuilder, PromptDiff, merge_negative_prompts
from video_core.visual_intelligence.prompt_package import PromptPackage


# ── Helpers ────────────────────────────────────────────────────────────────────


def _scene(visual_prompt: str = "A contemplative figure in a stone temple.") -> dict:
    return {
        "index": 1,
        "title": "Test Scene",
        "narration": "Test narration.",
        "visual_prompt": visual_prompt,
        "duration_seconds": 10.0,
    }


def _vm(**kwargs) -> VisualMetadata:
    defaults = dict(
        version=1,
        era=Era.ANCIENT,
        narrative_role=NarrativeRole.STORY,
        environment=Environment.TEMPLE,
        mood=Mood.REVERENT,
        visual_style=VisualStyle.DOCUMENTARY,
        allow_modern_objects=False,
        reason="Ancient temple setting",
    )
    defaults.update(kwargs)
    return VisualMetadata(**defaults)


# ── merge_negative_prompts tests ───────────────────────────────────────────────


class TestMergeNegativePrompts:
    def test_none_inputs(self):
        assert merge_negative_prompts(None, None) is None

    def test_single_part(self):
        result = merge_negative_prompts("a, b, c")
        assert result == "a, b, c"

    def test_merge_distinct(self):
        result = merge_negative_prompts("a, b", "c, d")
        assert result == "a, b, c, d"

    def test_deduplicate_case_insensitive(self):
        result = merge_negative_prompts("Drone, Helicopter", "drone, CAR")
        assert result == "Drone, Helicopter, CAR"

    def test_empty_string_ignored(self):
        result = merge_negative_prompts("a, b", "", None)
        assert result == "a, b"

    def test_order_preserved(self):
        result = merge_negative_prompts("z, a", "m, z")
        assert result == "z, a, m"


# ── PromptBuilder fallback tests ───────────────────────────────────────────────


class TestPromptBuilderFallback:
    def test_no_metadata_returns_original_prompt(self):
        builder = PromptBuilder()
        scene = _scene()
        package = builder.build_from_scene(scene)
        assert package.final_prompt == scene["visual_prompt"]
        assert package.visual_profile == ""
        assert package.negative_prompt is None

    def test_empty_metadata_dict_returns_original_prompt(self):
        builder = PromptBuilder()
        scene = _scene()
        scene["visual_metadata"] = {}
        package = builder.build_from_scene(scene)
        assert package.final_prompt == scene["visual_prompt"]
        assert package.visual_profile == ""

    def test_none_metadata_returns_original_prompt(self):
        builder = PromptBuilder()
        package = builder.build(_scene(), visual_metadata=None)
        assert package.final_prompt == _scene()["visual_prompt"]

    def test_invalid_metadata_falls_back(self):
        builder = PromptBuilder()
        scene = _scene()
        scene["visual_metadata"] = {"era": "INVALID_ERA"}
        package = builder.build_from_scene(scene)
        assert package.final_prompt == scene["visual_prompt"]


# ── Ancient profile tests ──────────────────────────────────────────────────────


class TestAncientProfile:
    def test_ancient_era_assigns_profile(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.ANCIENT)
        package = builder.build(scene, vm)
        assert package.visual_profile == "ancient_documentary"

    def test_ancient_positive_fragments_included(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.ANCIENT)
        package = builder.build(scene, vm)
        assert "historically authentic" in package.final_prompt
        assert "ancient architecture" in package.final_prompt
        assert "stone temples" in package.final_prompt
        assert "traditional clothing" in package.final_prompt

    def test_ancient_negative_constraints(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.ANCIENT, allow_modern_objects=False)
        package = builder.build(scene, vm)
        assert package.negative_prompt is not None
        assert "drones" in package.negative_prompt
        assert "smartphones" in package.negative_prompt
        assert "glass buildings" in package.negative_prompt
        assert "modern clothing" in package.negative_prompt

    def test_ancient_allow_modern_objects_true(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.ANCIENT, allow_modern_objects=True)
        package = builder.build(scene, vm)
        assert "modern objects" not in (package.negative_prompt or "")
        assert "contemporary elements" not in (package.negative_prompt or "")

    def test_ancient_environment_temple(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.ANCIENT, environment=Environment.TEMPLE)
        package = builder.build(scene, vm)
        assert "stone temple complex" in package.final_prompt
        assert "carved columns" in package.final_prompt

    def test_ancient_environment_forest(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.ANCIENT, environment=Environment.FOREST)
        package = builder.build(scene, vm)
        assert "dense forest" in package.final_prompt
        assert "ancient trees" in package.final_prompt

    def test_ancient_mood_reverent(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.ANCIENT, mood=Mood.REVERENT)
        package = builder.build(scene, vm)
        assert "sacred atmosphere" in package.final_prompt
        assert "temple glow" in package.final_prompt

    def test_ancient_narrative_role_story(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.ANCIENT, narrative_role=NarrativeRole.STORY)
        package = builder.build(scene, vm)
        assert "documentary realism" in package.final_prompt

    def test_ancient_visual_style_documentary(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.ANCIENT, visual_style=VisualStyle.DOCUMENTARY)
        package = builder.build(scene, vm)
        assert "documentary style" in package.final_prompt


# ── Historical profile tests ───────────────────────────────────────────────────


class TestHistoricalProfile:
    def test_historical_era_assigns_profile(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.HISTORICAL)
        package = builder.build(scene, vm)
        assert package.visual_profile == "historical_documentary"

    def test_historical_positive_fragments(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.HISTORICAL)
        package = builder.build(scene, vm)
        assert "historically authentic" in package.final_prompt
        assert "period-accurate details" in package.final_prompt

    def test_historical_negative_constraints(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.HISTORICAL, allow_modern_objects=False)
        package = builder.build(scene, vm)
        assert "anachronistic elements" in package.negative_prompt
        assert "modern technology" in package.negative_prompt

    def test_historical_allow_modern_true(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.HISTORICAL, allow_modern_objects=True)
        package = builder.build(scene, vm)
        assert "anachronistic elements" not in (package.negative_prompt or "")


# ── Modern profile tests ───────────────────────────────────────────────────────


class TestModernProfile:
    def test_modern_era_assigns_profile(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.MODERN)
        package = builder.build(scene, vm)
        assert package.visual_profile == "modern_documentary"

    def test_modern_positive_fragments(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.MODERN)
        package = builder.build(scene, vm)
        assert "contemporary setting" in package.final_prompt
        assert "modern technology" in package.final_prompt

    def test_modern_negative_constraints(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.MODERN)
        package = builder.build(scene, vm)
        assert package.negative_prompt is not None
        assert "ancient styling" in package.negative_prompt
        assert "historical costumes" in package.negative_prompt

    def test_modern_environment_office(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.MODERN, environment=Environment.OFFICE)
        package = builder.build(scene, vm)
        assert "modern office" in package.final_prompt
        assert "professional workspace" in package.final_prompt

    def test_modern_environment_city(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.MODERN, environment=Environment.CITY)
        package = builder.build(scene, vm)
        assert "urban environment" in package.final_prompt
        assert "cityscape" in package.final_prompt


# ── Symbolic profile tests ─────────────────────────────────────────────────────


class TestSymbolicProfile:
    def test_symbolic_era_assigns_profile(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.SYMBOLIC)
        package = builder.build(scene, vm)
        assert package.visual_profile == "symbolic_documentary"

    def test_symbolic_positive_fragments(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.SYMBOLIC)
        package = builder.build(scene, vm)
        assert "timeless" in package.final_prompt
        assert "dreamlike" in package.final_prompt
        assert "ethereal" in package.final_prompt
        assert "abstract" in package.final_prompt

    def test_symbolic_no_era_negative_constraints(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.SYMBOLIC)
        package = builder.build(scene, vm)
        assert "forced historical constraints" in (package.negative_prompt or "")

    def test_symbolic_environment_abstract(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.SYMBOLIC, environment=Environment.ABSTRACT)
        package = builder.build(scene, vm)
        assert "abstract visual space" in package.final_prompt
        assert "non-representational forms" in package.final_prompt

    def test_symbolic_environment_cosmic(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.SYMBOLIC, environment=Environment.COSMIC)
        package = builder.build(scene, vm)
        assert "cosmic scale" in package.final_prompt
        assert "celestial" in package.final_prompt


# ── Transitional profile tests ────────────────────────────────────────────────


class TestTransitionalProfile:
    def test_transitional_era_assigns_profile(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.TRANSITIONAL)
        package = builder.build(scene, vm)
        assert package.visual_profile == "transitional_documentary"

    def test_transitional_positive_fragments(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.TRANSITIONAL)
        package = builder.build(scene, vm)
        assert "intentional coexistence of ancient and modern" in package.final_prompt
        assert "contrast between eras" in package.final_prompt

    def test_transitional_no_negative_constraints(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.TRANSITIONAL)
        package = builder.build(scene, vm)
        assert not package.negative_prompt

    def test_transitional_environment_city(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(era=Era.TRANSITIONAL, environment=Environment.CITY)
        package = builder.build(scene, vm)
        assert "blend of ancient and modern architecture" in package.final_prompt


# ── Narrative Role tests ───────────────────────────────────────────────────────


class TestNarrativeRole:
    def test_story_role(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(narrative_role=NarrativeRole.STORY)
        package = builder.build(scene, vm)
        assert "documentary realism" in package.final_prompt

    def test_analogy_role(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(narrative_role=NarrativeRole.ANALOGY)
        package = builder.build(scene, vm)
        assert "visual metaphor" in package.final_prompt

    def test_metaphor_role(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(narrative_role=NarrativeRole.METAPHOR)
        package = builder.build(scene, vm)
        assert "symbolic imagery" in package.final_prompt

    def test_explanation_role(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(narrative_role=NarrativeRole.EXPLANATION)
        package = builder.build(scene, vm)
        assert "educational clarity" in package.final_prompt

    def test_establishing_role(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(narrative_role=NarrativeRole.ESTABLISHING)
        package = builder.build(scene, vm)
        assert "wide cinematic composition" in package.final_prompt

    def test_cta_role(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(narrative_role=NarrativeRole.CTA)
        package = builder.build(scene, vm)
        assert "clean composition" in package.final_prompt


# ── Mood tests ─────────────────────────────────────────────────────────────────


class TestMood:
    def test_peaceful_mood(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(mood=Mood.PEACEFUL)
        package = builder.build(scene, vm)
        assert "warm golden light" in package.final_prompt

    def test_fearful_mood(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(mood=Mood.FEARFUL)
        package = builder.build(scene, vm)
        assert "stormy contrast" in package.final_prompt

    def test_reflective_mood(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(mood=Mood.REFLECTIVE)
        package = builder.build(scene, vm)
        assert "soft evening light" in package.final_prompt

    def test_mysterious_mood(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(mood=Mood.MYSTERIOUS)
        package = builder.build(scene, vm)
        assert "fog and moonlight" in package.final_prompt

    def test_hopeful_mood(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(mood=Mood.HOPEFUL)
        package = builder.build(scene, vm)
        assert "first light breaking through clouds" in package.final_prompt


# ── Visual Style tests ─────────────────────────────────────────────────────────


class TestVisualStyle:
    def test_documentary_style(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(visual_style=VisualStyle.DOCUMENTARY)
        package = builder.build(scene, vm)
        assert "documentary style" in package.final_prompt

    def test_cinematic_style(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(visual_style=VisualStyle.CINEMATIC)
        package = builder.build(scene, vm)
        assert "cinematic style" in package.final_prompt

    def test_dreamlike_style(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm(visual_style=VisualStyle.DREAMLIKE)
        package = builder.build(scene, vm)
        assert "dreamlike" in package.final_prompt


# ── PromptPackage tests ────────────────────────────────────────────────────────


class TestPromptPackage:
    def test_fingerprint_is_deterministic(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm()
        p1 = builder.build(scene, vm)
        p2 = builder.build(scene, vm)
        assert p1.prompt_fingerprint == p2.prompt_fingerprint

    def test_fingerprint_changes_with_prompt(self):
        builder = PromptBuilder()
        scene1 = _scene("Prompt A")
        scene2 = _scene("Prompt B")
        vm = _vm()
        p1 = builder.build(scene1, vm)
        p2 = builder.build(scene2, vm)
        assert p1.prompt_fingerprint != p2.prompt_fingerprint

    def test_metadata_snapshot_populated(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm()
        package = builder.build(scene, vm)
        assert package.metadata_snapshot["era"] == "ANCIENT"
        assert package.metadata_snapshot["environment"] == "TEMPLE"

    def test_assembly_report_contains_sections(self):
        builder = PromptBuilder()
        scene = _scene()
        vm = _vm()
        package = builder.build(scene, vm)
        report = package.assembly_report or {}
        assert report["applied_profile"] == "ancient_documentary"
        assert "positive_constraints" in report
        assert "negative_constraints" in report
        assert "prompt_statistics" in report
        assert report["final_prompt"] == package.final_prompt


# ── PromptDiff tests ───────────────────────────────────────────────────────────


class TestPromptDiff:
    def test_diff_added(self):
        before = PromptPackage(final_prompt="a b c")
        after = PromptPackage(final_prompt="a b c d e")
        diff = PromptBuilder().diff(before, after)
        assert "d" in diff.added
        assert "e" in diff.added

    def test_diff_removed(self):
        before = PromptPackage(final_prompt="a b c d e")
        after = PromptPackage(final_prompt="a b c")
        diff = PromptBuilder().diff(before, after)
        assert "d" in diff.removed
        assert "e" in diff.removed

    def test_diff_string_representation(self):
        before = PromptPackage(final_prompt="a b")
        after = PromptPackage(final_prompt="a c")
        diff = PromptBuilder().diff(before, after)
        s = str(diff)
        assert "+" in s
        assert "-" in s


# ── Backward compatibility tests ───────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_existing_scene_dict_unchanged_when_no_metadata(self):
        builder = PromptBuilder()
        original = "Wide shot of a temple, golden hour, no text, no watermark, photorealistic"
        scene = {
            "index": 1,
            "title": "Temple",
            "narration": "Test.",
            "visual_prompt": original,
            "duration_seconds": 10.0,
        }
        package = builder.build_from_scene(scene)
        assert package.final_prompt == original
        assert package.negative_prompt is None

    def test_existing_pipeline_scene_survives(self):
        """A scene dict from an existing pipeline should not break."""
        builder = PromptBuilder()
        scene = {
            "index": 1,
            "title": "Old Scene",
            "narration": "Old narration.",
            "visual_prompt": "Old prompt.",
            "duration_seconds": 10.0,
            "visual_metadata": {},
        }
        package = builder.build_from_scene(scene)
        assert package.final_prompt == "Old prompt."

    def test_assembly_report_empty_when_no_metadata(self):
        builder = PromptBuilder()
        scene = _scene()
        package = builder.build_from_scene(scene)
        report = package.assembly_report or {}
        assert report["applied_profile"] == ""
        assert report["positive_constraints"] == []
        assert report["negative_constraints"] == []
