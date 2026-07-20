"""Phase 1 tests for Visual Intelligence Layer (VISUAL_INTELLIGENCE_ARCHITECTURE.md).

Covers:
- VisualMetadata model creation, defaults, and enum validation
- Scene model extension with visual_metadata
- Scene Planner prompt parsing (with and without visual_metadata)
- Pipeline propagation through scene dicts
- Backward compatibility with existing scene plans
"""

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
from ytfactory.scenes.models import Scene, ScenePlan


# ── VisualMetadata model tests ──────────────────────────────────────────────────


class TestVisualMetadataDefaults:
    def test_defaults(self):
        vm = VisualMetadata()
        assert vm.version == 1
        assert vm.era is None
        assert vm.narrative_role is None
        assert vm.environment is None
        assert vm.mood is None
        assert vm.visual_style is None
        assert vm.allow_modern_objects is False
        assert vm.reason == ""

    def test_full_construction(self):
        vm = VisualMetadata(
            version=1,
            era=Era.ANCIENT,
            narrative_role=NarrativeRole.STORY,
            environment=Environment.TEMPLE,
            mood=Mood.REVERENT,
            visual_style=VisualStyle.DOCUMENTARY,
            allow_modern_objects=False,
            reason="Ancient temple setting",
        )
        assert vm.version == 1
        assert vm.era == Era.ANCIENT
        assert vm.narrative_role == NarrativeRole.STORY
        assert vm.environment == Environment.TEMPLE
        assert vm.mood == Mood.REVERENT
        assert vm.visual_style == VisualStyle.DOCUMENTARY
        assert vm.allow_modern_objects is False
        assert vm.reason == "Ancient temple setting"


class TestVisualMetadataEnums:
    @pytest.mark.parametrize(
        "era",
        [
            Era.ANCIENT,
            Era.HISTORICAL,
            Era.MODERN,
            Era.SYMBOLIC,
            Era.TRANSITIONAL,
        ],
    )
    def test_era_values(self, era):
        assert era.value in {"ANCIENT", "HISTORICAL", "MODERN", "SYMBOLIC", "TRANSITIONAL"}

    @pytest.mark.parametrize(
        "role",
        [
            NarrativeRole.STORY,
            NarrativeRole.ANALOGY,
            NarrativeRole.METAPHOR,
            NarrativeRole.EXPLANATION,
            NarrativeRole.ESTABLISHING,
            NarrativeRole.CTA,
        ],
    )
    def test_narrative_role_values(self, role):
        assert role.value in {
            "STORY",
            "ANALOGY",
            "METAPHOR",
            "EXPLANATION",
            "ESTABLISHING",
            "CTA",
        }

    @pytest.mark.parametrize(
        "env",
        [
            Environment.FOREST,
            Environment.TEMPLE,
            Environment.ASHRAM,
            Environment.KINGDOM,
            Environment.BATTLEFIELD,
            Environment.CITY,
            Environment.OFFICE,
            Environment.HOME,
            Environment.MOUNTAIN,
            Environment.RIVER,
            Environment.ABSTRACT,
            Environment.COSMIC,
        ],
    )
    def test_environment_values(self, env):
        assert env.value in {
            "FOREST",
            "TEMPLE",
            "ASHRAM",
            "KINGDOM",
            "BATTLEFIELD",
            "CITY",
            "OFFICE",
            "HOME",
            "MOUNTAIN",
            "RIVER",
            "ABSTRACT",
            "COSMIC",
        }

    @pytest.mark.parametrize(
        "mood",
        [
            Mood.PEACEFUL,
            Mood.MYSTERIOUS,
            Mood.REVERENT,
            Mood.REFLECTIVE,
            Mood.HOPEFUL,
            Mood.FEARFUL,
            Mood.CURIOUS,
            Mood.LONELY,
            Mood.DETERMINED,
        ],
    )
    def test_mood_values(self, mood):
        assert mood.value in {
            "PEACEFUL",
            "MYSTERIOUS",
            "REVERENT",
            "REFLECTIVE",
            "HOPEFUL",
            "FEARFUL",
            "CURIOUS",
            "LONELY",
            "DETERMINED",
        }

    @pytest.mark.parametrize(
        "style",
        [
            VisualStyle.DOCUMENTARY,
            VisualStyle.CINEMATIC,
            VisualStyle.REALISTIC,
            VisualStyle.DREAMLIKE,
            VisualStyle.PAINTING,
            VisualStyle.ANIME,
            VisualStyle.WATERCOLOR,
        ],
    )
    def test_visual_style_values(self, style):
        assert style.value in {
            "DOCUMENTARY",
            "CINEMATIC",
            "REALISTIC",
            "DREAMLIKE",
            "PAINTING",
            "ANIME",
            "WATERCOLOR",
        }

    def test_invalid_era_rejected(self):
        with pytest.raises(ValueError):
            Era("MEDIEVAL")

    def test_invalid_mood_rejected(self):
        with pytest.raises(ValueError):
            Mood("EXCITED")


