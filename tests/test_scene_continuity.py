"""Tests for scene_continuity — StoryStateTracker, ContinuityValidator, ActionConstraint.

Covers all 14 problem classes from the image prompt pipeline audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


# ===========================================================================
# 15. Regression tests for five localized continuity fixes
# ===========================================================================

class TestContinuityRegressions:
    """Regression tests for bugs found in the-story-of-a-strange-mind audit."""

    # ── Fix 4: extended extinguish / oil-exhaustion patterns ─────────────────

    def test_lamp_went_out_detected(self):
        """'went out' must be detected as extinguishing the lamp."""
        result = _extract_prop_state_from_narration(
            "Then the lamp went out. The light vanished."
        )
        assert result.get("oil_lamp") == "unlit"

    def test_oil_was_gone_detected(self):
        """'oil was gone' must mark the lamp as empty (from the-story-of-a-strange-mind scene 14)."""
        result = _extract_prop_state_from_narration(
            "Then the lamp went out. The oil was gone. The light vanished."
        )
        assert result.get("oil_lamp") in {"unlit", "empty"}

    def test_oil_had_run_out_detected(self):
        """'oil had run out' must mark the lamp as empty."""
        result = _extract_prop_state_from_narration(
            "He realized the oil had run out. Darkness fell."
        )
        assert result.get("oil_lamp") == "empty"

    # ── Fix 5: extended death patterns ───────────────────────────────────────

    def test_traveler_lost_his_life_detected(self):
        """'lost his life' must be detected as death (from the-story-of-a-strange-mind scene 16)."""
        result = _infer_death_from_narration("the traveler lost his life in the darkness")
        assert len(result) > 0
        assert any("traveler" in r for r in result)

    def test_was_slain_detected(self):
        result = _infer_death_from_narration("The hero was slain by the dragon.")
        assert any("hero" in r for r in result)

    def test_was_killed_detected(self):
        result = _infer_death_from_narration("The guard was killed at the gate.")
        assert any("guard" in r for r in result)

    def test_was_murdered_detected(self):
        result = _infer_death_from_narration("The merchant was murdered for his gold.")
        assert any("merchant" in r for r in result)

    def test_met_his_end_detected(self):
        result = _infer_death_from_narration("The traveler met his end there.")
        assert any("traveler" in r for r in result)

    def test_met_her_death_detected(self):
        result = _infer_death_from_narration("The princess met her death at dawn.")
        assert any("princess" in r for r in result)

    # ── Fix 2+3: scene_analysis_map key alignment (1-based production dicts) ─

    def test_build_story_state_with_1based_dict_scenes(self):
        """Production scene dicts with 1-based 'index' must align with 1-based analysis_map."""
        scenes = [
            {"index": 1, "narration": "Traveler begins.", "visual_metadata": {"narrative_role": "STORY"}},
            {"index": 2, "narration": "Traveler walks on.", "visual_metadata": {"narrative_role": "STORY"}},
        ]
        analysis_map = {
            1: FakeSceneAnalysis(allowed_characters=["Traveler"]),
            2: FakeSceneAnalysis(allowed_characters=["Traveler"]),
        }
        state = build_story_state(scenes, analysis_map)
        assert "traveler" in state.characters
        # History must be keyed 1-based (matching scene["index"])
        assert 1 in state.scene_history
        assert 2 in state.scene_history

    def test_scene_mode_belongs_to_correct_scene(self):
        """METAPHOR scene must receive SYMBOLIC mode, not the next scene's LITERAL mode."""
        scenes = [
            {
                "index": 26,
                "narration": "A river of memories flows.",
                "visual_metadata": {"narrative_role": "METAPHOR"},
            },
            {
                "index": 27,
                "narration": "He sits quietly.",
                "visual_metadata": {"narrative_role": "STORY"},
            },
        ]
        analysis_map = {
            26: FakeSceneAnalysis(allowed_characters=[]),
            27: FakeSceneAnalysis(allowed_characters=[]),
        }
        state = build_story_state(scenes, analysis_map)
        assert state.scene_modes.get(26) == SceneMode.SYMBOLIC
        assert state.scene_modes.get(27) == SceneMode.LITERAL

    # ── Fix 1: scene-14→15 and scene-16→17 state propagation ────────────────

    def test_scene_14_to_15_state_transition(self):
        """After 'lamp went out / oil was gone', scene 15's context must show lamp unlit/empty."""
        scenes = [
            {
                "index": 13,
                "narration": "He lights the oil lamp carefully.",
                "visual_metadata": {"narrative_role": "STORY"},
            },
            {
                "index": 14,
                "narration": "Then the lamp went out. The oil was gone. The light vanished.",
                "visual_metadata": {"narrative_role": "STORY"},
            },
            {
                "index": 15,
                "narration": "Darkness surrounds him.",
                "visual_metadata": {"narrative_role": "STORY"},
            },
        ]
        analysis_map = {
            13: FakeSceneAnalysis(allowed_characters=[], scene_objects=["oil lamp"]),
            14: FakeSceneAnalysis(allowed_characters=[], scene_objects=["oil lamp"]),
            15: FakeSceneAnalysis(allowed_characters=[]),
        }
        state = build_story_state(scenes, analysis_map)
        # After scene 14, oil_lamp must be unlit or empty
        snap = state.scene_history.get(14)
        assert snap is not None
        lamp = snap.prop_states.get("oil_lamp")
        assert lamp is not None
        assert lamp.current_state in {"unlit", "empty"}
        # Scene 15 context (state before scene 15 = after scene 14) must show lamp as
        # unlit or empty — it must NOT claim the lamp is currently "lit"
        ctx = state.get_story_context_for_scene(15)
        ctx_lower = ctx.lower()
        assert "currently lit" not in ctx_lower

    def test_scene_16_to_17_traveler_dead(self):
        """After 'traveler lost his life', scene 17 context must show traveler dead."""
        scenes = [
            {
                "index": 15,
                "narration": "The traveler walks on.",
                "visual_metadata": {"narrative_role": "STORY"},
            },
            {
                "index": 16,
                "narration": "the traveler lost his life in the darkness",
                "visual_metadata": {"narrative_role": "STORY"},
            },
            {
                "index": 17,
                "narration": "Silence.",
                "visual_metadata": {"narrative_role": "STORY"},
            },
        ]
        analysis_map = {
            15: FakeSceneAnalysis(allowed_characters=["Traveler"]),
            16: FakeSceneAnalysis(allowed_characters=[]),
            17: FakeSceneAnalysis(allowed_characters=[]),
        }
        state = build_story_state(scenes, analysis_map)
        assert "traveler" in state.characters
        assert state.characters["traveler"].alive is False
        ctx = state.get_story_context_for_scene(17)
        assert "DEAD CHARACTERS" in ctx
        assert "Traveler" in ctx

    # ── Fix 3: SYMBOLIC mode context for scene 27→28 ─────────────────────────

    def test_symbolic_scene_gets_symbolic_context(self):
        """A METAPHOR scene must get SYMBOLIC context even when traveler died earlier."""
        scenes = [
            {
                "index": 16,
                "narration": "the traveler lost his life",
                "visual_metadata": {"narrative_role": "STORY"},
            },
            {
                "index": 26,
                "narration": "The spirit of the traveler drifts over the mountains.",
                "visual_metadata": {"narrative_role": "METAPHOR"},
            },
        ]
        analysis_map = {
            16: FakeSceneAnalysis(allowed_characters=["Traveler"]),
            26: FakeSceneAnalysis(allowed_characters=[]),
        }
        state = build_story_state(scenes, analysis_map)
        # Scene 26 is METAPHOR → SYMBOLIC mode
        ctx = state.get_story_context_for_scene(26)
        assert "SCENE MODE: SYMBOLIC" in ctx
        # SYMBOLIC context must NOT list dead characters (they're allowed symbolically)
        assert "DEAD CHARACTERS" not in ctx


