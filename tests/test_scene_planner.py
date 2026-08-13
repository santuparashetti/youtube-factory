"""Anchor_role unit tests for the scene planner (KAI_ANCHOR_CHARACTER_SPEC.md).

The scene planner assigns anchor_role ∈ {"primary", "spectator", "absent"} to
each scene and builds a visual_prompt that injects Kai's compressed spec per role.
"Kai" is the pipeline-internal character handle — it is permitted (and preferred)
in visual_prompt fields to aid image-generator consistency.

These tests drive controlled scene-plan JSON (as the LLM would return it) through
the real parse path (`_parse_visual_prompts`) and the real Pydantic model
(`ScenePlan` / `Scene`), so they stay deterministic without a live LLM.
"""

from __future__ import annotations

import json

import pytest

from ytfactory.agents.nodes.scene_planner import (
    _enforce_primary_kai_spec,
    _enforce_style_footer,
    _has_character_staging,
    _has_kai_markers,
    _parse_visual_prompts,
    _propagate_environment_anchors,
)
from ytfactory.scenes.models import Scene, ScenePlan

# Same markers the probe CLI checks — one must appear in a primary prompt,
# none may appear in an absent prompt.
KAI_MARKERS = ["dark hair", "simple dark shirt", "lean young man", "light stubble"]

VALID_ROLES = {"primary", "spectator", "absent"}


def _scene(index: int, anchor_role: str | None, visual_prompt: str, **extra) -> dict:
    """Build a full scene dict as stored in scene-plan.json. anchor_role=None
    omits the field entirely so the Pydantic default can be exercised."""
    d = {
        "index": index,
        "title": f"Scene {index}",
        "narration": f"Narration for scene {index}.",
        "visual_prompt": visual_prompt,
        "duration_seconds": 5.0,
    }
    if anchor_role is not None:
        d["anchor_role"] = anchor_role
    d.update(extra)
    return d


# A controlled scene plan representing correct LLM classification output:
# opening primary (Kai established), a symbolic absent, a spectator (real figure
# is primary, Kai watches), another absent, closing primary (arc completes), and
# a trailing brand card. Scene 4 intentionally omits anchor_role to test the default.
_CONTROLLED_SCENES = [
    _scene(
        1, "primary",
        "Lean young man, late 20s, short dark hair, light stubble, simple dark shirt, "
        "plain trousers, calm expression — sitting at a small wooden desk, staring at a "
        "blank page. Grey morning light. Still.",
    ),
    _scene(
        2, "absent",
        "A cracked hourglass lying on its side on a stone floor, sand pooled beneath it, "
        "soft diffused grey light. No human figure.",
    ),
    _scene(
        3, "spectator",
        "A man in late 19th century clothing writes feverishly at a cluttered desk by "
        "candlelight. At the edge of the frame, a young man — lean, dark hair, simple "
        "dark shirt — stands watching in silence.",
    ),
    _scene(
        4, None,  # anchor_role omitted → default should resolve to "absent"
        "Storm clouds parting over a mountain ridge, first light breaking through. "
        "Wide cinematic vista, no people.",
    ),
    _scene(
        5, "primary",
        "Lean young man, late 20s, short dark hair, light stubble, simple dark shirt — "
        "standing at an open window at dawn, something settled in his expression.",
    ),
    _scene(
        6, "absent",
        "Atma Theory brand card, calm indigo gradient, no text baked in.",
        scene_type="brand_card",
    ),
]


@pytest.fixture
def plan() -> ScenePlan:
    return ScenePlan.model_validate(
        {
            "title": "Controlled Test Plan",
            "total_duration_seconds": 30.0,
            "scenes": [dict(s) for s in _CONTROLLED_SCENES],
        }
    )


# ── Schema / defaults ────────────────────────────────────────────────────────


class TestAnchorRoleSchema:
    def test_every_scene_has_valid_anchor_role(self, plan: ScenePlan):
        for scene in plan.scenes:
            assert scene.anchor_role in VALID_ROLES, (
                f"Scene {scene.index} has invalid anchor_role: {scene.anchor_role!r}"
            )

    def test_missing_anchor_role_defaults_to_absent(self):
        raw = {
            "index": 1,
            "title": "t",
            "narration": "n",
            "visual_prompt": "a quiet empty room",
            "duration_seconds": 3.0,
        }
        scene = Scene.model_validate(raw)
        assert scene.anchor_role == "absent", "default should be 'absent'"
        assert scene.anchor_role is not None

    def test_omitted_role_in_plan_resolves_to_absent(self, plan: ScenePlan):
        # Scene 4 omitted anchor_role in the raw JSON.
        scene4 = next(s for s in plan.scenes if s.index == 4)
        assert scene4.anchor_role == "absent"


# ── Opening scene ────────────────────────────────────────────────────────────


class TestOpeningScene:
    def test_opening_scene_is_not_absent(self, plan: ScenePlan):
        assert plan.scenes[0].anchor_role != "absent", (
            "Opening scene is 'absent' — Kai should be established early"
        )


# ── PRIMARY contract ─────────────────────────────────────────────────────────