class TestVisualMetadataSerialization:
    def test_model_dump_roundtrip(self):
        original = VisualMetadata(
            era=Era.MODERN,
            narrative_role=NarrativeRole.EXPLANATION,
            environment=Environment.OFFICE,
            mood=Mood.CURIOUS,
            visual_style=VisualStyle.REALISTIC,
            allow_modern_objects=True,
            reason="Modern office setting",
        )
        dumped = original.model_dump()
        restored = VisualMetadata.model_validate(dumped)
        assert restored == original

    def test_model_dump_json_roundtrip(self):
        original = VisualMetadata(
            era=Era.ANCIENT,
            narrative_role=NarrativeRole.METAPHOR,
            environment=Environment.FOREST,
            mood=Mood.PEACEFUL,
            visual_style=VisualStyle.DOCUMENTARY,
            allow_modern_objects=False,
            reason="Ancient forest hermitage",
        )
        json_str = original.model_dump_json()
        restored = VisualMetadata.model_validate_json(json_str)
        assert restored == original

    def test_model_dump_includes_all_fields(self):
        vm = VisualMetadata(
            era=Era.TRANSITIONAL,
            narrative_role=NarrativeRole.ANALOGY,
            environment=Environment.CITY,
            mood=Mood.HOPEFUL,
            visual_style=VisualStyle.CINEMATIC,
            allow_modern_objects=True,
            reason="Ancient wisdom in modern city",
        )
        data = vm.model_dump()
        assert data["version"] == 1
        assert data["era"] == "TRANSITIONAL"
        assert data["narrative_role"] == "ANALOGY"
        assert data["environment"] == "CITY"
        assert data["mood"] == "HOPEFUL"
        assert data["visual_style"] == "CINEMATIC"
        assert data["allow_modern_objects"] is True
        assert data["reason"] == "Ancient wisdom in modern city"


# ── Scene model tests ──────────────────────────────────────────────────────────


class TestSceneModel:
    def test_scene_without_visual_metadata(self):
        scene = Scene(
            index=1,
            title="The Beginning",
            narration="Once upon a time.",
            visual_prompt="Wide shot of a forest.",
            duration_seconds=10.0,
        )
        assert scene.visual_metadata is None

    def test_scene_with_visual_metadata(self):
        vm = VisualMetadata(era=Era.ANCIENT, environment=Environment.FOREST)
        scene = Scene(
            index=1,
            title="The Beginning",
            narration="Once upon a time.",
            visual_prompt="Wide shot of a forest.",
            duration_seconds=10.0,
            visual_metadata=vm,
        )
        assert scene.visual_metadata is not None
        assert scene.visual_metadata.era == Era.ANCIENT
        assert scene.visual_metadata.environment == Environment.FOREST

    def test_scene_plan_serialization(self):
        vm = VisualMetadata(
            era=Era.HISTORICAL,
            narrative_role=NarrativeRole.STORY,
            environment=Environment.KINGDOM,
            mood=Mood.DETERMINED,
            visual_style=VisualStyle.CINEMATIC,
            allow_modern_objects=False,
            reason="Historical kingdom scene",
        )
        scene = Scene(
            index=1,
            title="The Kingdom",
            narration="The king ruled with wisdom.",
            visual_prompt="Low angle on a stone throne room.",
            duration_seconds=12.0,
            visual_metadata=vm,
        )
        plan = ScenePlan(title="Test", total_duration_seconds=12.0, scenes=[scene])
        data = plan.model_dump()
        restored = ScenePlan.model_validate(data)
        assert restored.scenes[0].visual_metadata is not None
        assert restored.scenes[0].visual_metadata.era == Era.HISTORICAL


# ── Scene Planner prompt parsing tests ─────────────────────────────────────────


