"""Tests for faithfulness-gate retry feedback injection.

Verifies that build_retry_prompt contains:
  1. the prior violation text (specific item names, not just generic codes);
  2. the expanded human_classification rule;
  3. per-scene character / environment hard constraints;
  4. the "invent none" wording when allowed_chars is empty.

Also verifies that to_feedback_block() exposes violated_item names.
"""

from __future__ import annotations

import pytest

from ytfactory.images.validators import (
    HUMAN_CLASSIFICATION_RULES,
    HumanClassification,
    ValidationError,
    ValidationResult,
    build_retry_prompt,
    compose_feedback,
)


# ── to_feedback_block — violated_item included ────────────────────────────────


class TestFeedbackBlockViolatedItem:
    def test_forbidden_object_names_the_object(self):
        err = ValidationError(
            code="FORBIDDEN_OBJECT",
            message="Forbidden object present in prompt: 'phone'.",
            severity="critical",
            hint="Remove forbidden object from the visual prompt.",
            violated_item="phone",
        )
        block = err.to_feedback_block()
        assert "FORBIDDEN_OBJECT" in block
        assert "phone" in block
        assert "remove 'phone'" in block

    def test_unsupported_character_names_detected_and_allowed(self):
        err = ValidationError(
            code="UNSUPPORTED_CHARACTER",
            message="Unsupported character detected: 'monk'.",
            severity="critical",
            allowed_values=["Mother Eagle", "Eagle Chick"],
            violated_item="monk",
        )
        block = err.to_feedback_block()
        assert "monk" in block
        assert "Mother Eagle" in block
        assert "detected" in block

    def test_human_classification_violated_names_detected_word(self):
        err = ValidationError(
            code="HUMAN_CLASSIFICATION_VIOLATED",
            message="Human figure detected ('hands') but human_classification=NO_HUMAN_ALLOWED.",
            severity="critical",
            hint="Remove all human figures from this scene.",
            violated_item="hands",
        )
        block = err.to_feedback_block()
        assert "hands" in block
        assert "remove 'hands'" in block

    def test_no_violated_item_falls_back_to_allowed_values(self):
        err = ValidationError(
            code="ENVIRONMENT_MISMATCH",
            message="Environment mismatch.",
            severity="critical",
            allowed_values=["auction house"],
        )
        block = err.to_feedback_block()
        assert "auction house" in block
        assert "ENVIRONMENT_MISMATCH" in block

    def test_no_violated_item_no_allowed_falls_back_to_hint(self):
        err = ValidationError(
            code="SYMBOLIC_REPLACEMENT",
            message="Symbolic replacement detected.",
            severity="critical",
            hint="Symbolism may enhance but must never replace the literal story.",
        )
        block = err.to_feedback_block()
        assert "Symbolism" in block


# ── compose_feedback propagates violated_item ─────────────────────────────────


class TestComposeFeedback:
    def test_feedback_text_includes_forbidden_object_name(self):
        result = ValidationResult(
            passed=False,
            errors=[
                ValidationError(
                    code="FORBIDDEN_OBJECT",
                    message="Forbidden object present in prompt: 'smartphone'.",
                    severity="critical",
                    hint="Remove forbidden object from the visual prompt.",
                    violated_item="smartphone",
                )
            ],
        )
        text = compose_feedback(result)
        assert "smartphone" in text
        assert "FORBIDDEN_OBJECT" in text


# ── build_retry_prompt hard constraints ───────────────────────────────────────


def _minimal_scene(idx: int = 1, visual_prompt: str = "A city park at dawn.") -> dict:
    return {
        "index": idx,
        "narration": "Wealthy executives walk past a lone man.",
        "visual_prompt": visual_prompt,
        "scene_analysis": {},
    }


def _minimal_scene_analysis(
    allowed_characters: list[str] | None = None,
    environment: str = "",
    forbidden_objects: list[str] | None = None,
) -> dict:
    return {
        "allowed_characters": allowed_characters or [],
        "scene_characters": [],
        "environment": environment,
        "forbidden_objects": forbidden_objects or [],
        "scene_category": "human_implied",
        "human_requirement": "human_required",
    }