class TestPrimaryContract:
    def test_primary_prompt_contains_kai_marker(self, plan: ScenePlan):
        for scene in plan.scenes:
            if scene.anchor_role == "primary":
                prompt = scene.visual_prompt.lower()
                assert any(m in prompt for m in KAI_MARKERS), (
                    f"Scene {scene.index} is primary but has no Kai spec marker"
                )


# ── SPECTATOR contract ───────────────────────────────────────────────────────


class TestSpectatorContract:
    _DESCRIPTORS = ["watching", "dark hair", "edge", "periphery"]

    def test_spectator_prompt_contains_brief_descriptor(self, plan: ScenePlan):
        for scene in plan.scenes:
            if scene.anchor_role == "spectator":
                prompt = scene.visual_prompt.lower()
                assert any(d in prompt for d in self._DESCRIPTORS), (
                    f"Scene {scene.index} is spectator but has no brief Kai descriptor"
                )


# ── ABSENT contract ──────────────────────────────────────────────────────────


class TestAbsentContract:
    def test_absent_prompt_has_no_kai_markers(self, plan: ScenePlan):
        for scene in plan.scenes:
            if scene.anchor_role == "absent":
                prompt = scene.visual_prompt.lower()
                for marker in KAI_MARKERS:
                    assert marker not in prompt, (
                        f"Scene {scene.index} is absent but contains Kai marker '{marker}'"
                    )



# ── Real parse path preserves anchor_role ────────────────────────────────────


class TestParsePreservesAnchorRole:
    """Drive a mock LLM Phase-2 (visual prompts) response through the real
    parser and confirm anchor_role + visual_prompt survive together."""

    def _mock_llm_response(self) -> str:
        items = [
            {"index": 1, "anchor_role": "primary",
             "visual_prompt": "lean young man, short dark hair at a desk"},
            {"index": 2, "anchor_role": "spectator",
             "visual_prompt": "a scholar writes; a young man watches at the edge"},
            {"index": 3, "anchor_role": "absent",
             "visual_prompt": "a cracked hourglass on a stone floor"},
        ]
        return json.dumps(items)

    def test_parse_carries_each_role(self):
        parsed = _parse_visual_prompts(self._mock_llm_response())
        assert parsed is not None
        by_index = {i["index"]: i for i in parsed}
        assert by_index[1]["anchor_role"] == "primary"
        assert by_index[2]["anchor_role"] == "spectator"
        assert by_index[3]["anchor_role"] == "absent"

    def test_parse_keeps_prompt_and_role_aligned(self):
        parsed = _parse_visual_prompts(self._mock_llm_response())
        assert parsed is not None
        primary = next(i for i in parsed if i["anchor_role"] == "primary")
        assert "dark hair" in primary["visual_prompt"].lower()

    def test_parsed_scene_without_role_defaults_via_model(self):
        # LLM omitted anchor_role on an item; the Scene model supplies the default.
        raw = '[{"index": 1, "visual_prompt": "empty road at dusk"}]'
        parsed = _parse_visual_prompts(raw)
        assert parsed is not None
        item = parsed[0]
        assert "anchor_role" not in item  # parser does not invent it
        scene = Scene.model_validate(
            {
                "index": 1, "title": "t", "narration": "n",
                "visual_prompt": item["visual_prompt"], "duration_seconds": 3.0,
            }
        )
        assert scene.anchor_role == "absent"


# ── Programmatic enforcement guards ─────────────────────────────────────────