# ===========================================================================
# 16. Normalization — time
# ===========================================================================

class TestTimeNormalization:
    def test_dawn_to_sunrise(self):
        from ytfactory.scene_continuity.normalization import normalize_time
        assert normalize_time("dawn") == "SUNRISE"

    def test_midday_noon(self):
        from ytfactory.scene_continuity.normalization import normalize_time
        assert normalize_time("noon") == "MIDDAY"

    def test_deep_night_midnight(self):
        from ytfactory.scene_continuity.normalization import normalize_time
        assert normalize_time("midnight") == "DEEP_NIGHT"

    def test_time_progression_forward_allowed(self):
        from ytfactory.scene_continuity.normalization import time_progression_allowed
        ok, _ = time_progression_allowed("MORNING", "MIDDAY")
        assert ok is True

    def test_time_reversal_blocked_without_jump(self):
        from ytfactory.scene_continuity.normalization import time_progression_allowed
        ok, reason = time_progression_allowed("DEEP_NIGHT", "SUNSET")
        assert ok is False
        assert "reversed" in reason.lower()

    def test_time_reversal_allowed_with_jump_narration(self):
        from ytfactory.scene_continuity.normalization import time_progression_allowed
        ok, _ = time_progression_allowed("DEEP_NIGHT", "SUNSET", "The sun rose the next morning.")
        assert ok is True

    def test_detect_time_jump(self):
        from ytfactory.scene_continuity.normalization import detect_time_jump
        assert detect_time_jump("The next morning, he woke early.") is True
        assert detect_time_jump("He sat in silence.") is False


# ===========================================================================
# 17. Normalization — location
# ===========================================================================

class TestLocationNormalization:
    def test_forest_path_normalized(self):
        from ytfactory.scene_continuity.normalization import normalize_location
        assert normalize_location("Forest Path") == "forest_path"

    def test_forest_clearing_normalized(self):
        from ytfactory.scene_continuity.normalization import normalize_location
        assert normalize_location("forest clearing") == "forest_clearing"

    def test_unknown_location_slugified(self):
        from ytfactory.scene_continuity.normalization import normalize_location
        assert normalize_location("A New Place!") == "a_new_place"


# ===========================================================================
# 18. Normalization — entity / state
# ===========================================================================