class TestBuildRetryPromptConstraints:
    def test_violation_text_in_prompt(self):
        feedback = "FAILED: FORBIDDEN_OBJECT — remove 'smartphone'"
        prompt = build_retry_prompt(
            scene=_minimal_scene(),
            scene_analysis=_minimal_scene_analysis(),
            narration="A man walks past.",
            violation_feedback=feedback,
        )
        assert "FORBIDDEN_OBJECT" in prompt
        assert "smartphone" in prompt
        assert "VIOLATION TO FIX" in prompt

    def test_character_constraint_present(self):
        prompt = build_retry_prompt(
            scene=_minimal_scene(),
            scene_analysis=_minimal_scene_analysis(allowed_characters=["wealthy executives", "a man"]),
            narration="Wealthy executives walk past a lone man.",
            violation_feedback="FAILED: UNSUPPORTED_CHARACTER — 'monk' detected",
            human_classification=HumanClassification.HUMAN_REQUIRED,
        )
        assert "wealthy executives" in prompt
        assert "ONLY" in prompt
        assert "HARD CONSTRAINTS" in prompt

    def test_environment_constraint_present(self):
        prompt = build_retry_prompt(
            scene=_minimal_scene(),
            scene_analysis=_minimal_scene_analysis(environment="auction houses abroad"),
            narration="Paintings are sold at auction.",
            violation_feedback="FAILED: ENVIRONMENT_MISMATCH — allowed: auction houses abroad",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert "auction houses abroad" in prompt
        assert "MUST be one of" in prompt

    def test_no_human_allowed_rule_mentions_hands(self):
        prompt = build_retry_prompt(
            scene=_minimal_scene(),
            scene_analysis=_minimal_scene_analysis(),
            narration="Empty marketplace at dawn.",
            violation_feedback="FAILED: HUMAN_CLASSIFICATION_VIOLATED — remove 'hands'",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        rule_text = HUMAN_CLASSIFICATION_RULES[HumanClassification.NO_HUMAN_ALLOWED]
        assert "hands" in rule_text
        assert "no_human_allowed" in prompt
        assert "hands" in prompt  # both from violated_item and from the rule

    def test_human_symbolic_rule_in_prompt(self):
        prompt = build_retry_prompt(
            scene=_minimal_scene(),
            scene_analysis=_minimal_scene_analysis(),
            narration="A lone figure stands at the crossroads.",
            violation_feedback="FAILED: HUMAN_CLASSIFICATION_VIOLATED — Include a symbolic human figure",
            human_classification=HumanClassification.HUMAN_SYMBOLIC,
        )
        assert "human_symbolic" in prompt
        assert "stylized" in prompt or "abstract" in prompt

    def test_empty_allowed_chars_produces_invent_none(self):
        prompt = build_retry_prompt(
            scene=_minimal_scene(),
            scene_analysis=_minimal_scene_analysis(allowed_characters=[]),
            narration="The market stalls are empty.",
            violation_feedback="FAILED: UNSUPPORTED_CHARACTER — 'man' detected",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert "NONE" in prompt
        assert "introduce no named person or figure" in prompt


# ── HUMAN_CLASSIFICATION_RULES completeness ───────────────────────────────────


class TestHumanClassificationRules:
    def test_all_values_have_rules(self):
        for hc in HumanClassification:
            assert hc in HUMAN_CLASSIFICATION_RULES, f"Missing rule for {hc}"

    def test_no_human_allowed_explicitly_lists_hands(self):
        rule = HUMAN_CLASSIFICATION_RULES[HumanClassification.NO_HUMAN_ALLOWED]
        assert "hands" in rule
        assert "feet" in rule
        assert "body part" in rule


# ── Bug-fix regression tests ──────────────────────────────────────────────────


class TestBodyPartFalsePositive:
    """Bug 1: isolated body-part words must NOT fire HUMAN_CLASSIFICATION_VIOLATED
    in non-animal_only NO_HUMAN_ALLOWED scenes (log: shoulder/arm/brain false positives)."""

    def _run(self, prompt: str, category: str = "landscape") -> list:
        from ytfactory.images.validators import StoryFidelityValidator
        v = StoryFidelityValidator()
        scene_analysis = {
            "allowed_characters": [],
            "forbidden_characters": [],
            "forbidden_objects": [],
            "scene_characters": [],
            "characters": [],
            "environment": "mountain pass",
            "scene_category": category,
        }
        result = v.validate(
            scene_analysis=scene_analysis,
            prompt=prompt,
            narration="A mountain path winds through fog.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category=category,
        )
        return [e.code for e in result.errors]

    def test_shoulder_in_landscape_scene_is_not_violation(self):
        # "mountain shoulder" is geographic — not a human
        codes = self._run("The rugged mountain shoulder disappears into low cloud.")
        assert "HUMAN_CLASSIFICATION_VIOLATED" not in codes

    def test_arm_in_landscape_scene_is_not_violation(self):
        codes = self._run("A river arm curves around the rocky outcrop at dawn.")
        assert "HUMAN_CLASSIFICATION_VIOLATED" not in codes

    def test_hand_in_non_animal_scene_is_not_violation(self):
        # hand is already excepted in non-animal scenes; regression guard
        codes = self._run("A golden hand reaches from a cloud in classical style.")
        assert "HUMAN_CLASSIFICATION_VIOLATED" not in codes

    def test_standing_figure_is_still_a_violation(self):
        # Action words remain hard violations — action implies a human agent
        codes = self._run("A figure standing at the edge of a cliff.")
        assert "HUMAN_CLASSIFICATION_VIOLATED" in codes

    def test_silhouette_is_still_a_violation(self):
        codes = self._run("A dark silhouette against the setting sun.")
        assert "HUMAN_CLASSIFICATION_VIOLATED" in codes


class TestHumanSymbolicForbiddenCharacterContradiction:
    """Bug 2: generic human tokens must NOT fire FORBIDDEN_CHARACTER when
    human_classification requires a human figure (log: scene 011 'man' rejected)."""

    def _run(
        self,
        prompt: str,
        forbidden: list[str],
        human_classification: HumanClassification,
    ) -> list:
        from ytfactory.images.validators import StoryFidelityValidator
        v = StoryFidelityValidator()
        scene_analysis = {
            "allowed_characters": [],
            "forbidden_characters": forbidden,
            "forbidden_objects": [],
            "scene_characters": [],
            "characters": [],
            "environment": "abstract",
            "scene_category": "human_symbolic",
        }
        result = v.validate(
            scene_analysis=scene_analysis,
            prompt=prompt,
            narration="A symbolic figure contemplates the void.",
            human_classification=human_classification,
            scene_category="human_symbolic",
        )
        return [e.code for e in result.errors]

    def test_man_not_forbidden_in_human_symbolic_scene(self):
        # entity extraction produced forbidden_characters=["man"] but the scene
        # requires a symbolic human — "man" must not be force-failed
        codes = self._run(
            prompt="A solitary man rendered as a geometric abstraction against fog.",
            forbidden=["man"],
            human_classification=HumanClassification.HUMAN_SYMBOLIC,
        )
        assert "FORBIDDEN_CHARACTER" not in codes

    def test_person_not_forbidden_in_human_required_scene(self):
        codes = self._run(
            prompt="A person kneeling in prayer, dramatically lit.",
            forbidden=["person"],
            human_classification=HumanClassification.HUMAN_REQUIRED,
        )
        assert "FORBIDDEN_CHARACTER" not in codes

    def test_non_generic_forbidden_still_fires_in_human_symbolic_scene(self):
        # Only generic human tokens get the bypass — named characters stay blocked
        codes = self._run(
            prompt="Arjuna stands on the battlefield, bow raised.",
            forbidden=["arjuna"],
            human_classification=HumanClassification.HUMAN_SYMBOLIC,
        )
        assert "FORBIDDEN_CHARACTER" in codes

    def test_man_IS_forbidden_in_no_human_scene(self):
        # Bypass only applies when human presence is required — not when forbidden
        from ytfactory.images.validators import StoryFidelityValidator
        v = StoryFidelityValidator()
        scene_analysis = {
            "allowed_characters": [],
            "forbidden_characters": ["man"],
            "forbidden_objects": [],
            "scene_characters": [],
            "characters": [],
            "environment": "forest",
            "scene_category": "landscape",
        }
        result = v.validate(
            scene_analysis=scene_analysis,
            prompt="A man walks through the ancient forest.",
            narration="The forest is empty and still.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="landscape",
        )
        codes = [e.code for e in result.errors]
        assert "FORBIDDEN_CHARACTER" in codes


# ── RUN3 false-positive fixes ─────────────────────────────────────────────────


class TestCameraTermNotHuman:
    """Fix A: 'profile'/'portrait' are shot vocabulary, not human body refs
    (log scene 013: HUMAN_CLASSIFICATION_VIOLATED — remove 'profile')."""

    def _codes(self, prompt: str) -> list:
        from ytfactory.images.validators import StoryFidelityValidator
        v = StoryFidelityValidator()
        scene_analysis = {
            "allowed_characters": [],
            "forbidden_characters": [],
            "forbidden_objects": [],
            "scene_characters": [],
            "characters": [],
            "environment": "an auction house",
            "scene_category": "object_focus",
        }
        result = v.validate(
            scene_analysis=scene_analysis,
            prompt=prompt,
            narration="A gavel rests on the auctioneer's desk.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="object_focus",
        )
        return [e.code for e in result.errors]

    def test_profile_shot_is_not_human_violation(self):
        codes = self._codes(
            "Profile shot of an antique vase in an auction house, side lighting."
        )
        assert "HUMAN_CLASSIFICATION_VIOLATED" not in codes

    def test_portrait_framing_is_not_human_violation(self):
        codes = self._codes(
            "A portrait orientation composition of a lone chair in an auction house."
        )
        assert "HUMAN_CLASSIFICATION_VIOLATED" not in codes

    def test_standing_still_fires(self):
        # regression guard — real human tokens are unaffected by the camera guard
        codes = self._codes(
            "A man standing beside the auction house podium."
        )
        assert "HUMAN_CLASSIFICATION_VIOLATED" in codes


class TestEnvironmentCoreWordMatch:
    """Fix C: qualified/plural environment strings match the depicted setting
    (log scene 013: ENVIRONMENT_MISMATCH — allowed 'auction houses abroad')."""

    def _env_error(self, environment: str, prompt: str) -> bool:
        from ytfactory.images.validators import StoryFidelityValidator
        v = StoryFidelityValidator()
        scene_analysis = {
            "allowed_characters": [],
            "forbidden_characters": [],
            "forbidden_objects": [],
            "scene_characters": [],
            "characters": [],
            "environment": environment,
            "scene_category": "object_focus",
        }
        result = v.validate(
            scene_analysis=scene_analysis,
            prompt=prompt,
            narration="A gavel falls.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="object_focus",
        )
        return "ENVIRONMENT_MISMATCH" in [e.code for e in result.errors]

    def test_plural_and_qualifier_still_match(self):
        # "auction houses abroad" ~ "an auction house"
        assert not self._env_error(
            "auction houses abroad",
            "Interior of an elegant auction house, warm chandelier light.",
        )

    def test_exact_substring_still_matches(self):
        assert not self._env_error(
            "a quiet monastery",
            "A quiet monastery courtyard at dawn.",
        )

    def test_genuinely_wrong_environment_still_fails(self):
        # a monastery prompt must not satisfy an auction-house environment
        assert self._env_error(
            "auction houses abroad",
            "A quiet monastery courtyard at dawn, stone walls.",
        )

    def test_warehouse_does_not_satisfy_house(self):
        # start-boundary guard: "warehouse" must not match core word "house"
        assert self._env_error(
            "auction houses abroad",
            "A dim warehouse full of crates and forklifts.",
        )

    def test_outdoor_market_not_satisfied_by_indoor(self):
        # indoors/outdoors are NOT qualifier-stripped — they change the visual,
        # so "outdoor market" must count "outdoor" toward the core-word match
        assert self._env_error(
            "outdoor market",
            "A bustling indoor market hall under a glass roof.",
        )

    def test_outdoor_market_matched_by_outdoor_prompt(self):
        assert not self._env_error(
            "outdoor market",
            "A bustling outdoor market with striped awnings at noon.",
        )


class TestForbiddenObjectMetaphorGuard:
    """Fix B: a forbidden object that is the scene's own required visual /
    metaphor must not fire (log scene 017: FORBIDDEN_OBJECT — remove 'canvas'
    on a paint-a-life-onto-canvas scene)."""

    def _codes(self, prompt, forbidden_objects, narration="", visual_anchor=""):
        from ytfactory.images.validators import StoryFidelityValidator
        v = StoryFidelityValidator()
        scene_analysis = {
            "allowed_characters": [],
            "forbidden_characters": [],
            "forbidden_objects": forbidden_objects,
            "scene_characters": [],
            "characters": [],
            "environment": "abstract",
            "scene_category": "abstract",
        }
        result = v.validate(
            scene_analysis=scene_analysis,
            prompt=prompt,
            narration=narration,
            human_classification=HumanClassification.HUMAN_SYMBOLIC,
            scene_category="abstract",
            visual_anchor=visual_anchor,
        )
        return [e.code for e in result.errors]

    def test_canvas_in_narration_is_not_forbidden(self):
        codes = self._codes(
            prompt="A vast blank canvas slowly filling with colour.",
            forbidden_objects=["canvas"],
            narration="Each choice paints a life onto the canvas of the years.",
        )
        assert "FORBIDDEN_OBJECT" not in codes

    def test_canvas_in_visual_anchor_is_not_forbidden(self):
        codes = self._codes(
            prompt="A vast blank canvas slowly filling with colour.",
            forbidden_objects=["canvas"],
            narration="Each choice adds a brushstroke.",
            visual_anchor="A painter's canvas being filled stroke by stroke.",
        )
        assert "FORBIDDEN_OBJECT" not in codes

    def test_unrelated_forbidden_object_still_fires(self):
        # guard only exempts the scene's own required visual — others still block
        codes = self._codes(
            prompt="A canvas beside a smartphone on the table.",
            forbidden_objects=["smartphone"],
            narration="Each choice paints a life onto the canvas.",
            visual_anchor="A painter's canvas.",
        )
        assert "FORBIDDEN_OBJECT" in codes