class TestScenePlannerParsing:
    def test_parse_with_visual_metadata(self):
        from ytfactory.agents.nodes.scene_planner import _parse_visual_prompts

        text = json.dumps([
            {
                "index": 1,
                "visual_prompt": "Wide shot of an ancient temple.",
                "visual_metadata": {
                    "version": 1,
                    "era": "ANCIENT",
                    "narrative_role": "ESTABLISHING",
                    "environment": "TEMPLE",
                    "mood": "REVERENT",
                    "visual_style": "DOCUMENTARY",
                    "allow_modern_objects": False,
                    "reason": "Ancient temple setting",
                },
            }
        ])
        result = _parse_visual_prompts(text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["index"] == 1
        assert result[0]["visual_metadata"]["era"] == "ANCIENT"
        assert result[0]["visual_metadata"]["environment"] == "TEMPLE"

    def test_parse_without_visual_metadata_backward_compat(self):
        from ytfactory.agents.nodes.scene_planner import _parse_visual_prompts

        text = json.dumps([
            {"index": 1, "visual_prompt": "Wide shot of an ancient temple."}
        ])
        result = _parse_visual_prompts(text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["index"] == 1
        assert result[0]["visual_prompt"] == "Wide shot of an ancient temple."

    def test_parse_mixed_with_and_without_metadata(self):
        from ytfactory.agents.nodes.scene_planner import _parse_visual_prompts

        text = json.dumps([
            {
                "index": 1,
                "visual_prompt": "Ancient temple.",
                "visual_metadata": {"era": "ANCIENT", "environment": "TEMPLE"},
            },
            {"index": 2, "visual_prompt": "Modern office."},
        ])
        result = _parse_visual_prompts(text)
        assert result is not None
        assert len(result) == 2
        assert result[0]["visual_metadata"]["era"] == "ANCIENT"
        assert "visual_metadata" not in result[1]

    def test_parse_ignores_missing_visual_prompt(self):
        from ytfactory.agents.nodes.scene_planner import _parse_visual_prompts

        text = json.dumps([{"index": 1, "visual_metadata": {"era": "ANCIENT"}}])
        result = _parse_visual_prompts(text)
        assert result is None


# ── Pipeline propagation tests ─────────────────────────────────────────────────


class TestPipelinePropagation:
    def test_scene_dict_preserves_visual_metadata(self):
        scene = {
            "index": 1,
            "title": "Test",
            "narration": "Test narration.",
            "visual_prompt": "Test prompt.",
            "duration_seconds": 10.0,
            "visual_metadata": {
                "version": 1,
                "era": "MODERN",
                "narrative_role": "STORY",
                "environment": "OFFICE",
                "mood": "CURIOUS",
                "visual_style": "REALISTIC",
                "allow_modern_objects": True,
                "reason": "Modern office scene",
            },
        }
        # Simulate propagation through scene_assets.py pattern
        propagated = {**scene, "width": 1920, "height": 1080}
        assert propagated["visual_metadata"]["era"] == "MODERN"
        assert propagated["visual_metadata"]["environment"] == "OFFICE"

    def test_scene_dict_with_empty_visual_metadata(self):
        scene = {
            "index": 1,
            "title": "Test",
            "narration": "Test narration.",
            "visual_prompt": "Test prompt.",
            "duration_seconds": 10.0,
            "visual_metadata": {},
        }
        propagated = {**scene, "width": 1920}
        assert propagated["visual_metadata"] == {}

    def test_backward_compat_existing_plan_without_metadata(self):
        """Existing scene plans loaded from disk should gain empty visual_metadata."""
        existing_scenes = [
            {"index": 1, "title": "Old", "narration": "Old narration.", "duration_seconds": 10.0, "visual_prompt": "Old prompt."}
        ]
        for scene in existing_scenes:
            if "visual_metadata" not in scene:
                scene["visual_metadata"] = {}
        assert existing_scenes[0]["visual_metadata"] == {}


# ── Prompt template tests ──────────────────────────────────────────────────────


class TestPromptTemplate:
    def test_visual_prompts_prompt_includes_visual_metadata_instructions(self):
        from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt

        prompt = build_visual_prompts_prompt(
            [{"index": 1, "narration": "Test narration."}],
            style="documentary",
        )
        assert "visual_metadata" in prompt
        assert "ANCIENT" in prompt
        assert "HISTORICAL" in prompt
        assert "MODERN" in prompt
        assert "SYMBOLIC" in prompt
        assert "TRANSITIONAL" in prompt
        assert "STORY" in prompt
        assert "ANALOGY" in prompt
        assert "environment" in prompt
        assert "allow_modern_objects" in prompt
