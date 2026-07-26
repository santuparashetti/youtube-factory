"""Tests for docs/script/task-2.4-seven-fixes.md.

Seven targeted fixes on top of Task 2.3: zero-errors-is-pass bug, article
stripping in character matching, is_equivalent_character wiring, expanded
UNAMBIGUOUS_HUMAN_WORDS with animal-possessive nuance for eye/hand, forbidden
generation words, expanded fuzzy ABSTRACT_ENVIRONMENTS, and symbolic figures
in abstract/no-chars scenes as a warning rather than a hard violation.
"""

from __future__ import annotations

import inspect

from ytfactory.agents.nodes import scene_planner as scene_planner_module
from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt
from ytfactory.images.validators import (
    HumanClassification,
    StoryFidelityValidator,
    is_equivalent_character,
    run_validators,
    should_skip_environment_check,
)


# ── Fix 1 — zero errors must always mean PASS ─────────────────────────────────


class TestZeroErrorsIsPass:
    def test_clean_prompt_has_zero_errors_and_passes(self):
        result = run_validators(
            scene_analysis={"allowed_characters": ["eaglet"]},
            prompt="A young eaglet tests its wings on a cliff edge, wide cinematic.",
            narration="The eaglet tests its wings.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="animal_only",
        )
        assert result.errors == []
        assert result.passed is True

    def test_retry_loop_never_lets_legacy_check_override_clean_deterministic_result(self):
        """Regression guard for the exact bug: 'FAIL | 0 errors' then FAILED
        after retries, because an LLM-based legacy check could flip a
        deterministically-clean scene to failed. The fix makes deterministic
        pass unconditional on zero CRITICAL errors; legacy disagreement is
        logged, not blocking. Task 2.5 Fix C tightened this further from
        `deterministic_result.passed` (zero errors of ANY severity) to zero
        CRITICAL errors specifically — a minor-only issue must not block PASS."""
        source = inspect.getsource(scene_planner_module)
        assert "if deterministic_result.passed and legacy_passed:" not in source
        assert "if not critical_errors:" in source


# ── Fix 2 — article stripping ─────────────────────────────────────────────────


class TestArticleStripping:
    def test_article_stripped_in_char_match(self):
        assert is_equivalent_character("man", ["a man"]) is True

    def test_article_stripped_woman_she(self):
        assert is_equivalent_character("woman", ["she", "the boy"]) is True

    def test_article_stripped_an_prefix(self):
        assert is_equivalent_character("elder", ["an elder"]) is True


# ── Fix 3 — is_equivalent_character wired into UNSUPPORTED_CHARACTER ─────────


class TestEquivalenceWiring:
    def test_is_equivalent_character_called_in_unsupported_check(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["she"]},
            prompt="A woman walks along the shore, wide cinematic.",
            narration="She walks along the shore.",
        )
        assert not any(e.code == "UNSUPPORTED_CHARACTER" for e in result.errors)

    def test_article_and_equivalence_combined(self):
        """Scene 006 repro: allowed=['a man'], detected='man'."""
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["a man"]},
            prompt="A man walks the shoreline at dusk, wide cinematic.",
            narration="A man walks the shoreline.",
        )
        assert not any(e.code == "UNSUPPORTED_CHARACTER" for e in result.errors)


# ── Fix 4 — expanded UNAMBIGUOUS_HUMAN_WORDS + animal-possessive nuance ──────


class TestExpandedHumanWords:
    def test_face_flagged_in_animal_only(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eagle"], "characters": ["eagle"]},
            prompt="The bird's face turned toward the sun, wide cinematic.",
            narration="The eagle watches the sunrise.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="animal_only",
        )
        assert any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)

    def test_shoulder_flagged_in_animal_only(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eagle"], "characters": ["eagle"]},
            prompt="Feathers ripple across its shoulder as it lifts off, wide cinematic.",
            narration="The eagle takes flight.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="animal_only",
        )
        assert any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)

    def test_eye_allowed_with_animal_possessive(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eagle"], "characters": ["eagle"]},
            prompt="The eagle's eye catches the last light, wide cinematic.",
            narration="The eagle watches the sunset.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="animal_only",
        )
        assert not any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)

    def test_eye_flagged_without_animal_possessive(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eagle"], "characters": ["eagle"]},
            prompt="A single eye stares out from the shadows, wide cinematic.",
            narration="The eagle watches the sunset.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="animal_only",
        )
        assert any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)


# ── Fix 5 — forbidden words in generation prompt ──────────────────────────────


class TestForbiddenGenerationWords:
    def test_generation_prompt_bans_silhouette_ethereal_glow_text_watermark(self):
        prompt = build_visual_prompts_prompt(
            [{"index": 1, "narration": "test", "shot_type": "wide shot"}],
            style=None,
        )
        assert "FORBIDDEN WORDS" in prompt
        assert "silhouette" in prompt.lower()
        assert "ethereal glow" in prompt.lower()
        assert "watermark" in prompt.lower()


# ── Fix 6 — expanded fuzzy ABSTRACT_ENVIRONMENTS ──────────────────────────────


class TestExpandedAbstractEnvironments:
    def test_abstract_env_inside_head(self):
        assert should_skip_environment_check("inside his head") is True

    def test_abstract_env_substring_match(self):
        assert should_skip_environment_check("the boy's head (implied mental space)") is True

    def test_abstract_env_imagination(self):
        assert should_skip_environment_check("a fleeting image in his imagination") is True


# ── Fix 7 — symbolic figure in abstract/no-chars scene is a warning ──────────


class TestSymbolicFigureAbstractWarning:
    def test_sage_in_abstract_scene_no_chars_is_not_a_violation(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": [], "characters": []},
            prompt="An ancient sage sits in stillness beneath a banyan tree, wide cinematic.",
            narration="Ancient teachers remind us that wisdom is earned slowly.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="abstract",
        )
        assert result.passed is True
        assert result.errors == []

    def test_sage_still_flagged_when_characters_were_extracted(self):
        """Fix 7 only relaxes the no-characters-extracted case."""
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eaglet"], "characters": ["eaglet"]},
            prompt="An ancient sage sits in stillness beneath a banyan tree, wide cinematic.",
            narration="The eaglet tests its wings.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="abstract",
        )
        assert any(e.code == "UNSUPPORTED_CHARACTER" for e in result.errors)