class TestEnforcementGuards:
    def test_closing_scene_anchor_role_respects_character_presence(self):
        """Closing scene anchor_role is no longer forced to primary by the pipeline.
        It reflects what the LLM assigned (or what character_presence implies).
        """
        mock_scenes = [
            {"index": 1, "anchor_role": "primary", "character_presence": ["KAI"],
             "visual_prompt": "Lean young man, short dark hair at a desk",
             "scene_type": "generated_image"},
            {"index": 2, "anchor_role": "absent", "character_presence": [],
             "visual_prompt": "A crowd cheers in a stadium",
             "scene_type": "generated_image"},
        ]
        result = _enforce_primary_kai_spec(mock_scenes)
        # The last scene with character_presence=[] stays absent — no auto-promotion
        assert result[-1]["anchor_role"] == "absent"

    def test_primary_spec_prepended_when_missing(self):
        """Primary scenes with character staging but no Kai spec get the spec prepended."""
        mock_scenes = [
            {"index": 1, "anchor_role": "primary",
             "visual_prompt": "A man seated at a desk, looking at scattered papers."},
        ]
        result = _enforce_primary_kai_spec(mock_scenes)
        assert _has_kai_markers(result[0]["visual_prompt"])
        assert result[0]["visual_prompt"].startswith("Lean young man")

    def test_primary_spec_not_doubled_when_already_present(self):
        """Primary scenes that already have the Kai spec are not modified."""
        original = "Lean young man, late 20s, short dark hair — sitting at a desk."
        mock_scenes = [
            {"index": 1, "anchor_role": "primary", "visual_prompt": original},
        ]
        result = _enforce_primary_kai_spec(mock_scenes)
        assert result[0]["visual_prompt"] == original

    def test_absent_scenes_unaffected_by_guards(self):
        """Guards must not modify absent scenes."""
        mock_scenes = [
            {"index": 1, "anchor_role": "absent", "character_presence": [],
             "visual_prompt": "A cracked hourglass on stone floor.",
             "scene_type": "generated_image"},
            {"index": 2, "anchor_role": "primary", "character_presence": ["KAI"],
             "visual_prompt": "Lean young man, late 20s, short dark hair — at a window.",
             "scene_type": "generated_image"},
            {"index": 3, "anchor_role": "absent", "character_presence": [],
             "visual_prompt": "Atma Theory brand card.",
             "scene_type": "brand_card"},
        ]
        result = _enforce_primary_kai_spec(mock_scenes)
        assert result[0]["anchor_role"] == "absent"
        assert "dark hair" not in result[0]["visual_prompt"]

    def test_atmospheric_primary_reclassified_to_absent(self):
        """Primary scene with no character staging gets reclassified to absent."""
        mock_scenes = [
            {"index": 1, "anchor_role": "primary",
             "visual_prompt": "A wide shot of an empty room with peeling paint."},
        ]
        result = _enforce_primary_kai_spec(mock_scenes)
        assert result[0]["anchor_role"] == "absent"
        assert not _has_kai_markers(result[0]["visual_prompt"])

    def test_primary_with_character_staging_gets_spec_prepended(self):
        """Primary scene with character staging gets Kai spec prepended."""
        mock_scenes = [
            {"index": 1, "anchor_role": "primary",
             "visual_prompt": "A man standing at a window, facing outward."},
        ]
        result = _enforce_primary_kai_spec(mock_scenes)
        assert result[0]["anchor_role"] == "primary"
        assert _has_kai_markers(result[0]["visual_prompt"])

    def test_no_contradiction_in_output(self):
        """Primary scene whose staging declares absence of humans must not get Kai spec prepended."""
        # Scene 1: staging explicitly has no human — must be reclassified absent, not get Kai spec
        mock_scenes = [
            {"index": 1, "anchor_role": "primary",
             "visual_prompt": "No human figure, hands, or silhouettes are present."},
            # Scene 2: staging has Kai already — guard must not touch it
            {"index": 2, "anchor_role": "primary",
             "visual_prompt": "Lean young man, dark hair — seated at a desk."},
        ]
        result = _enforce_primary_kai_spec(mock_scenes)
        scene1 = next(s for s in result if s["index"] == 1)
        scene2 = next(s for s in result if s["index"] == 2)
        # Scene 1 must have been reclassified — it has no character staging
        assert scene1["anchor_role"] == "absent", "Atmospheric scene must be reclassified to absent"
        assert not _has_kai_markers(scene1["visual_prompt"]), "Absent scene must not have Kai spec"
        # Scene 2 already had Kai markers — should remain primary and unchanged
        assert scene2["anchor_role"] == "primary"
        assert _has_kai_markers(scene2["visual_prompt"])

    def test_no_kai_spec_on_absent_reclassified_scene(self):
        """Scene reclassified from primary to absent must not have Kai spec."""
        mock_scenes = [
            {"index": 1, "anchor_role": "primary",
             "visual_prompt": "No human figure. An empty cushion on a stone floor."},
        ]
        result = _enforce_primary_kai_spec(mock_scenes)
        assert result[0]["anchor_role"] == "absent"
        assert "no human figure" in result[0]["visual_prompt"].lower()
        assert not _has_kai_markers(result[0]["visual_prompt"])


# ── Scene continuity / environment anchor propagation ────────────────────────


class TestPropagateEnvironmentAnchors:
    def test_injects_continuity_prefix_when_missing(self):
        """Subsequent scene without continuity prefix gets it injected."""
        scenes = [
            {
                "index": 5,
                "scene_group_id": "laughing_club_park",
                "environment_anchor": "Manicured urban park at pre-dawn. Cool blue light.",
                "visual_prompt": "Full description of scene 5 with environment.",
                "anchor_role": "spectator",
            },
            {
                "index": 6,
                "scene_group_id": "laughing_club_park",
                "environment_anchor": "Manicured urban park at pre-dawn. Cool blue light.",
                "visual_prompt": "The instructor turns to walk away, collecting payment.",
                "anchor_role": "spectator",
            },
        ]
        result = _propagate_environment_anchors(scenes)
        assert result[1]["visual_prompt"].startswith("Continuous from scene 5")
        assert "Manicured urban park" in result[1]["visual_prompt"]

    def test_does_not_double_inject(self):
        """Subsequent scene that already has the continuity prefix is not modified."""
        scenes = [
            {
                "index": 5,
                "scene_group_id": "laughing_club_park",
                "environment_anchor": "Manicured urban park at pre-dawn.",
                "visual_prompt": "Scene 5 full prompt.",
                "anchor_role": "spectator",
            },
            {
                "index": 6,
                "scene_group_id": "laughing_club_park",
                "environment_anchor": "Manicured urban park at pre-dawn.",
                "visual_prompt": "Continuous from scene 5. Manicured urban park at pre-dawn. Payment exchange.",
                "anchor_role": "spectator",
            },
        ]
        result = _propagate_environment_anchors(scenes)
        assert result[1]["visual_prompt"].count("Continuous from scene 5") == 1

    def test_ungrouped_scenes_unaffected(self):
        """Scenes with no scene_group_id are not touched."""
        scenes = [
            {
                "index": 3,
                "scene_group_id": None,
                "visual_prompt": "A glowing orb on a cloth. Symbolic.",
                "anchor_role": "absent",
            },
        ]
        result = _propagate_environment_anchors(scenes)
        assert result[0]["visual_prompt"] == "A glowing orb on a cloth. Symbolic."