class TestEntityAndStateNormalization:
    def test_traveler_alias(self):
        from ytfactory.scene_continuity.normalization import canonical_entity_id
        assert canonical_entity_id("the traveler") == "traveler"

    def test_old_sage_alias(self):
        from ytfactory.scene_continuity.normalization import canonical_entity_id
        assert canonical_entity_id("Old Sage") == "old_sage"

    def test_state_lit_normalized(self):
        from ytfactory.scene_continuity.normalization import normalize_state
        assert normalize_state("glowing") == "lit"

    def test_state_empty_normalized(self):
        from ytfactory.scene_continuity.normalization import normalize_state
        assert normalize_state("depleted") == "empty"

    def test_terminal_destroyed(self):
        from ytfactory.scene_continuity.normalization import is_terminal_state
        assert is_terminal_state("destroyed") is True

    def test_terminal_lit(self):
        from ytfactory.scene_continuity.normalization import is_terminal_state
        assert is_terminal_state("lit") is False


# ===========================================================================
# 19. Normalization — transfer detection
# ===========================================================================

class TestTransferDetection:
    def test_gives_detected(self):
        from ytfactory.scene_continuity.normalization import detect_transfer_language
        assert detect_transfer_language("The mentor gives the lamp to the traveler.") is True

    def test_no_transfer(self):
        from ytfactory.scene_continuity.normalization import detect_transfer_language
        assert detect_transfer_language("The traveler walks alone.") is False

    def test_extract_transfer_target(self):
        from ytfactory.scene_continuity.normalization import extract_transfer_target
        result = extract_transfer_target("The mentor gives the lamp to the traveler.", "lamp")
        assert result == "traveler"


# ===========================================================================
# 20. ObjectStateTransitionRule
# ===========================================================================

class TestObjectStateTransitionRule:
    def test_allowed_transition_passes(self):
        from ytfactory.scene_continuity.transitions import ObjectStateTransitionRule
        rule = ObjectStateTransitionRule(
            object_type="light",
            allowed_transitions=[("unlit", "lit"), ("lit", "unlit")],
        )
        ok, _ = rule.can_transition("unlit", "lit")
        assert ok is True

    def test_disallowed_transition_fails(self):
        from ytfactory.scene_continuity.transitions import ObjectStateTransitionRule
        rule = ObjectStateTransitionRule(
            object_type="light",
            allowed_transitions=[("unlit", "lit")],
        )
        ok, reason = rule.can_transition("lit", "destroyed")
        assert ok is False

    def test_terminal_state_blocks(self):
        from ytfactory.scene_continuity.transitions import ObjectStateTransitionRule
        rule = ObjectStateTransitionRule(
            object_type="light",
            terminal_states=["destroyed"],
        )
        ok, reason = rule.can_transition("destroyed", "lit")
        assert ok is False
        assert "terminal" in reason.lower()

    def test_default_container_rule(self):
        from ytfactory.scene_continuity.transitions import get_default_rule
        rule = get_default_rule("container")
        assert rule.object_type == "container"
        ok, _ = rule.can_transition("empty", "full")
        assert ok is True


# ===========================================================================
# 21. validate_scene_transition — death guard
# ===========================================================================

class TestDeathGuard:
    def _make_dead_state(self, char_name: str, died_scene: int) -> StoryState:
        from ytfactory.scene_continuity.models import CharacterState, SceneState, SceneMode
        state = StoryState()
        cid = char_name.lower().replace(" ", "_")
        char = CharacterState(
            name=char_name, canonical_id=cid, alive=False, scene_last_seen=died_scene
        )
        state.characters[cid] = char
        state.scene_modes[died_scene] = SceneMode.LITERAL
        state.scene_history[died_scene] = SceneState(
            scene_id=died_scene,
            mode=SceneMode.LITERAL,
            character_states={cid: char},
            prop_states={},
        )
        return state

    def test_dead_resurrected_is_critical(self):
        from ytfactory.scene_continuity.transitions import validate_scene_transition
        from ytfactory.scene_continuity.models import SceneMode, SceneState, CharacterState
        prev = self._make_dead_state("Traveler", 5)
        proposed = StoryState()
        cid = "traveler"
        proposed.characters[cid] = CharacterState(
            name="Traveler", canonical_id=cid, alive=True, scene_last_seen=10
        )
        proposed.scene_modes[10] = SceneMode.LITERAL
        proposed.scene_history[10] = SceneState(
            scene_id=10,
            mode=SceneMode.LITERAL,
            character_states={cid: proposed.characters[cid]},
            prop_states={},
        )
        violations = validate_scene_transition(
            prev, proposed, 10, SceneMode.LITERAL, "The traveler walks again."
        )
        codes = [v.code for v in violations]
        assert "CONT_DEATH_002" in codes
        assert any(v.severity == ValidationLevel.CRITICAL for v in violations)

    def test_dead_stays_dead_no_violation(self):
        from ytfactory.scene_continuity.transitions import validate_scene_transition
        from ytfactory.scene_continuity.models import SceneMode, SceneState, CharacterState
        prev = self._make_dead_state("Traveler", 5)
        proposed = StoryState()
        cid = "traveler"
        proposed.characters[cid] = CharacterState(
            name="Traveler", canonical_id=cid, alive=False, scene_last_seen=10
        )
        proposed.scene_modes[10] = SceneMode.LITERAL
        proposed.scene_history[10] = SceneState(
            scene_id=10,
            mode=SceneMode.LITERAL,
            character_states={cid: proposed.characters[cid]},
            prop_states={},
        )
        violations = validate_scene_transition(
            prev, proposed, 10, SceneMode.LITERAL, "The body lies still."
        )
        death_violations = [v for v in violations if v.category == "CHARACTER_RESURRECTION"]
        assert death_violations == []


