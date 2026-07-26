"""Tests for docs/script/task-2.3-validator-fix.md.

Story fidelity validator fix: removes lexical/pattern "semantic" checks that
cannot judge whether cinematic imagery embodies a concept, fixes
HUMAN_CLASSIFICATION_VIOLATED false positives on animal pronouns, adds
semantic character equivalence for UNSUPPORTED_CHARACTER, and skips
ENVIRONMENT_MISMATCH for abstract/internal environments.
"""

from __future__ import annotations

import inspect

from ytfactory.images import validators as validators_module
from ytfactory.images.validators import (
    HumanClassification,
    StoryFidelityValidator,
    is_equivalent_character,
    run_validators,
    should_skip_environment_check,
)

_REMOVED_CODES = (
    "NARRATION_NOT_REPRESENTED",
    "STORY_GOAL_MISSING",
    "EMOTIONAL_BEAT_MISSING",
    "VISUAL_FOCUS_MISSING",
    "PRIMARY_SUBJECT_MISSING",
    "PRIMARY_ACTION_MISSING",
)


class TestSemanticChecksRemoved:
    def test_semantic_checks_removed_from_source(self):
        source = inspect.getsource(validators_module)
        for code in _REMOVED_CODES:
            assert f'"{code}"' not in source, f"{code} should have been removed"


# ── Fix 2 — HUMAN_CLASSIFICATION_VIOLATED false positives ────────────────────


class TestHumanCheckAnimalScenes:
    def test_human_check_skips_pronoun_in_animal_scene(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["mother eagle", "eaglet"]},
            prompt="Her wings spread wide as the mother eagle watches its chick, wide cinematic.",
            narration="The mother eagle encourages the chick to fly.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="animal_only",
        )
        assert not any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)

    def test_human_check_flags_man_in_animal_scene(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eaglet"]},
            prompt="A man standing at the cliff edge watches the eaglet, wide cinematic.",
            narration="The eaglet tests its wings.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="animal_only",
        )
        assert any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)


# ── Fix 3 — UNSUPPORTED_CHARACTER semantic equivalence ────────────────────────


class TestUnsupportedCharacterEquivalence:
    def test_is_equivalent_character_woman_she(self):
        assert is_equivalent_character("woman", ["she", "the boy"])

    def test_is_equivalent_character_boy_child(self):
        assert is_equivalent_character("boy", ["Mother", "Child"])

    def test_is_equivalent_character_false_for_unrelated(self):
        assert not is_equivalent_character("monk", ["eaglet", "mother eagle"])

    def test_unsupported_char_woman_equals_she(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["she", "the boy"]},
            prompt="The woman walks along the shore with the boy, wide cinematic.",
            narration="She walks along the shore with the boy.",
        )
        assert not any(e.code == "UNSUPPORTED_CHARACTER" for e in result.errors)

    def test_unsupported_char_boy_equals_child(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["Mother", "Child"]},
            prompt="The mother watches the boy play by the river, wide cinematic.",
            narration="The mother watches her child play.",
        )
        assert not any(e.code == "UNSUPPORTED_CHARACTER" for e in result.errors)

    def test_unsupported_char_elder_exempt_in_human_symbolic(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": []},
            prompt="An elder sits beneath an ancient tree, wide cinematic.",
            narration="Ancient teachers remind us that wisdom is earned slowly.",
            scene_category="human_symbolic",
        )
        assert not any(e.code == "UNSUPPORTED_CHARACTER" for e in result.errors)

    def test_unsupported_char_still_flagged_outside_human_symbolic(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eaglet"]},
            prompt="An elder sits beneath an ancient tree, wide cinematic.",
            narration="The eaglet tests its wings.",
            scene_category="animal_only",
        )
        assert any(e.code == "UNSUPPORTED_CHARACTER" for e in result.errors)


# ── Fix 4 — ENVIRONMENT_MISMATCH skipped for abstract environments ───────────


class TestEnvironmentMismatchAbstract:
    def test_should_skip_environment_check_abstract(self):
        assert should_skip_environment_check("internal/psychological space")
        assert should_skip_environment_check("Abstract")
        assert not should_skip_environment_check("cliff edge")

    def test_environment_mismatch_skipped_for_abstract(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["eaglet"],
                "environment": "internal/psychological space",
            },
            prompt="A still lake mirrors the sky at dawn, wide cinematic.",
            narration="The eaglet tests its wings.",
        )
        assert not any(e.code == "ENVIRONMENT_MISMATCH" for e in result.errors)

    def test_environment_mismatch_still_fires_for_concrete_environment(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eaglet"], "environment": "ocean"},
            prompt="A young eaglet tests its wings on a cliff edge, wide cinematic.",
            narration="The eaglet tests its wings.",
        )
        assert any(e.code == "ENVIRONMENT_MISMATCH" for e in result.errors)


# ── run_validators threads scene_category through ─────────────────────────────


class TestRunValidatorsSceneCategory:
    def test_scene_category_passed_through(self):
        result = run_validators(
            scene_analysis={"allowed_characters": []},
            prompt="Her wings spread as the mother eagle soars, wide cinematic.",
            narration="The mother eagle soars.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="animal_only",
        )
        assert not any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)
