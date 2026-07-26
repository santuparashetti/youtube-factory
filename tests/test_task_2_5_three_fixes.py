"""Tests for docs/script/task-2.5-three-fixes.md.

Fix A: forbidden-words block moved to the very top of the generation prompt.
Fix B: per-scene REQUIRED SETTING environment hard constraint.
Fix C: unify pass/fail on zero CRITICAL errors (not zero errors of any
severity) at the single retry-loop evaluation point.
"""

from __future__ import annotations

import inspect

from ytfactory.agents.nodes import scene_planner as scene_planner_module
from ytfactory.agents.prompts.scene_planner import (
    _VISUAL_PROMPTS_TEMPLATE,
    build_visual_prompts_prompt,
)


# ── Fix A — forbidden words at the very top ───────────────────────────────────


class TestForbiddenWordsAtTop:
    def test_template_has_absolute_constraints_before_scene_content(self):
        """Task 2.8 prepended STORYBOARD MODE/STRICT SCENE FIDELITY ahead of
        this block — ⚠ ABSOLUTE CONSTRAINTS is no longer position 0, but it
        must still precede all scene-specific content."""
        assert "⚠ ABSOLUTE CONSTRAINTS" in _VISUAL_PROMPTS_TEMPLATE
        assert _VISUAL_PROMPTS_TEMPLATE.index("⚠ ABSOLUTE CONSTRAINTS") < _VISUAL_PROMPTS_TEMPLATE.index("{scene_list}")

    def test_built_prompt_has_absolute_constraints_before_scene_content(self):
        prompt = build_visual_prompts_prompt(
            [{"index": 1, "narration": "test", "shot_type": "wide shot"}],
            style=None,
        )
        assert prompt.index("⚠ ABSOLUTE CONSTRAINTS") < prompt.index("Scene 1")

    def test_forbidden_words_precede_scene_specific_content(self):
        prompt = build_visual_prompts_prompt(
            [{"index": 1, "narration": "a very unique narration marker", "shot_type": "wide shot"}],
            style=None,
        )
        assert prompt.index("FORBIDDEN WORDS") < prompt.index("a very unique narration marker")

    def test_animal_only_guidance_present(self):
        prompt = build_visual_prompts_prompt(
            [{"index": 1, "narration": "test", "shot_type": "wide shot"}], style=None
        )
        assert "ANIMAL_ONLY SCENES" in prompt


# ── Fix B — environment hard constraint per scene ─────────────────────────────


class TestEnvironmentConstraint:
    def test_environment_constraint_injected_when_specific(self):
        prompt = build_visual_prompts_prompt(
            [
                {
                    "index": 1,
                    "narration": "test",
                    "shot_type": "wide shot",
                    "scene_analysis": {"environment": "bedroom upon waking"},
                }
            ],
            style=None,
        )
        assert "REQUIRED SETTING: bedroom upon waking" in prompt
        assert "Do not use a different location" in prompt

    def test_environment_constraint_skipped_when_no_specific_location(self):
        prompt = build_visual_prompts_prompt(
            [
                {
                    "index": 1,
                    "narration": "test",
                    "shot_type": "wide shot",
                    "scene_analysis": {"environment": "no specific location"},
                }
            ],
            style=None,
        )
        assert "REQUIRED SETTING" not in prompt

    def test_environment_constraint_skipped_when_abstract(self):
        prompt = build_visual_prompts_prompt(
            [{"index": 1, "narration": "test", "shot_type": "wide shot", "scene_analysis": {"environment": "abstract"}}],
            style=None,
        )
        assert "REQUIRED SETTING" not in prompt

    def test_environment_constraint_skipped_when_missing(self):
        prompt = build_visual_prompts_prompt(
            [{"index": 1, "narration": "test", "shot_type": "wide shot"}], style=None
        )
        assert "REQUIRED SETTING" not in prompt

    def test_environment_constraint_per_scene_in_batch(self):
        prompt = build_visual_prompts_prompt(
            [
                {"index": 1, "narration": "n1", "shot_type": "wide shot", "scene_analysis": {"environment": "ashram courtyard"}},
                {"index": 2, "narration": "n2", "shot_type": "wide shot", "scene_analysis": {"environment": "unspecified"}},
            ],
            style=None,
        )
        assert "REQUIRED SETTING: ashram courtyard" in prompt
        assert prompt.count("REQUIRED SETTING") == 1


# ── Fix C — zero CRITICAL errors always means PASS ────────────────────────────


class TestUnifiedZeroErrorsPass:
    def test_pass_gated_on_critical_errors_not_all_errors(self):
        """The single evaluation point checks `not critical_errors`, not
        `deterministic_result.passed` (which requires zero errors of ANY
        severity, including minor ones like STORY_TIME_MISSING) — a minor-only
        issue must not block PASS."""
        source = inspect.getsource(scene_planner_module)
        assert "if not critical_errors:" in source
        # the old, stricter (buggy) condition must be gone
        assert "if deterministic_result.passed:" not in source

    def test_no_stray_deterministic_passed_gate_remains(self):
        source = inspect.getsource(scene_planner_module)
        assert "deterministic_result.passed and legacy_passed" not in source