# ===========================================================================
# 22. validate_scene_transition — ownership guard
# ===========================================================================

class TestOwnershipGuard:
    def test_spontaneous_ownership_is_error(self):
        from ytfactory.scene_continuity.transitions import validate_scene_transition
        from ytfactory.scene_continuity.models import SceneMode, SceneState, PropState, CharacterState
        prev = StoryState()
        prev.scene_modes[1] = SceneMode.LITERAL
        prev.scene_history[1] = SceneState(
            scene_id=1, mode=SceneMode.LITERAL, character_states={}, prop_states={}
        )
        proposed = StoryState()
        prop = PropState(name="lamp", canonical_id="lamp", owner="traveler")
        proposed.props["lamp"] = prop
        char = CharacterState(name="Traveler", canonical_id="traveler")
        proposed.characters["traveler"] = char
        proposed.scene_modes[2] = SceneMode.LITERAL
        proposed.scene_history[2] = SceneState(
            scene_id=2, mode=SceneMode.LITERAL,
            character_states={"traveler": char}, prop_states={"lamp": prop}
        )
        violations = validate_scene_transition(
            prev, proposed, 2, SceneMode.LITERAL, "The traveler holds the lamp."
        )
        codes = [v.code for v in violations]
        assert "CONT_OWN_001" in codes

    def test_explicit_transfer_allowed(self):
        from ytfactory.scene_continuity.transitions import validate_scene_transition
        from ytfactory.scene_continuity.models import SceneMode, SceneState, PropState, CharacterState
        prev = StoryState()
        prev.scene_modes[1] = SceneMode.LITERAL
        prev.scene_history[1] = SceneState(
            scene_id=1, mode=SceneMode.LITERAL, character_states={}, prop_states={}
        )
        proposed = StoryState()
        prop = PropState(name="lamp", canonical_id="lamp", owner="traveler")
        proposed.props["lamp"] = prop
        char = CharacterState(name="Traveler", canonical_id="traveler")
        proposed.characters["traveler"] = char
        proposed.scene_modes[2] = SceneMode.LITERAL
        proposed.scene_history[2] = SceneState(
            scene_id=2, mode=SceneMode.LITERAL,
            character_states={"traveler": char}, prop_states={"lamp": prop}
        )
        violations = validate_scene_transition(
            prev, proposed, 2, SceneMode.LITERAL,
            "The mentor gives the lamp to the traveler.",
        )
        own_violations = [v for v in violations if v.category == "OBJECT_OWNERSHIP"]
        assert own_violations == []


# ===========================================================================
# 23. validate_scene_transition — monotonic object states
# ===========================================================================

class TestMonotonicObjectStates:
    def test_terminal_state_blocks_reversion(self):
        from ytfactory.scene_continuity.transitions import validate_scene_transition, ObjectStateTransitionRule
        from ytfactory.scene_continuity.models import (
            SceneMode, SceneState, PropState
        )
        prev = StoryState()
        prev.scene_modes[1] = SceneMode.LITERAL
        lamp = PropState(name="lamp", canonical_id="lamp", current_state="destroyed")
        prev.props["lamp"] = lamp
        prev.scene_history[1] = SceneState(
            scene_id=1, mode=SceneMode.LITERAL, character_states={}, prop_states={"lamp": lamp}
        )
        proposed = StoryState()
        lamp2 = PropState(name="lamp", canonical_id="lamp", current_state="lit")
        proposed.props["lamp"] = lamp2
        proposed.scene_modes[2] = SceneMode.LITERAL
        proposed.scene_history[2] = SceneState(
            scene_id=2, mode=SceneMode.LITERAL,
            character_states={}, prop_states={"lamp": lamp2}
        )
        # Inject a specific rule with terminal states for this test
        import ytfactory.scene_continuity.transitions as _t
        _original = _t._DEFAULT_RULES.get("lamp")
        _t._DEFAULT_RULES["lamp"] = ObjectStateTransitionRule(
            object_type="lamp",
            terminal_states=["destroyed", "lost"],
        )
        try:
            violations = validate_scene_transition(
                prev, proposed, 2, SceneMode.LITERAL, "The lamp glows brightly."
            )
        finally:
            if _original is not None:
                _t._DEFAULT_RULES["lamp"] = _original
            else:
                _t._DEFAULT_RULES.pop("lamp", None)
        prop_violations = [v for v in violations if v.category == "PROP_STATE_MONOTONICITY"]
        assert len(prop_violations) >= 1


# ===========================================================================
# 24. validate_scene_transition — temporal continuity
# ===========================================================================