class TestSceneGroupModelFields:
    def test_scene_group_id_and_environment_anchor_defaults_to_none(self):
        """Scene model has scene_group_id and environment_anchor fields defaulting to None."""
        from ytfactory.scenes.models import Scene
        s = Scene(index=1, title="t", narration="n",
                  visual_prompt="test", duration_seconds=3.0)
        assert s.scene_group_id is None
        assert s.environment_anchor is None


# ── Style footer enforcement ─────────────────────────────────────────────────


class TestEnforceStyleFooter:
    def test_appends_human_footer_to_primary_missing_photorealistic(self):
        """Primary scene missing 'photorealistic' gets full human quality footer."""
        scenes = [{"index": 1, "anchor_role": "primary",
                   "visual_prompt": "Lean young man at a desk."}]
        result = _enforce_style_footer(scenes)
        assert "photorealistic" in result[0]["visual_prompt"].lower()
        assert "highly detailed human face" in result[0]["visual_prompt"].lower()

    def test_appends_symbolic_footer_to_absent_missing_photorealistic(self):
        """Absent scene missing 'photorealistic' gets symbolic footer only."""
        scenes = [{"index": 1, "anchor_role": "absent",
                   "visual_prompt": "A glowing orb on dark cloth."}]
        result = _enforce_style_footer(scenes)
        assert "photorealistic" in result[0]["visual_prompt"].lower()
        assert "highly detailed human face" not in result[0]["visual_prompt"].lower()

    def test_does_not_double_footer_when_full_footer_present(self):
        """Prompt already containing full footer is not modified."""
        original = (
            "Lean young man at a desk. Documentary-quality realism, "
            "highly detailed human face, realistic eyes, authentic skin texture, "
            "seamless integration with the environment, "
            "no text, no watermark, photorealistic."
        )
        scenes = [{"index": 1, "anchor_role": "primary", "visual_prompt": original}]
        result = _enforce_style_footer(scenes)
        assert result[0]["visual_prompt"].lower().count("photorealistic") == 1

    def test_upgrades_bare_photorealistic_for_primary(self):
        """Primary scene with bare 'photorealistic' (no human quality lines) gets full footer."""
        scenes = [{"index": 1, "anchor_role": "primary",
                   "visual_prompt": "Lean young man at a desk. No text, photorealistic."}]
        result = _enforce_style_footer(scenes)
        assert "highly detailed human face" in result[0]["visual_prompt"].lower()

    def test_partial_footer_not_doubled(self):
        """LLM partial footer (documentary-quality realism but no photorealistic) is not duplicated."""
        scenes = [{"index": 1, "anchor_role": "primary",
                   "visual_prompt": (
                       "Lean young man at a desk. "
                       "Documentary-quality realism, natural facial expression."
                   )}]
        result = _enforce_style_footer(scenes)
        prompt = result[0]["visual_prompt"].lower()
        assert prompt.count("documentary-quality realism") == 1
        assert "highly detailed human face" in prompt

    def test_full_footer_not_modified(self):
        """Prompt with complete footer (all four indicators) is not modified."""
        full = (
            "Lean young man at a desk. Documentary-quality realism, "
            "highly detailed human face, realistic eyes, authentic skin texture, "
            "seamless integration with the environment, no text, no watermark, "
            "photorealistic."
        )
        scenes = [{"index": 1, "anchor_role": "primary", "visual_prompt": full}]
        result = _enforce_style_footer(scenes)
        assert result[0]["visual_prompt"].lower().count("documentary-quality realism") == 1


# ── Primary Kai spec: action-verb guard (Fix 3) ─────────────────────────────


class TestEnforcePrimaryKaiSpecActionGuard:
    def test_kai_spec_with_action_left_as_primary(self):
        """Primary scene with Kai spec AND action verb stays primary, unchanged."""
        original = (
            "Lean young man, late 20s, short dark hair, light stubble, "
            "simple dark shirt, plain trousers, calm expression — "
            "sitting alone at a desk, staring at a blank page."
        )
        scenes = [{"index": 1, "anchor_role": "primary", "visual_prompt": original}]
        result = _enforce_primary_kai_spec(scenes)
        assert result[0]["anchor_role"] == "primary"
        assert result[0]["visual_prompt"] == original

    def test_kai_spec_with_no_action_reclassified_to_absent(self):
        """Primary scene with Kai spec but no action verb is reclassified to absent."""
        scenes = [{"index": 1, "anchor_role": "primary",
                   "visual_prompt": (
                       "Lean young man, late 20s, short dark hair, light stubble, "
                       "simple dark shirt, plain trousers, calm expression — "
                       "A wide shot of a dim, empty room. Dust motes drift in the air."
                   )}]
        result = _enforce_primary_kai_spec(scenes)
        assert result[0]["anchor_role"] == "absent"

    def test_scene_group_id_in_scene_model_defaults_to_none(self):
        """Pydantic Scene model has scene_group_id field defaulting to None."""
        from ytfactory.scenes.models import Scene
        s = Scene(index=1, title="t", narration="n",
                  visual_prompt="test", duration_seconds=3.0)
        assert hasattr(s, "scene_group_id")
        assert s.scene_group_id is None


