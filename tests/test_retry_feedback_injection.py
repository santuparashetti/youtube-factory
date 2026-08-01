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