class TestTemporalContinuity:
    def test_forward_time_allowed(self):
        from ytfactory.scene_continuity.transitions import validate_scene_transition
        from ytfactory.scene_continuity.models import (
            SceneMode, SceneState
        )
        prev = StoryState()
        prev.scene_modes[1] = SceneMode.LITERAL
        prev.scene_history[1] = SceneState(
            scene_id=1, mode=SceneMode.LITERAL,
            character_states={}, prop_states={}, time_of_day="MORNING"
        )
        proposed = StoryState()
        proposed.scene_modes[2] = SceneMode.LITERAL
        proposed.scene_history[2] = SceneState(
            scene_id=2, mode=SceneMode.LITERAL,
            character_states={}, prop_states={}, time_of_day="AFTERNOON"
        )
        violations = validate_scene_transition(
            prev, proposed, 2, SceneMode.LITERAL, "The day wears on."
        )
        temporal_violations = [v for v in violations if v.category == "TEMPORAL_CONTINUITY"]
        assert temporal_violations == []

    def test_night_to_sunset_blocked(self):
        from ytfactory.scene_continuity.transitions import validate_scene_transition
        from ytfactory.scene_continuity.models import (
            SceneMode, SceneState
        )
        prev = StoryState()
        prev.scene_modes[1] = SceneMode.LITERAL
        prev.scene_history[1] = SceneState(
            scene_id=1, mode=SceneMode.LITERAL,
            character_states={}, prop_states={}, time_of_day="DEEP_NIGHT"
        )
        proposed = StoryState()
        proposed.scene_modes[2] = SceneMode.LITERAL
        proposed.scene_history[2] = SceneState(
            scene_id=2, mode=SceneMode.LITERAL,
            character_states={}, prop_states={}, time_of_day="SUNSET"
        )
        violations = validate_scene_transition(
            prev, proposed, 2, SceneMode.LITERAL, "The sun sets."
        )
        temporal_violations = [v for v in violations if v.category == "TEMPORAL_CONTINUITY"]
        assert len(temporal_violations) >= 1


# ===========================================================================
# 25. validate_scene_transition — location continuity
# ===========================================================================

class TestLocationContinuity:
    def test_same_location_no_violation(self):
        from ytfactory.scene_continuity.transitions import validate_scene_transition
        from ytfactory.scene_continuity.models import (
            SceneMode, SceneState, LocationState
        )
        prev = StoryState()
        prev.scene_modes[1] = SceneMode.LITERAL
        prev.scene_history[1] = SceneState(
            scene_id=1, mode=SceneMode.LITERAL,
            character_states={}, prop_states={},
            location=LocationState(location_id="forest_path")
        )
        proposed = StoryState()
        proposed.scene_modes[2] = SceneMode.LITERAL
        proposed.scene_history[2] = SceneState(
            scene_id=2, mode=SceneMode.LITERAL,
            character_states={}, prop_states={},
            location=LocationState(location_id="forest_path")
        )
        violations = validate_scene_transition(
            prev, proposed, 2, SceneMode.LITERAL, "He continues walking."
        )
        loc_violations = [v for v in violations if v.category == "LOCATION_CONTINUITY"]
        assert loc_violations == []

    def test_unexplained_teleport_warns(self):
        from ytfactory.scene_continuity.transitions import validate_scene_transition
        from ytfactory.scene_continuity.models import (
            SceneMode, SceneState, LocationState
        )
        prev = StoryState()
        prev.scene_modes[1] = SceneMode.LITERAL
        prev.scene_history[1] = SceneState(
            scene_id=1, mode=SceneMode.LITERAL,
            character_states={}, prop_states={},
            location=LocationState(location_id="forest_clearing")
        )
        proposed = StoryState()
        proposed.scene_modes[2] = SceneMode.LITERAL
        proposed.scene_history[2] = SceneState(
            scene_id=2, mode=SceneMode.LITERAL,
            character_states={}, prop_states={},
            location=LocationState(location_id="city_palace")
        )
        violations = validate_scene_transition(
            prev, proposed, 2, SceneMode.LITERAL, "He is in the palace."
        )
        loc_violations = [v for v in violations if v.category == "LOCATION_CONTINUITY"]
        assert len(loc_violations) >= 1


# ===========================================================================
# 26. Symbolic scene isolation
# ===========================================================================

class TestSymbolicIsolation:
    def test_symbolic_state_does_not_mutate_literal(self):
        """Symbolic scene state changes must not affect the canonical literal state."""
        tracker = StoryStateTracker()
        tracker.process_scene(
            0, "The traveler begins.", FakeSceneAnalysis(allowed_characters=["Traveler"])
        )
        # Symbolic scene — should not update character state
        tracker.process_scene(
            1, "The old world dies.", None, narrative_role="METAPHOR"
        )
        assert "traveler" in tracker.story_state.characters
        assert tracker.story_state.characters["traveler"].alive is True

    def test_symbolic_mode_stored_in_snapshot(self):
        tracker = StoryStateTracker()
        tracker.process_scene(
            0, "The traveler begins.", FakeSceneAnalysis(allowed_characters=["Traveler"])
        )
        tracker.process_scene(
            1, "The old world dies.", None, narrative_role="METAPHOR"
        )
        snap = tracker.story_state.scene_history.get(1)
        assert snap is not None
        assert snap.mode == SceneMode.SYMBOLIC


# ===========================================================================
# 27. Lighting continuity via derive_lighting
# ===========================================================================

class TestLightingContinuity:
    def test_sunrise_lighting(self):
        from ytfactory.scene_continuity.normalization import derive_lighting
        result = derive_lighting("SUNRISE")
        assert "sunrise" in result.lower()

    def test_lamp_added_to_night(self):
        from ytfactory.scene_continuity.normalization import derive_lighting
        result = derive_lighting("NIGHT", ["oil lamp"])
        assert "lamp" in result.lower() or "oil" in result.lower()
        assert "night" in result.lower()


# ===========================================================================
# 28. Golden regression test (generic fixture based on reference prompt audit)
# ===========================================================================