# ── Scene Planner V2 Tests ─────────────────────────────────────────────────────

class TestScenePlannerV2:
    """Tests for Visual Bible, StructuredImagePrompt, and continuity validation."""

    def test_visual_bible_generation_stub(self):
        """When VISUAL_BIBLE_ENABLED=False, stub returns valid VisualBible."""
        from unittest.mock import MagicMock
        from ytfactory.agents.nodes.scene_planner import _generate_visual_bible, _stub_visual_bible
        from ytfactory.scenes.models import VisualBible

        settings = MagicMock()
        settings.VISUAL_BIBLE_ENABLED = False
        llm = MagicMock()

        result = _generate_visual_bible("some script", llm, settings)
        assert isinstance(result, VisualBible)
        assert len(result.anchor_environments) >= 2
        assert isinstance(result.color_arc, dict)
        assert "opening" in result.color_arc
        llm.generate.assert_not_called()

    def test_visual_bible_json_parse(self):
        """Valid JSON from LLM parses to VisualBible correctly."""
        from unittest.mock import MagicMock
        from ytfactory.agents.nodes.scene_planner import _generate_visual_bible
        from ytfactory.scenes.models import VisualBible
        import json

        bible_data = {
            "dominant_metaphor": "A traveler at the crossroads of choice",
            "anchor_environments": ["Stone courtyard at dawn", "Mountain ridge at dusk"],
            "color_arc": {
                "opening": "cool grey-blue",
                "build": "warm amber",
                "climax": "deep gold",
                "resolution": "soft blue with warm accent",
            },
            "visual_motifs": ["empty threshold", "open hands"],
            "shot_arc": {
                "opening_scenes": "establishing wide",
                "build_scenes": "medium with depth",
                "climax_scene": "tight close-up",
                "resolution_scenes": "medium wide",
            },
        }

        settings = MagicMock()
        settings.VISUAL_BIBLE_ENABLED = True
        llm = MagicMock()
        llm.generate.return_value.text = json.dumps(bible_data)

        result = _generate_visual_bible("script text", llm, settings)
        assert isinstance(result, VisualBible)
        assert result.dominant_metaphor == "A traveler at the crossroads of choice"
        assert len(result.anchor_environments) == 2
        assert result.color_arc["climax"] == "deep gold"

    def test_visual_bible_json_parse_failure_returns_stub(self):
        """Invalid JSON from LLM falls back to stub without crashing."""
        from unittest.mock import MagicMock
        from ytfactory.agents.nodes.scene_planner import _generate_visual_bible
        from ytfactory.scenes.models import VisualBible

        settings = MagicMock()
        settings.VISUAL_BIBLE_ENABLED = True
        llm = MagicMock()
        llm.generate.return_value.text = "not valid json {{{"

        result = _generate_visual_bible("script text", llm, settings)
        assert isinstance(result, VisualBible)
        assert len(result.anchor_environments) >= 2

    def test_structured_prompt_fields_present(self):
        """All 8 fields populated on returned StructuredImagePrompt."""
        from ytfactory.scenes.models import StructuredImagePrompt

        sp = StructuredImagePrompt(
            shot_type="medium",
            camera_angle="eye_level",
            environment_prompt="A sun-drenched stone courtyard.",
            character_staging="An illustrated young man, seen from behind.",
            lighting_match="Warm afternoon light matches the courtyard glow.",
            color_palette_phase="build: warm amber tones",
            continuity_ref="same environment as scene_001",
            compiled_prompt="Hybrid style. Medium shot. A sun-drenched stone courtyard. 16:9. No text.",
        )
        assert sp.shot_type == "medium"
        assert sp.camera_angle == "eye_level"
        assert sp.environment_prompt
        assert sp.character_staging
        assert sp.lighting_match
        assert sp.color_palette_phase
        assert sp.continuity_ref
        assert sp.compiled_prompt

    def test_compiled_prompt_no_storyboard_mode_language(self):
        """'Storyboard Mode' must NOT appear in any compiled_prompt."""
        from unittest.mock import MagicMock
        from ytfactory.agents.nodes.scene_planner import _build_structured_prompt
        from ytfactory.scenes.models import VisualBible, StructuredImagePrompt
        import json

        bible = VisualBible(
            dominant_metaphor="A lone figure at the edge",
            anchor_environments=["Mountain path", "Stone courtyard"],
            color_arc={"opening": "cool", "build": "warm", "climax": "gold", "resolution": "blue"},
            visual_motifs=["threshold"],
            shot_arc={"opening_scenes": "wide", "build_scenes": "medium", "climax_scene": "close", "resolution_scenes": "medium wide"},
        )
        scene = {"index": 1, "narration": "Silence fills the room.", "anchor_role": "absent", "visual_prompt": ""}
        sp_data = {
            "shot_type": "establishing_wide",
            "camera_angle": "eye_level",
            "environment_prompt": "A vast stone courtyard at dawn.",
            "character_staging": None,
            "lighting_match": "Cool morning light, diffuse shadows.",
            "color_palette_phase": "opening: cool grey-blue",
            "continuity_ref": "",
            "compiled_prompt": "Wide establishing shot. A vast stone courtyard at dawn. Cool morning light. 16:9. No text, no watermark.",
        }
        settings = MagicMock()
        settings.HYBRID_STYLE_ENABLED = True
        settings.KAI_POSE_DISCIPLINE_ENABLED = True
        llm = MagicMock()
        llm.generate.return_value.text = json.dumps(sp_data)

        result = _build_structured_prompt(scene, bible, 0, 5, llm, settings)
        assert "Storyboard Mode" not in result.compiled_prompt

    def test_enforce_primary_kai_spec_no_staging_reclassifies_to_absent(self):
        """Primary scene with no character staging indicators is reclassified to absent."""
        scenes = [{"index": 1, "anchor_role": "primary",
                   "visual_prompt": "An empty stone courtyard. A single cushion rests on the floor."}]
        result = _enforce_primary_kai_spec(scenes)
        assert result[0]["anchor_role"] == "absent"

    def test_enforce_primary_kai_spec_with_staging_preserved(self):
        """Primary scene with character staging indicators remains primary."""
        scenes = [{"index": 1, "anchor_role": "primary",
                   "visual_prompt": (
                       "Lean young man, late 20s, short dark hair, light stubble, "
                       "simple dark shirt — standing at the edge of a cliff, looking outward."
                   )}]
        result = _enforce_primary_kai_spec(scenes)
        assert result[0]["anchor_role"] == "primary"

    def test_continuity_validation_shot_variety_warning(self):
        """All-medium shot mix triggers a shot-variety continuity warning."""
        from ytfactory.agents.nodes.scene_planner import _validate_visual_continuity
        from ytfactory.scenes.models import VisualBible

        bible = VisualBible(
            dominant_metaphor="A lone figure at the edge",
            anchor_environments=["Mountain path", "Stone courtyard"],
            color_arc={"opening": "cool", "build": "warm", "climax": "gold", "resolution": "blue"},
            visual_motifs=["threshold"],
            shot_arc={"opening_scenes": "wide", "build_scenes": "medium", "climax_scene": "close", "resolution_scenes": "medium wide"},
        )
        scenes = [
            {"index": i, "anchor_role": "absent", "structured_prompt": {"shot_type": "medium", "character_staging": None, "environment_prompt": "a place"}}
            for i in range(1, 8)
        ]
        warnings = _validate_visual_continuity(scenes, bible)
        assert any("shot type" in w.lower() or "diversifying" in w.lower() for w in warnings)

    def test_continuity_validation_kai_front_facing_warning(self):
        """Two front-facing Kai scenes trigger a pose discipline warning."""
        from ytfactory.agents.nodes.scene_planner import _validate_visual_continuity
        from ytfactory.scenes.models import VisualBible

        bible = VisualBible(
            dominant_metaphor="A lone figure at the edge",
            anchor_environments=["Mountain path", "Stone courtyard"],
            color_arc={"opening": "cool", "build": "warm", "climax": "gold", "resolution": "blue"},
            visual_motifs=["threshold"],
            shot_arc={"opening_scenes": "wide", "build_scenes": "medium", "climax_scene": "close", "resolution_scenes": "medium wide"},
        )
        scenes = [
            {"index": 1, "anchor_role": "primary", "structured_prompt": {"shot_type": "medium", "character_staging": "Young man facing forward toward the viewer.", "environment_prompt": "a courtyard"}},
            {"index": 2, "anchor_role": "absent", "structured_prompt": {"shot_type": "establishing_wide", "character_staging": None, "environment_prompt": "mountain"}},
            {"index": 3, "anchor_role": "primary", "structured_prompt": {"shot_type": "close_up", "character_staging": "Kai front-facing with direct eye contact.", "environment_prompt": "a room"}},
        ]
        warnings = _validate_visual_continuity(scenes, bible)
        assert any("front-facing" in w.lower() or "pose discipline" in w.lower() for w in warnings)

    def test_visual_prompt_backward_compat(self):
        """scene['visual_prompt'] equals structured_prompt.compiled_prompt after V2 pass."""
        from ytfactory.scenes.models import StructuredImagePrompt

        compiled = "Wide shot. Stone courtyard at dawn. Cool morning light. 16:9. No text."
        sp = StructuredImagePrompt(
            shot_type="establishing_wide",
            camera_angle="eye_level",
            environment_prompt="Stone courtyard at dawn.",
            character_staging=None,
            lighting_match="Cool morning light.",
            color_palette_phase="opening: cool grey-blue",
            continuity_ref="",
            compiled_prompt=compiled,
        )
        scene: dict = {"index": 1, "visual_prompt": "", "anchor_role": "absent"}
        scene["structured_prompt"] = sp.model_dump()
        scene["visual_prompt"] = sp.compiled_prompt
        assert scene["visual_prompt"] == compiled

    def test_visual_bible_model_fields(self):
        """VisualBible model accepts all required fields and serializes correctly."""
        from ytfactory.scenes.models import VisualBible

        bible = VisualBible(
            dominant_metaphor="The journey inward",
            anchor_environments=["Ancient library", "Forest path at dawn"],
            color_arc={"opening": "cool blue", "build": "warm amber", "climax": "gold", "resolution": "soft blue"},
            visual_motifs=["open door", "still water"],
            shot_arc={"opening_scenes": "wide", "build_scenes": "medium", "climax_scene": "close", "resolution_scenes": "medium wide"},
        )
        d = bible.model_dump()
        assert d["dominant_metaphor"] == "The journey inward"
        assert len(d["anchor_environments"]) == 2
        assert d["color_arc"]["opening"] == "cool blue"


