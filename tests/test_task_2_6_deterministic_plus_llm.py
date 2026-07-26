"""Tests for docs/script/task-2.6-deterministic-plus-llm.md.

Part 1: ABSTRACT_ENVIRONMENTS catch-alls + STORY_TIME_MISSING removed.
Part 2: LLM validation layer for ENVIRONMENT_MISMATCH/HUMAN_CLASSIFICATION_VIOLATED.
Part 3: FORBIDDEN_CHARACTER must not fire for an allowed character.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from ytfactory.agents.nodes import scene_planner as scene_planner_module
from ytfactory.agents.nodes.scene_planner import (
    LLM_VALIDATABLE_CHECKS,
    _run_llm_validation,
    _should_use_llm_validation,
)
from ytfactory.agents.prompts.scene_planner import build_llm_validation_prompt
from ytfactory.images.validators import (
    HumanClassification,
    StoryFidelityValidator,
    should_skip_environment_check,
)


# ── Part 1A — ABSTRACT_ENVIRONMENTS catch-alls ────────────────────────────────


class TestAbstractEnvironmentCatchAlls:
    def test_abstract_env_implied_prefix(self):
        assert should_skip_environment_check("implied human existence") is True
        assert should_skip_environment_check("implied everyday life setting") is True

    def test_abstract_env_no_specific(self):
        assert should_skip_environment_check("no specific location") is True

    def test_abstract_env_realm(self):
        assert should_skip_environment_check("open sky realm") is True
        assert should_skip_environment_check("nest in the open sky realm") is True

    def test_abstract_env_narrators_mind(self):
        assert should_skip_environment_check("the narrator's mind") is True

    def test_realm_catch_all_requires_short_phrase(self):
        """The 'realm' catch-all is scoped to <=5 words to avoid over-matching
        a long, concrete environment description that happens to say 'realm'."""
        long_env = "a vast desert realm stretching endlessly toward distant purple mountains at dusk"
        assert should_skip_environment_check(long_env) is False


# ── Part 1B — STORY_TIME_MISSING removed entirely ─────────────────────────────


class TestStoryTimeMissingRemoved:
    def test_story_time_missing_not_in_validators(self):
        from ytfactory.images import validators

        source = inspect.getsource(validators)
        assert "STORY_TIME_MISSING" not in source


# ── Part 2 — LLM validation layer ─────────────────────────────────────────────


class TestShouldUseLlmValidation:
    def test_env_mismatch_only(self):
        assert _should_use_llm_validation(["ENVIRONMENT_MISMATCH"]) is True

    def test_human_violated_only(self):
        assert _should_use_llm_validation(["HUMAN_CLASSIFICATION_VIOLATED"]) is True

    def test_both_together(self):
        assert _should_use_llm_validation(
            ["ENVIRONMENT_MISMATCH", "HUMAN_CLASSIFICATION_VIOLATED"]
        ) is True

    def test_mixed_with_structural_error_disqualifies(self):
        assert _should_use_llm_validation(["ENVIRONMENT_MISMATCH", "FORBIDDEN_CHARACTER"]) is False

    def test_empty_list_is_false(self):
        assert _should_use_llm_validation([]) is False

    def test_llm_validatable_checks_set(self):
        assert LLM_VALIDATABLE_CHECKS == {"ENVIRONMENT_MISMATCH", "HUMAN_CLASSIFICATION_VIOLATED"}


class TestRunLlmValidation:
    def _mock_llm(self, response_json: str) -> MagicMock:
        llm = MagicMock()
        llm.generate.return_value = MagicMock(text=response_json)
        return llm

    def test_both_ok_passes(self):
        llm = self._mock_llm('{"environment_ok": true, "human_ok": true, "reason": "fine"}')
        passed, reason = _run_llm_validation(
            {"scene_category": "abstract", "environment": "forest"},
            HumanClassification.NO_HUMAN_ALLOWED,
            "A quiet forest clearing, wide cinematic.",
            llm,
        )
        assert passed is True
        assert reason == "fine"

    def test_environment_not_ok_fails(self):
        llm = self._mock_llm('{"environment_ok": false, "human_ok": true, "reason": "wrong setting"}')
        passed, reason = _run_llm_validation(
            {"scene_category": "abstract", "environment": "forest"},
            HumanClassification.NO_HUMAN_ALLOWED,
            "A city street, wide cinematic.",
            llm,
        )
        assert passed is False
        assert reason == "wrong setting"

    def test_parse_failure_does_not_block(self):
        llm = self._mock_llm("not valid json")
        passed, reason = _run_llm_validation(
            {"scene_category": "abstract", "environment": "forest"},
            HumanClassification.NO_HUMAN_ALLOWED,
            "test prompt",
            llm,
        )
        assert passed is True
        assert "llm_parse_failed" in reason

    def test_exception_does_not_block(self):
        llm = MagicMock()
        llm.generate.side_effect = RuntimeError("network error")
        passed, reason = _run_llm_validation(
            {"scene_category": "abstract", "environment": "forest"},
            HumanClassification.NO_HUMAN_ALLOWED,
            "test prompt",
            llm,
        )
        assert passed is True
        assert "llm_parse_failed" in reason

    def test_uses_json_mode(self):
        llm = self._mock_llm('{"environment_ok": true, "human_ok": true, "reason": "ok"}')
        _run_llm_validation(
            {"scene_category": "abstract", "environment": "forest"},
            HumanClassification.NO_HUMAN_ALLOWED,
            "test prompt",
            llm,
        )
        assert llm.generate.call_args.kwargs.get("json_mode") is True


class TestBuildLlmValidationPrompt:
    def test_prompt_contains_scene_fields(self):
        prompt = build_llm_validation_prompt(
            scene_category="animal_only",
            human_classification="no_human_allowed",
            environment="forest clearing",
            visual_prompt="An eagle perched on a branch.",
        )
        assert "animal_only" in prompt
        assert "no_human_allowed" in prompt
        assert "forest clearing" in prompt
        assert "An eagle perched on a branch." in prompt
        assert "environment_ok" in prompt
        assert "human_ok" in prompt

    def test_empty_environment_defaults_to_unspecified(self):
        prompt = build_llm_validation_prompt(
            scene_category="abstract",
            human_classification="no_human_allowed",
            environment="",
            visual_prompt="test",
        )
        assert "unspecified" in prompt


class TestLlmValidationWiredIntoRetryLoop:
    def test_llm_validation_client_created_separately_from_generation_client(self):
        source = inspect.getsource(scene_planner_module)
        assert '_get_cheap_llm(settings, "llm_validation")' in source

    def test_faithfulness_qa_includes_llm_validated_fields(self):
        source = inspect.getsource(scene_planner_module)
        assert '"llm_validated"' in source
        assert '"llm_reason"' in source

    def test_llm_validation_gated_by_settings_flag(self):
        source = inspect.getsource(scene_planner_module)
        assert "settings.faithfulness_llm_validation_enabled" in source


# ── Part 3 — FORBIDDEN_CHARACTER respects allowed_characters ──────────────────


class TestForbiddenCharacterRespectsAllowed:
    def test_forbidden_character_not_fired_for_allowed_char(self):
        """Scene 014 repro: forbidden_characters accidentally includes 'boy',
        which is also in allowed_characters — must not fire."""
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["boy", "mother"],
                "forbidden_characters": ["boy"],
            },
            prompt="A young boy walks with his mother, wide cinematic.",
            narration="A boy walks with his mother.",
        )
        assert not any(e.code == "FORBIDDEN_CHARACTER" for e in result.errors)

    def test_forbidden_character_still_fires_when_not_allowed(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["eaglet"],
                "forbidden_characters": ["silhouette"],
            },
            prompt="A silhouette stands on the cliff, wide cinematic.",
            narration="The eaglet tests its wings.",
        )
        assert any(e.code == "FORBIDDEN_CHARACTER" for e in result.errors)

    def test_forbidden_character_equivalence_with_article(self):
        """allowed=['a boy'], forbidden=['boy'] — article-stripped equivalence."""
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["a boy"],
                "forbidden_characters": ["boy"],
            },
            prompt="A boy runs along the beach, wide cinematic.",
            narration="A boy runs along the beach.",
        )
        assert not any(e.code == "FORBIDDEN_CHARACTER" for e in result.errors)