class TestGoldenRegression:
    """Regression fixture for the canonical continuity engine.

    Tests the key failure modes found in the reference-prompt audit:
    - object not owned before transfer
    - explicit transfer establishes ownership
    - nighttime progression
    - repeated counting
    - object burial (terminal state)
    - character death
    - symbolic reconstruction
    - symbolic state isolation
    - later literal scene retains canonical state
    - canonical clothing does not drift
    """

    def _build_full_scenario(self) -> tuple[list[dict], dict[int, Any]]:
        scenes = [
            {
                "index": 1,
                "narration": "The traveler walks the forest path at dawn.",
                "visual_metadata": {"narrative_role": "STORY"},
                "scene_state": {
                    "time_of_day": "SUNRISE",
                    "location": {"canonical_name": "forest path", "location_id": "forest_path"},
                },
            },
            {
                "index": 2,
                "narration": "He finds an old oil lamp half-buried in the leaves.",
                "visual_metadata": {"narrative_role": "STORY"},
                "scene_state": {
                    "time_of_day": "MORNING",
                    "location": {"canonical_name": "forest path", "location_id": "forest_path"},
                },
            },
            {
                "index": 3,
                "narration": "He picks up the lamp. It is unlit.",
                "visual_metadata": {"narrative_role": "STORY"},
                "scene_state": {
                    "time_of_day": "MORNING",
                    "location": {"canonical_name": "forest path", "location_id": "forest_path"},
                },
            },
            {
                "index": 4,
                "narration": "The mentor gives the lamp to the traveler. Now he carries two.",
                "visual_metadata": {"narrative_role": "STORY"},
                "scene_state": {
                    "time_of_day": "AFTERNOON",
                    "location": {"canonical_name": "forest path", "location_id": "forest_path"},
                },
            },
            {
                "index": 5,
                "narration": "He counts: one, two, three lamps in the darkness.",
                "visual_metadata": {"narrative_role": "STORY"},
                "scene_state": {
                    "time_of_day": "DEEP_NIGHT",
                    "location": {"canonical_name": "forest clearing", "location_id": "forest_clearing"},
                },
            },
            {
                "index": 6,
                "narration": "He buries the lamps in the earth. They are gone forever.",
                "visual_metadata": {"narrative_role": "STORY"},
                "scene_state": {
                    "time_of_day": "DEEP_NIGHT",
                    "location": {"canonical_name": "forest clearing", "location_id": "forest_clearing"},
                },
            },
            {
                "index": 7,
                "narration": "The traveler's life ended there in the darkness.",
                "visual_metadata": {"narrative_role": "STORY"},
                "scene_state": {
                    "time_of_day": "DEEP_NIGHT",
                    "location": {"canonical_name": "forest clearing", "location_id": "forest_clearing"},
                },
            },
            {
                "index": 8,
                "narration": "A symbolic reconstruction: the traveler stands again with lamps lit.",
                "visual_metadata": {"narrative_role": "METAPHOR"},
                "scene_state": {
                    "temporal_mode": "SYMBOLIC_RECONSTRUCTION",
                },
            },
            {
                "index": 9,
                "narration": "The earth is still. The lamps remain buried.",
                "visual_metadata": {"narrative_role": "STORY"},
                "scene_state": {
                    "time_of_day": "DEEP_NIGHT",
                    "location": {"canonical_name": "forest clearing", "location_id": "forest_clearing"},
                },
            },
        ]
        analysis_map = {
            1: FakeSceneAnalysis(allowed_characters=["Traveler"], scene_objects=["oil lamp"]),
            2: FakeSceneAnalysis(allowed_characters=["Traveler"], scene_objects=["oil lamp"]),
            3: FakeSceneAnalysis(allowed_characters=["Traveler"], scene_objects=["oil lamp"]),
            4: FakeSceneAnalysis(allowed_characters=["Traveler", "Mentor"], scene_objects=["oil lamp"]),
            5: FakeSceneAnalysis(allowed_characters=["Traveler"], scene_objects=["oil lamp"]),
            6: FakeSceneAnalysis(allowed_characters=["Traveler"], scene_objects=["oil lamp"]),
            7: FakeSceneAnalysis(allowed_characters=[], scene_objects=["oil lamp"]),
            8: FakeSceneAnalysis(allowed_characters=["Traveler"], scene_objects=["oil lamp"]),
            9: FakeSceneAnalysis(allowed_characters=[], scene_objects=["oil lamp"]),
        }
        return scenes, analysis_map

    def test_object_not_owned_before_transfer(self):
        scenes, analysis_map = self._build_full_scenario()
        state = build_story_state(scenes[:3], {k: v for k, v in analysis_map.items() if k <= 3})
        prev_chars, prev_props = state.get_state_before_scene(3)
        lamp = prev_props.get("oil_lamp")
        assert lamp is not None
        assert lamp.owner == ""  # not owned before explicit transfer

    def test_explicit_transfer_establishes_ownership(self):
        scenes, analysis_map = self._build_full_scenario()
        state = build_story_state(scenes[:4], {k: v for k, v in analysis_map.items() if k <= 4})
        # After scene 4 (the transfer), the lamp should be owned by traveler
        chars_after, props_after = state.get_state_after_scene(4)
        lamp = props_after.get("oil_lamp")
        assert lamp is not None
        assert lamp.owner == "traveler"

    def test_nighttime_progression(self):
        scenes, analysis_map = self._build_full_scenario()
        state = build_story_state(scenes[:5], {k: v for k, v in analysis_map.items() if k <= 5})
        snap = state.scene_history.get(5)
        assert snap is not None
        assert snap.time_of_day == "DEEP_NIGHT"

    def test_burial_is_terminal_state(self):
        from ytfactory.scene_continuity.normalization import normalize_state, is_terminal_state
        assert normalize_state("buried") == "buried"
        assert is_terminal_state("buried") is True

    def test_character_death_is_terminal(self):
        scenes, analysis_map = self._build_full_scenario()
        state = build_story_state(scenes[:7], {k: v for k, v in analysis_map.items() if k <= 7})
        assert "traveler" in state.characters
        assert state.characters["traveler"].alive is False

    def test_symbolic_scene_does_not_resurrect(self):
        scenes, analysis_map = self._build_full_scenario()
        state = build_story_state(scenes[:8], {k: v for k, v in analysis_map.items() if k <= 8})
        assert "traveler" in state.characters
        assert state.characters["traveler"].alive is False

    def test_literal_after_symbolic_retains_canonical_state(self):
        scenes, analysis_map = self._build_full_scenario()
        state = build_story_state(scenes, analysis_map)
        assert "traveler" in state.characters
        assert state.characters["traveler"].alive is False
        snap = state.scene_history.get(9)
        assert snap is not None
        assert snap.time_of_day == "DEEP_NIGHT"

    def test_transition_validator_detects_death(self):
        from ytfactory.scene_continuity.transitions import validate_scene_transition
        from ytfactory.scene_continuity.models import (
            SceneMode, SceneState, CharacterState
        )
        scenes, analysis_map = self._build_full_scenario()
        state_before = build_story_state(scenes[:6], {k: v for k, v in analysis_map.items() if k <= 6})
        # Build proposed state with traveler dead
        proposed = StoryState()
        cid = "traveler"
        proposed.characters[cid] = CharacterState(
            name="Traveler", canonical_id=cid, alive=False, scene_last_seen=7
        )
        proposed.scene_modes[7] = SceneMode.LITERAL
        proposed.scene_history[7] = SceneState(
            scene_id=7, mode=SceneMode.LITERAL,
            character_states={cid: proposed.characters[cid]}, prop_states={}
        )
        violations = validate_scene_transition(
            state_before, proposed, 7, SceneMode.LITERAL,
            "The traveler's life ended there in the darkness."
        )
        death_violations = [v for v in violations if v.category == "CHARACTER_DEATH"]
        assert len(death_violations) >= 1

    def test_symbolic_scene_isolated_from_literal(self):
        from ytfactory.scene_continuity.transitions import validate_scene_transition
        from ytfactory.scene_continuity.models import (
            SceneMode, SceneState, CharacterState, TemporalMode
        )
        scenes, analysis_map = self._build_full_scenario()
        state_before = build_story_state(scenes[:7], {k: v for k, v in analysis_map.items() if k <= 7})
        # Symbolic scene 8: traveler alive in symbolic, but canonical state stays dead
        proposed = StoryState()
        cid = "traveler"
        proposed.characters[cid] = CharacterState(
            name="Traveler", canonical_id=cid, alive=True, scene_last_seen=8
        )
        proposed.scene_modes[8] = SceneMode.SYMBOLIC
        proposed.scene_history[8] = SceneState(
            scene_id=8, mode=SceneMode.SYMBOLIC,
            temporal_mode=TemporalMode.SYMBOLIC_RECONSTRUCTION,
            character_states={cid: proposed.characters[cid]}, prop_states={}
        )
        violations = validate_scene_transition(
            state_before, proposed, 8, SceneMode.SYMBOLIC,
            "The traveler stands again.",
        )
        resurrections = [v for v in violations if v.category == "CHARACTER_RESURRECTION"]
        assert resurrections == []