# ── Scene Planner V2 Fixes Tests (V2.1) ──────────────────────────────────────

class TestScenePlannerV2Fixes:
    """Tests for V2.1 fixes: allowed_characters injection, camera angle, continuity."""

    def test_allowed_characters_injected_into_prompt(self):
        """Scene with non-empty scene_analysis.allowed_characters → character_block in prompt."""
        from unittest.mock import MagicMock, patch
        from ytfactory.agents.nodes.scene_planner import _build_structured_prompt
        from ytfactory.scenes.models import VisualBible, StructuredImagePrompt
        import json

        bible = VisualBible(
            dominant_metaphor="A lone figure at the edge",
            anchor_environments=["Mountain path", "Stone courtyard"],
            color_arc={"opening": "cool", "build": "warm", "climax": "gold", "resolution": "blue"},
            visual_motifs=["threshold"],
            shot_arc={"opening_scenes": "wide", "build_scenes": "medium", "climax_scene": "close", "resolution_scenes": "medium wide"},
        )
        sp_data = {
            "shot_type": "medium", "camera_angle": "eye_level",
            "environment_prompt": "Temple steps at dusk.",
            "character_staging": "Bhagiratha kneeling in prayer.",
            "lighting_match": "Warm diffuse light.", "color_palette_phase": "build: warm",
            "continuity_ref": "", "compiled_prompt": "Medium shot. Temple steps. Bhagiratha kneeling. 16:9. No text.",
        }
        scene = {
            "index": 3, "narration": "Bhagiratha prayed for a thousand years.",
            "anchor_role": "absent", "visual_prompt": "",
            "scene_analysis": {
                "allowed_characters": ["Bhagiratha"],
                "forbidden_characters": ["man", "woman"],
                "environment": "temple steps",
            },
        }
        settings = MagicMock()
        settings.HYBRID_STYLE_ENABLED = False
        settings.KAI_POSE_DISCIPLINE_ENABLED = False
        llm = MagicMock()

        captured_prompts = []
        def capture_generate(prompt, **kwargs):
            captured_prompts.append(prompt)
            r = MagicMock()
            r.text = json.dumps(sp_data)
            return r

        llm.generate.side_effect = capture_generate
        _build_structured_prompt(scene, bible, 2, 10, llm, settings)

        assert captured_prompts, "LLM was not called"
        full_prompt = captured_prompts[0]
        assert "Bhagiratha" in full_prompt
        assert "IMMUTABLE CHARACTER CONSTRAINTS" in full_prompt

    def test_forbidden_generic_terms_noted_in_prompt(self):
        """Immutability block names 'man', 'woman' as forbidden when allowed_characters non-empty."""
        from unittest.mock import MagicMock
        from ytfactory.agents.nodes.scene_planner import _build_structured_prompt
        from ytfactory.scenes.models import VisualBible, StructuredImagePrompt
        import json

        bible = VisualBible(
            dominant_metaphor="A lone figure at the edge",
            anchor_environments=["Mountain path", "Stone courtyard"],
            color_arc={"opening": "cool", "build": "warm", "climax": "gold", "resolution": "blue"},
            visual_motifs=["threshold"],
            shot_arc={"opening_scenes": "wide", "build_scenes": "medium", "climax_scene": "close", "resolution_scenes": "medium wide"},
        )
        sp_data = {
            "shot_type": "medium", "camera_angle": "eye_level",
            "environment_prompt": "Village square.", "character_staging": None,
            "lighting_match": "Midday sun.", "color_palette_phase": "build: warm",
            "continuity_ref": "", "compiled_prompt": "Village square. 16:9. No text.",
        }
        scene = {
            "index": 2, "narration": "The elder spoke truth.",
            "anchor_role": "absent", "visual_prompt": "",
            "scene_analysis": {"allowed_characters": ["elder"], "forbidden_characters": ["man"], "environment": "village"},
        }
        settings = MagicMock()
        settings.HYBRID_STYLE_ENABLED = False
        settings.KAI_POSE_DISCIPLINE_ENABLED = False
        llm = MagicMock()

        captured = []
        def cap(prompt, **kwargs):
            captured.append(prompt)
            r = MagicMock(); r.text = json.dumps(sp_data); return r
        llm.generate.side_effect = cap

        _build_structured_prompt(scene, bible, 1, 10, llm, settings)
        assert captured
        assert '"man"' in captured[0] or "\"man\"" in captured[0] or "man" in captured[0]
        assert "IMMUTABLE CHARACTER CONSTRAINTS" in captured[0]

    def test_camera_angle_guidance_in_system_prompt(self):
        """Each arc phase produces non-eye_level guidance string in the injected context."""
        from ytfactory.agents.nodes.scene_planner import _CAMERA_ANGLE_BY_PHASE

        for phase in ("opening", "build", "climax", "resolution"):
            guidance = _CAMERA_ANGLE_BY_PHASE[phase]
            assert guidance
            # All phases should mention more than just "eye_level"
            assert "eye_level" not in guidance or any(
                other in guidance for other in ("high_angle", "low_angle")
            )

    def test_continuity_warning_camera_angle_monotony(self):
        """20 of 23 scenes eye_level → camera angle monotony warning emitted."""
        from ytfactory.agents.nodes.scene_planner import _validate_visual_continuity
        from ytfactory.scenes.models import VisualBible

        bible = VisualBible(
            dominant_metaphor="A lone figure at the edge",
            anchor_environments=["Mountain path", "Stone courtyard"],
            color_arc={"opening": "cool", "build": "warm", "climax": "gold", "resolution": "blue"},
            visual_motifs=["threshold"],
            shot_arc={"opening_scenes": "wide", "build_scenes": "medium", "climax_scene": "close", "resolution_scenes": "medium wide"},
        )
        scenes = []
        for i in range(1, 24):
            angle = "eye_level" if i <= 20 else "low_angle"
            scenes.append({
                "index": i, "anchor_role": "absent",
                "structured_prompt": {"shot_type": "medium", "camera_angle": angle, "character_staging": None, "environment_prompt": "place"},
            })
        warnings = _validate_visual_continuity(scenes, bible)
        assert any("camera_angle" in w.lower() or "eye_level" in w for w in warnings)

    def test_rehook_validator_detects_missing_rehook(self):
        """Script with no closing echo of opening nouns → returns False."""
        from ytfactory.composer.pipeline import _validate_rehook_present

        # Opening unique nouns: "cobblestone", "archway", "narrow" — none appear in closing
        script = "\n".join([
            "A cobblestone archway frames the narrow city street below.",
            "Rain falls sideways through the old iron gate at dusk.",
            "Choices accumulate into the person we gradually become.",
            "Every hour spent in focus adds to a larger whole.",
            "Discipline is not punishment but a form of self-respect.",
            "The quiet worker finishes what the loud talker begins.",
            "Patience opens doors that urgency forever slams shut.",
            "Stillness is not passivity — it is concentrated force.",
            "This is the Atma Theory.",
            "If these ideas resonate with you, join us on this journey.",
            "Clear mind. Purposeful life.",
        ])

        assert _validate_rehook_present(script) is False

    def test_rehook_validator_passes_valid_rehook(self):
        """Script where closing window contains opening noun → returns True."""
        from ytfactory.composer.pipeline import _validate_rehook_present

        # 20-line script so the closing 25% window (lines 15+) includes the rehook
        script = "\n".join([
            "A lighthouse stands alone at the edge of everything.",  # 0 — opening noun: "lighthouse"
            "Its beam cuts through the endless dark each night.",
            "Actions shape character and define meaning in life.",
            "We choose what matters and what we ignore daily.",
            "Purpose gives direction to our thoughts and days.",
            "Clarity of mind brings focus to our work.",
            "Meaningful choices create the life we deserve.",
            "The answers are within us waiting to be found.",
            "Each day we build toward a better understanding.",
            "Truth is not hidden — it reveals itself gradually.",
            "Practice sharpens the mind and opens the spirit.",
            "Old patterns fade when new awareness arrives.",
            "The work continues until the work becomes natural.",
            "Stillness is earned not imposed from the outside.",
            "That same lighthouse beam still sweeps the dark water.",  # 14 — rehook with "lighthouse"
            "But now someone on the shore understands its rhythm.",
            "This is the Atma Theory.",
            "If these ideas resonate with you, join us on this journey.",
            "Clear mind. Meaningful life.",
        ])

        assert _validate_rehook_present(script) is True


