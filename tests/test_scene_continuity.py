"""Tests for scene_continuity — StoryStateTracker, ContinuityValidator, ActionConstraint.

Covers all 14 problem classes from the image prompt pipeline audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from ytfactory.scene_continuity.models import (
    CharacterState,
    ContinuityFinding,
    PropState,
    SceneMode,
    StoryState,
    ValidationLevel,
    is_symbolic_mode,
    scene_mode_from_narrative_role,
)
from ytfactory.scene_continuity.tracker import (
    StoryStateTracker,
    _extract_prop_state_from_narration,
    _infer_death_from_narration,
    _slugify,
    build_story_state,
)
from ytfactory.scene_continuity.validator import ContinuityValidator
from ytfactory.scene_continuity.action_grounding import (
    ActionConstraint,
    build_action_constraints_block,
    extract_action_constraints,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeVisualMeta:
    narrative_role: str = "STORY"


@dataclass
class FakeSceneAnalysis:
    scene_id: int = 0
    allowed_characters: list[str] = field(default_factory=list)
    forbidden_characters: list[str] = field(default_factory=list)
    primary_subject: str = ""
    scene_objects: list[str] = field(default_factory=list)


@dataclass
class FakeScene:
    narration: str = ""
    visual_prompt: str = ""
    visual_metadata: FakeVisualMeta = field(default_factory=FakeVisualMeta)


def _make_state_with_dead(char_name: str, scene_died: int) -> StoryState:
    state = StoryState()
    cid = _slugify(char_name)
    char = CharacterState(name=char_name, canonical_id=cid, alive=False, scene_last_seen=scene_died)
    from ytfactory.scene_continuity.models import SceneState
    state.characters[cid] = char
    state.scene_modes[0] = SceneMode.LITERAL
    # record history at scene 0
    state.scene_history[0] = SceneState(
        scene_id=0,
        mode=SceneMode.LITERAL,
        characters_present=[],
        character_states={cid: char},
        prop_states={},
    )
    return state


# ===========================================================================
# 1. SceneMode mapping
# ===========================================================================

class TestSceneMode:
    def test_story_maps_to_literal(self):
        assert scene_mode_from_narrative_role("STORY") == SceneMode.LITERAL

    def test_metaphor_maps_to_symbolic(self):
        assert scene_mode_from_narrative_role("METAPHOR") == SceneMode.SYMBOLIC

    def test_analogy_maps_to_symbolic(self):
        assert scene_mode_from_narrative_role("ANALOGY") == SceneMode.SYMBOLIC

    def test_explanation_maps_to_transitional(self):
        assert scene_mode_from_narrative_role("EXPLANATION") == SceneMode.TRANSITIONAL

    def test_cta_maps_to_cta(self):
        assert scene_mode_from_narrative_role("CTA") == SceneMode.CTA

    def test_unknown_defaults_to_literal(self):
        assert scene_mode_from_narrative_role("RANDOM_JUNK") == SceneMode.LITERAL

    def test_case_insensitive(self):
        assert scene_mode_from_narrative_role("story") == SceneMode.LITERAL

    def test_is_symbolic_mode_symbolic(self):
        assert is_symbolic_mode(SceneMode.SYMBOLIC) is True

    def test_is_symbolic_mode_cta(self):
        assert is_symbolic_mode(SceneMode.CTA) is True

    def test_is_symbolic_mode_literal_is_false(self):
        assert is_symbolic_mode(SceneMode.LITERAL) is False


# ===========================================================================
# 2. CharacterState
# ===========================================================================

class TestCharacterState:
    def test_alive_and_present_is_available(self):
        cs = CharacterState(name="Traveler", canonical_id="traveler")
        assert cs.is_available_for_literal_scene() is True

    def test_dead_not_available(self):
        cs = CharacterState(name="Traveler", canonical_id="traveler", alive=False)
        assert cs.is_available_for_literal_scene() is False

    def test_absent_not_available(self):
        cs = CharacterState(name="Traveler", canonical_id="traveler", present_in_story=False)
        assert cs.is_available_for_literal_scene() is False


# ===========================================================================
# 3. PropState state contradiction checks
# ===========================================================================

class TestPropState:
    def test_lit_vs_unlit_contradiction(self):
        prop = PropState(name="oil lamp", canonical_id="oil_lamp", current_state="lit",
                         scene_last_modified=3)
        ok, reason = prop.can_be_in_state("unlit")
        assert ok is False
        assert "oil lamp" in reason

    def test_unlit_vs_lit_contradiction(self):
        prop = PropState(name="oil lamp", canonical_id="oil_lamp", current_state="unlit",
                         scene_last_modified=5)
        ok, reason = prop.can_be_in_state("lit")
        assert ok is False

    def test_full_vs_empty_contradiction(self):
        prop = PropState(name="flask", canonical_id="flask", current_state="full",
                         scene_last_modified=2)
        ok, _ = prop.can_be_in_state("empty")
        assert ok is False

    def test_empty_vs_full_contradiction(self):
        prop = PropState(name="flask", canonical_id="flask", current_state="empty",
                         scene_last_modified=2)
        ok, _ = prop.can_be_in_state("full")
        assert ok is False

    def test_no_state_is_compatible(self):
        prop = PropState(name="flask", canonical_id="flask", current_state="")
        ok, _ = prop.can_be_in_state("full")
        assert ok is True

    def test_same_state_family_is_compatible(self):
        prop = PropState(name="torch", canonical_id="torch", current_state="lit",
                         scene_last_modified=1)
        ok, _ = prop.can_be_in_state("burning")
        # "burning" is in _LIT family, same family — no contradiction expected
        # Actually both are in LIT; our code only checks LIT-vs-UNLIT cross
        assert ok is True


# ===========================================================================
# 4. PropState extraction from narration
# ===========================================================================

class TestPropStateExtraction:
    def test_pour_oil_into_lamp(self):
        narration = "He carefully pours oil into the old lamp and lights it."
        result = _extract_prop_state_from_narration(narration)
        assert "oil_lamp" in result
        # Should detect filling OR lighting — accept either valid state
        assert result["oil_lamp"] in {"full", "lit"}

    def test_lamp_extinguished(self):
        narration = "The flame extinguishes as the wind howls through the window."
        result = _extract_prop_state_from_narration(narration)
        assert result.get("oil_lamp") == "unlit"

    def test_flask_emptied(self):
        narration = "She empties her flask, the last drop hitting the dust."
        result = _extract_prop_state_from_narration(narration)
        assert result.get("flask") == "empty"

    def test_no_props(self):
        narration = "The merchant walked silently through the bazaar."
        result = _extract_prop_state_from_narration(narration)
        assert result == {}


# ===========================================================================
# 5. Death detection from narration
# ===========================================================================

class TestDeathDetection:
    def test_dies_detected(self):
        narration = "The old sage dies peacefully under the banyan tree."
        result = _infer_death_from_narration(narration)
        assert len(result) > 0
        assert any("sage" in r for r in result)

    def test_falls_dead_detected(self):
        narration = "The warrior falls dead on the battlefield."
        result = _infer_death_from_narration(narration)
        assert any("warrior" in r for r in result)

    def test_no_death(self):
        narration = "The merchant smiled and handed over the scroll."
        result = _infer_death_from_narration(narration)
        assert result == []

    def test_life_ended_implicit(self):
        narration = "His life ended there. The gold remained in the earth."
        result = _infer_death_from_narration(narration)
        assert "__implicit__" in result

    def test_life_ended_her(self):
        narration = "Her life was over. Nothing remained."
        result = _infer_death_from_narration(narration)
        assert "__implicit__" in result

    def test_implicit_death_resolves_to_last_active_protagonist(self):
        tracker = StoryStateTracker()
        tracker.process_scene(
            0, "The Traveler begins.", FakeSceneAnalysis(allowed_characters=["Traveler"])
        )
        # S15-style: implicit death via "his life ended"
        tracker.process_scene(
            1, "His life ended there.", FakeSceneAnalysis(allowed_characters=[])
        )
        assert not tracker.story_state.characters["traveler"].alive


# ===========================================================================
# 6. StoryStateTracker — scene processing
# ===========================================================================

class TestStoryStateTracker:
    def _analysis(self, allowed: list[str], forbidden: list[str] | None = None,
                  scene_objects: list[str] | None = None) -> FakeSceneAnalysis:
        return FakeSceneAnalysis(
            allowed_characters=allowed,
            forbidden_characters=forbidden or [],
            scene_objects=scene_objects or [],
        )

    def test_new_character_introduced(self):
        tracker = StoryStateTracker()
        tracker.process_scene(0, "The Traveler begins his journey.", self._analysis(["Traveler"]))
        assert "traveler" in tracker.story_state.characters

    def test_character_death_marks_not_alive(self):
        tracker = StoryStateTracker()
        tracker.process_scene(0, "The Traveler begins his journey.", self._analysis(["Traveler"]))
        tracker.process_scene(1, "The Traveler dies fighting the dragon.", self._analysis([]))
        assert tracker.story_state.characters["traveler"].alive is False

    def test_symbolic_scene_doesnt_update_character_state(self):
        tracker = StoryStateTracker()
        tracker.process_scene(0, "The Traveler begins.", self._analysis(["Traveler"]))
        # Symbolic scene with "death" language should NOT kill the character
        tracker.process_scene(1, "The old world dies.", None, narrative_role="METAPHOR")
        assert tracker.story_state.characters["traveler"].alive is True

    def test_prop_state_tracked(self):
        tracker = StoryStateTracker()
        tracker.process_scene(
            0, "He pours oil into the lamp and lights it.",
            self._analysis([])
        )
        assert "oil_lamp" in tracker.story_state.props

    def test_snapshot_captured_after_scene(self):
        tracker = StoryStateTracker()
        tracker.process_scene(0, "The Traveler arrives.", self._analysis(["Traveler"]))
        assert 0 in tracker.story_state.scene_history

    def test_get_state_before_scene_empty_for_first(self):
        tracker = StoryStateTracker()
        tracker.process_scene(0, "Start.", self._analysis(["Hero"]))
        chars, props = tracker.story_state.get_state_before_scene(0)
        assert chars == {}
        assert props == {}

    def test_get_state_before_scene_after_intro(self):
        tracker = StoryStateTracker()
        tracker.process_scene(0, "Hero starts.", self._analysis(["Hero"]))
        tracker.process_scene(1, "Hero continues.", self._analysis(["Hero"]))
        chars, _ = tracker.story_state.get_state_before_scene(1)
        assert "hero" in chars


# ===========================================================================
# 7. build_story_state integration
# ===========================================================================

class TestBuildStoryState:
    def test_returns_story_state(self):
        scenes = [FakeScene(narration="Hero arrives."), FakeScene(narration="Hero leaves.")]
        analysis_map = {
            0: FakeSceneAnalysis(allowed_characters=["Hero"]),
            1: FakeSceneAnalysis(allowed_characters=["Hero"]),
        }
        state = build_story_state(scenes, analysis_map)
        assert isinstance(state, StoryState)
        assert "hero" in state.characters

    def test_symbolic_scene_skipped_in_state(self):
        scenes = [
            FakeScene(narration="Hero walks.", visual_metadata=FakeVisualMeta("STORY")),
            FakeScene(narration="The hero dies in metaphor.", visual_metadata=FakeVisualMeta("METAPHOR")),
            FakeScene(narration="Hero continues walking.", visual_metadata=FakeVisualMeta("STORY")),
        ]
        analysis_map = {
            0: FakeSceneAnalysis(allowed_characters=["Hero"]),
            1: FakeSceneAnalysis(allowed_characters=[]),
            2: FakeSceneAnalysis(allowed_characters=["Hero"]),
        }
        state = build_story_state(scenes, analysis_map)
        # Hero should still be alive because scene 1 was METAPHOR, not STORY
        if "hero" in state.characters:
            assert state.characters["hero"].alive is True


# ===========================================================================
# 8. ContinuityValidator — dead character check
# ===========================================================================

class TestContinuityValidatorDeadCharacter:
    def _validator_with_dead(self, char_name: str, scene_died: int) -> ContinuityValidator:
        state = _make_state_with_dead(char_name, scene_died)
        return ContinuityValidator(state)

    def test_dead_character_in_prompt_is_error(self):
        v = self._validator_with_dead("Traveler", 0)
        scene = FakeScene(
            narration="The old sage speaks.",
            visual_prompt="The Traveler sits calmly by the river.",
        )
        findings = v.validate_scene(5, scene, None)
        errors = [f for f in findings if f.level == ValidationLevel.ERROR]
        assert len(errors) >= 1
        assert any("Traveler" in f.message for f in errors)

    def test_alive_character_in_prompt_no_error(self):
        state = StoryState()
        state.characters["hero"] = CharacterState(name="Hero", canonical_id="hero", alive=True)
        from ytfactory.scene_continuity.models import SceneState
        state.scene_history[0] = SceneState(
            scene_id=0, mode=SceneMode.LITERAL,
            character_states={"hero": state.characters["hero"]},
            prop_states={},
        )
        v = ContinuityValidator(state)
        scene = FakeScene(
            narration="The hero fights bravely.",
            visual_prompt="The Hero charges forward with sword raised.",
        )
        findings = v.validate_scene(5, scene, None)
        errors = [f for f in findings if f.level == ValidationLevel.ERROR
                  and f.category == "CHARACTER_CONTINUITY"]
        assert errors == []


# ===========================================================================
# 9. ContinuityValidator — forbidden character check
# ===========================================================================

class TestContinuityValidatorForbiddenCharacter:
    def test_forbidden_character_in_prompt_is_error(self):
        state = StoryState()
        v = ContinuityValidator(state)
        analysis = FakeSceneAnalysis(
            allowed_characters=["Hero"],
            forbidden_characters=["Villain"],
        )
        scene = FakeScene(
            narration="The hero advances.",
            visual_prompt="The Villain and Hero face each other.",
        )
        findings = v.validate_scene(3, scene, analysis)
        errors = [f for f in findings if f.category == "EXTRA_CHARACTER"]
        assert len(errors) >= 1

    def test_no_forbidden_no_error(self):
        state = StoryState()
        v = ContinuityValidator(state)
        analysis = FakeSceneAnalysis(
            allowed_characters=["Hero"],
            forbidden_characters=["Villain"],
        )
        scene = FakeScene(
            narration="The hero advances.",
            visual_prompt="The Hero walks forward under the bright sun.",
        )
        findings = v.validate_scene(3, scene, analysis)
        errors = [f for f in findings if f.category == "EXTRA_CHARACTER"]
        assert errors == []


# ===========================================================================
# 10. ContinuityValidator — prop state contradiction check
# ===========================================================================

class TestContinuityValidatorPropState:
    def _state_with_prop(self, prop_name: str, current_state: str, scene_set: int) -> StoryState:
        from ytfactory.scene_continuity.models import SceneState
        state = StoryState()
        cid = _slugify(prop_name)
        prop = PropState(name=prop_name, canonical_id=cid, current_state=current_state,
                         scene_last_modified=scene_set)
        state.props[cid] = prop
        state.scene_modes[0] = SceneMode.LITERAL
        state.scene_history[0] = SceneState(
            scene_id=0, mode=SceneMode.LITERAL,
            character_states={},
            prop_states={cid: prop},
        )
        return state

    def test_lamp_unlit_but_prompt_says_glowing(self):
        state = self._state_with_prop("oil lamp", "unlit", 2)
        v = ContinuityValidator(state)
        scene = FakeScene(
            narration="He holds up the lamp.",
            visual_prompt="The glowing oil lamp illuminates the room.",
        )
        findings = v.validate_scene(5, scene, None)
        warnings = [f for f in findings if f.category == "PROP_STATE"]
        assert len(warnings) >= 1

    def test_lamp_lit_consistent_no_warning(self):
        state = self._state_with_prop("oil lamp", "lit", 2)
        v = ContinuityValidator(state)
        scene = FakeScene(
            narration="He reads by lamplight.",
            visual_prompt="The burning oil lamp casts warm light.",
        )
        findings = v.validate_scene(5, scene, None)
        warnings = [f for f in findings if f.category == "PROP_STATE"]
        assert warnings == []


# ===========================================================================
# 11. ContinuityValidator — narration coverage check
# ===========================================================================

class TestNarrationCoverage:
    def test_completely_disconnected_prompt_warns(self):
        state = StoryState()
        v = ContinuityValidator(state)
        scene = FakeScene(
            narration="The weaver carefully threads silk through the ancient loom in the workshop.",
            visual_prompt="A majestic mountain range at sunset with golden clouds.",
        )
        findings = v.validate_scene(3, scene, None)
        warnings = [f for f in findings if f.category == "NARRATION_COVERAGE"]
        assert len(warnings) >= 1

    def test_connected_prompt_no_warning(self):
        state = StoryState()
        v = ContinuityValidator(state)
        scene = FakeScene(
            narration="The weaver carefully threads silk through the ancient loom.",
            visual_prompt="A weaver threading silk through a traditional wooden loom in a workshop.",
        )
        findings = v.validate_scene(3, scene, None)
        warnings = [f for f in findings if f.category == "NARRATION_COVERAGE"]
        assert warnings == []


# ===========================================================================
# 12. ContinuityValidator — symbolic scene relaxation
# ===========================================================================

class TestSymbolicSceneRelaxation:
    def test_dead_character_in_symbolic_scene_not_flagged(self):
        state = _make_state_with_dead("Traveler", 2)
        v = ContinuityValidator(state)
        scene = FakeScene(
            narration="The spirit of the traveler lingers.",
            visual_prompt="The Traveler's ghostly form drifts over the mountains.",
            visual_metadata=FakeVisualMeta("METAPHOR"),
        )
        findings = v.validate_scene(7, scene, None)
        char_errors = [f for f in findings if f.category == "CHARACTER_CONTINUITY"]
        assert char_errors == []


# ===========================================================================
# 13. Action grounding — extract_action_constraints
# ===========================================================================

class TestActionConstraints:
    def test_pour_oil_into_lamp(self):
        narration = "She pours oil into the lamp to keep the flame alive."
        constraints = extract_action_constraints(narration)
        assert len(constraints) >= 1
        assert any("POURING OIL" in c.constraint for c in constraints)

    def test_lights_a_lamp(self):
        narration = "The monk lights the oil lamp at dawn."
        constraints = extract_action_constraints(narration)
        assert any("LIGHTING" in c.constraint for c in constraints)

    def test_writes_on_scroll(self):
        narration = "The scribe writes on the parchment."
        constraints = extract_action_constraints(narration)
        assert any("WRITING" in c.constraint for c in constraints)

    def test_rides_horse(self):
        narration = "The warrior rides his horse across the plains."
        constraints = extract_action_constraints(narration)
        assert any("RIDING" in c.constraint for c in constraints)

    def test_no_constraints_for_simple_narration(self):
        narration = "He smiled and walked away."
        constraints = extract_action_constraints(narration)
        assert constraints == []

    def test_builds_constraints_block(self):
        narration = "The traveler pours oil into the lamp."
        block = build_action_constraints_block(narration)
        assert "PHYSICAL ACTION GROUNDING" in block
        assert "POURING OIL" in block

    def test_empty_block_for_no_actions(self):
        narration = "She sat quietly beside the river."
        block = build_action_constraints_block(narration)
        assert block == ""

    def test_action_constraint_to_prompt_block(self):
        c = ActionConstraint(action="pours oil", obj="lamp",
                             constraint="Do X correctly.", bad_example="wrong way")
        block = c.to_prompt_block()
        assert "ACTION CONSTRAINT" in block
        assert "Do X correctly." in block
        assert "BAD:" in block


# ===========================================================================
# 14. StoryState.get_story_context_for_scene
# ===========================================================================

class TestStoryContextForScene:
    def test_dead_character_listed_in_context(self):
        from ytfactory.scene_continuity.models import SceneState
        state = StoryState()
        cid = "traveler"
        char = CharacterState(name="Traveler", canonical_id=cid, alive=False, scene_last_seen=3)
        state.characters[cid] = char
        state.scene_modes[3] = SceneMode.LITERAL
        state.scene_modes[5] = SceneMode.LITERAL
        state.scene_history[3] = SceneState(
            scene_id=3, mode=SceneMode.LITERAL,
            character_states={cid: char}, prop_states={},
        )
        ctx = state.get_story_context_for_scene(5)
        assert "DEAD CHARACTERS" in ctx
        assert "Traveler" in ctx

    def test_symbolic_scene_gets_symbolic_header(self):
        from ytfactory.scene_continuity.models import SceneState
        state = StoryState()
        cid = "traveler"
        char = CharacterState(name="Traveler", canonical_id=cid, alive=False)
        state.characters[cid] = char
        state.scene_modes[5] = SceneMode.SYMBOLIC
        state.scene_history[3] = SceneState(
            scene_id=3, mode=SceneMode.LITERAL,
            character_states={cid: char}, prop_states={},
        )
        ctx = state.get_story_context_for_scene(5)
        # Dead character NOT listed for symbolic scenes; header says SYMBOLIC
        assert "SCENE MODE: SYMBOLIC" in ctx
        assert "DEAD CHARACTERS" not in ctx

    def test_known_prop_state_in_context(self):
        from ytfactory.scene_continuity.models import SceneState
        state = StoryState()
        prop = PropState(name="oil lamp", canonical_id="oil_lamp",
                         current_state="unlit", scene_last_modified=2)
        state.props["oil_lamp"] = prop
        state.scene_modes[5] = SceneMode.LITERAL
        state.scene_history[3] = SceneState(
            scene_id=3, mode=SceneMode.LITERAL,
            character_states={}, prop_states={"oil_lamp": prop},
        )
        ctx = state.get_story_context_for_scene(5)
        assert "oil lamp" in ctx
        assert "unlit" in ctx

    def test_empty_context_when_nothing_to_report(self):
        state = StoryState()
        ctx = state.get_story_context_for_scene(0)
        assert ctx == ""