# ===========================================================================
# 29. Prompt validator
# ===========================================================================

class TestPromptValidator:
    def _state_with_dead_traveler(self) -> StoryState:
        from ytfactory.scene_continuity.models import (
            CharacterState, SceneMode, SceneState
        )
        state = StoryState()
        cid = "traveler"
        char = CharacterState(name="Traveler", canonical_id=cid, alive=False)
        state.characters[cid] = char
        state.scene_modes[5] = SceneMode.LITERAL
        state.scene_history[5] = SceneState(
            scene_id=5, mode=SceneMode.LITERAL,
            character_states={cid: char}, prop_states={}
        )
        return state

    def test_dead_character_alive_in_prompt_is_critical(self):
        from ytfactory.scene_continuity.prompt_validator import validate_prompt_against_state
        from ytfactory.scene_continuity.models import SceneMode
        state = self._state_with_dead_traveler()
        prompt = "The Traveler walks calmly through the forest."
        findings = validate_prompt_against_state(
            prompt, state, 6, SceneMode.LITERAL
        )
        crit = [f for f in findings if f.level == ValidationLevel.CRITICAL]
        assert len(crit) >= 1
        assert any("Traveler" in f.message for f in crit)

    def test_dead_character_symbolic_is_allowed(self):
        from ytfactory.scene_continuity.prompt_validator import validate_prompt_against_state
        from ytfactory.scene_continuity.models import SceneMode
        state = self._state_with_dead_traveler()
        prompt = "A ghostly figure of the Traveler drifts over the mountains."
        findings = validate_prompt_against_state(
            prompt, state, 7, SceneMode.SYMBOLIC
        )
        crit = [f for f in findings if f.level == ValidationLevel.CRITICAL]
        assert crit == []

    def test_absent_character_body_part_is_error(self):
        from ytfactory.scene_continuity.prompt_validator import validate_prompt_against_state
        from ytfactory.scene_continuity.models import (
            CharacterState, SceneMode, SceneState
        )
        state = StoryState()
        cid = "traveler"
        char = CharacterState(
            name="Traveler", canonical_id=cid, alive=True, present_in_story=False
        )
        state.characters[cid] = char
        state.scene_modes[3] = SceneMode.LITERAL
        state.scene_history[3] = SceneState(
            scene_id=3, mode=SceneMode.LITERAL,
            character_states={cid: char}, prop_states={}
        )
        prompt = "The traveler's hand reaches out from the shadows."
        findings = validate_prompt_against_state(
            prompt, state, 4, SceneMode.LITERAL
        )
        errors = [f for f in findings if f.is_error()]
        assert len(errors) >= 1

    def test_prop_state_contradiction_detected(self):
        from ytfactory.scene_continuity.prompt_validator import validate_prompt_against_state
        from ytfactory.scene_continuity.models import (
            PropState, SceneMode, SceneState
        )
        state = StoryState()
        lamp = PropState(name="oil lamp", canonical_id="oil_lamp", current_state="unlit")
        state.props["oil_lamp"] = lamp
        state.scene_modes[3] = SceneMode.LITERAL
        state.scene_history[3] = SceneState(
            scene_id=3, mode=SceneMode.LITERAL,
            character_states={}, prop_states={"oil_lamp": lamp}
        )
        prompt = "The glowing oil lamp illuminates the room."
        findings = validate_prompt_against_state(
            prompt, state, 4, SceneMode.LITERAL
        )
        prop_errors = [f for f in findings if f.category == "PROP_STATE"]
        assert len(prop_errors) >= 1

    def test_canonical_clothing_drift_detected(self):
        from ytfactory.scene_continuity.prompt_validator import validate_prompt_against_state
        from ytfactory.scene_continuity.models import (
            CharacterState, SceneMode, SceneState
        )
        state = StoryState()
        char = CharacterState(
            name="Traveler", canonical_id="traveler",
            alive=True, clothing="dark cloak and worn leather boots"
        )
        state.characters["traveler"] = char
        state.scene_modes[2] = SceneMode.LITERAL
        state.scene_history[2] = SceneState(
            scene_id=2, mode=SceneMode.LITERAL,
            character_states={"traveler": char}, prop_states={}
        )
        prompt = "The Traveler stands barefoot in the rain."
        findings = validate_prompt_against_state(
            prompt, state, 3, SceneMode.LITERAL
        )
        clothing = [f for f in findings if f.category == "CLOTHING_DRIFT"]
        assert len(clothing) >= 1