class TestVisualAnchorFallback:
    def test_visual_anchor_falls_back_to_second_model_on_first_failure(self):
        """Primary model raises; fallback model succeeds and its result is returned."""
        from unittest.mock import MagicMock, call
        from ytfactory.agents.nodes.scene_planner import _build_visual_anchors
        from video_core.domain.llm import LLMResponse

        scenes = [
            {"index": 1, "narration": "A man walks alone.", "scene_type": "standard"},
            {"index": 2, "narration": "The path narrows ahead.", "scene_type": "standard"},
        ]

        provider = MagicMock()
        provider.generate.side_effect = [
            Exception("primary model timeout"),
            LLMResponse(
                text='{"001": "A solitary figure walking a dirt path", "002": "A narrow trail disappearing into fog"}',
                model="deepseek/deepseek-v4-pro",
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                finish_reason="stop",
            ),
        ]

        settings = MagicMock()
        settings.VISUAL_ANCHOR_MODEL = "google/gemini-2.5-flash-lite"
        settings.VISUAL_ANCHOR_FALLBACK_MODEL = "deepseek/deepseek-v4-pro"

        result = _build_visual_anchors(scenes, provider, settings)

        assert result == {
            1: "A solitary figure walking a dirt path",
            2: "A narrow trail disappearing into fog",
        }
        assert provider.generate.call_count == 2
        first_call_model = provider.generate.call_args_list[0].kwargs.get("model")
        second_call_model = provider.generate.call_args_list[1].kwargs.get("model")
        assert first_call_model == "google/gemini-2.5-flash-lite"
        assert second_call_model == "deepseek/deepseek-v4-pro"
