"""Anchor_role unit tests for the scene planner (KAI_ANCHOR_CHARACTER_SPEC.md).

The scene planner assigns anchor_role ∈ {"primary", "spectator", "absent"} to
each scene and builds a visual_prompt that injects Kai's compressed spec per role.
"Kai" is a pipeline-internal handle — it must never appear in a visual_prompt.

These tests drive controlled scene-plan JSON (as the LLM would return it) through
the real parse path (`_parse_visual_prompts`) and the real Pydantic model
(`ScenePlan` / `Scene`), so they stay deterministic without a live LLM.
"""

from __future__ import annotations

import json

import pytest

from ytfactory.agents.nodes.scene_planner import (
    _enforce_closing_scene_primary,
    _enforce_primary_kai_spec,
    _has_kai_markers,
    _parse_visual_prompts,
    _sanitize_kai_name_from_prompts,
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

    def test_primary_prompt_has_no_kai_name(self, plan: ScenePlan):
        for scene in plan.scenes:
            if scene.anchor_role == "primary":
                assert "kai" not in scene.visual_prompt.lower()


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

    def test_spectator_prompt_has_no_kai_name(self, plan: ScenePlan):
        for scene in plan.scenes:
            if scene.anchor_role == "spectator":
                assert "kai" not in scene.visual_prompt.lower()


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

    def test_absent_prompt_has_no_kai_name(self, plan: ScenePlan):
        for scene in plan.scenes:
            if scene.anchor_role == "absent":
                assert "kai" not in scene.visual_prompt.lower()


# ── Global ───────────────────────────────────────────────────────────────────


class TestGlobalNoKaiLeak:
    def test_no_visual_prompt_contains_kai(self, plan: ScenePlan):
        for scene in plan.scenes:
            assert "kai" not in scene.visual_prompt.lower(), (
                f"Scene {scene.index} visual_prompt contains the name 'Kai'"
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
    def test_closing_scene_is_always_primary(self):
        """Last non-asset scene is forced to primary even when LLM returned spectator."""
        mock_scenes = [
            {"index": 1, "anchor_role": "primary",
             "visual_prompt": "Lean young man, short dark hair at a desk",
             "scene_type": "generated_image"},
            {"index": 2, "anchor_role": "spectator",
             "visual_prompt": "A crowd cheers in a stadium",
             "scene_type": "generated_image"},
        ]
        result = _enforce_closing_scene_primary(mock_scenes)
        assert result[-1]["anchor_role"] == "primary"
        assert _has_kai_markers(result[-1]["visual_prompt"])

    def test_primary_spec_prepended_when_missing(self):
        """Primary scenes without Kai spec markers get the spec prepended."""
        mock_scenes = [
            {"index": 1, "anchor_role": "primary",
             "visual_prompt": "A single human figure in an empty room."},
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
        """Guards must not modify absent scenes that are not the closing scene."""
        mock_scenes = [
            {"index": 1, "anchor_role": "absent",
             "visual_prompt": "A cracked hourglass on stone floor.",
             "scene_type": "generated_image"},
            {"index": 2, "anchor_role": "primary",
             "visual_prompt": "Lean young man, late 20s, short dark hair — at a window.",
             "scene_type": "generated_image"},
            {"index": 3, "anchor_role": "absent",
             "visual_prompt": "Atma Theory brand card.",
             "scene_type": "brand_card"},
        ]
        result = _enforce_primary_kai_spec(mock_scenes)
        result = _enforce_closing_scene_primary(result)
        assert result[0]["anchor_role"] == "absent"
        assert "dark hair" not in result[0]["visual_prompt"]

    def test_kai_name_stripped_from_visual_prompts(self):
        """'Kai' must never appear in visual_prompts — stripped and replaced with 'the young man'."""
        mock_scenes = [
            {"index": 1, "anchor_role": "primary",
             "visual_prompt": "Kai sits at a desk, looking out the window."},
            {"index": 2, "anchor_role": "spectator",
             "visual_prompt": "A professor lectures while Kai watches from the back."},
        ]
        result = _sanitize_kai_name_from_prompts(mock_scenes)
        for scene in result:
            assert "kai" not in scene["visual_prompt"].lower()