# ===========================================================================
# 30. Diagnostics
# ===========================================================================

class TestContinuityDiagnostics:
    def test_empty_report(self):
        from ytfactory.scene_continuity.diagnostics import ContinuityReport
        report = ContinuityReport()
        assert report.total_scenes == 0
        assert report.error_count == 0
        d = report.to_dict()
        assert d["error_count"] == 0

    def test_record_scene_updates_counts(self):
        from ytfactory.scene_continuity.diagnostics import (
            ContinuityReport, SceneContinuityStatus
        )
        from ytfactory.scene_continuity.models import ValidationLevel
        report = ContinuityReport()
        status = SceneContinuityStatus(
            scene_index=1,
            status="PASS",
            violations=[
                ContinuityFinding(
                    scene_id=1, level=ValidationLevel.WARNING,
                    category="TEST", message="test warning"
                )
            ],
        )
        report.record_scene(status)
        assert report.total_scenes == 1
        assert report.warning_count == 1

    def test_markdown_output(self):
        from ytfactory.scene_continuity.diagnostics import (
            ContinuityReport, SceneContinuityStatus
        )
        from ytfactory.scene_continuity.models import ValidationLevel
        report = ContinuityReport()
        report.record_scene(SceneContinuityStatus(scene_index=1, status="PASS"))
        report.record_scene(SceneContinuityStatus(
            scene_index=2, status="REPAIRED",
            prompt_violations=[
                ContinuityFinding(
                    scene_id=2, level=ValidationLevel.ERROR,
                    category="TEST", message="test error",
                    suggested_fix="fix it"
                )
            ],
        ))
        md = report.to_markdown()
        assert "Scene Continuity Report" in md
        assert "Scene 001" in md
        assert "Scene 002" in md
        assert "REPAIRED" in md
        assert "fix it" in md

    def test_write_report_creates_files(self, tmp_path):
        from ytfactory.scene_continuity.diagnostics import (
            ContinuityReport, SceneContinuityStatus
        )
        report = ContinuityReport()
        report.record_scene(SceneContinuityStatus(scene_index=1, status="PASS"))
        md_path = report.write_report(tmp_path)
        assert md_path.exists()
        assert md_path.name == "continuity-report.md"
        json_path = tmp_path / "scenes" / "continuity-report.json"
        assert json_path.exists()
