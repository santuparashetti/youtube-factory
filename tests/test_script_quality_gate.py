"""Regression tests for the Script Quality Gate — SINGLE_VISUAL_WORLD check.

These tests mock the LLM to reproduce the exact prompting behaviour and verify
that the guard clause added to _QUALITY_GATE_PROMPT prevents false positives
from common English idioms while still catching genuinely split visual worlds.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from ytfactory.agents.nodes.scene_planner import (
    ScriptQualityGateError,
    _run_script_quality_gate,
    _QUALITY_GATE_PROMPT,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_llm(json_response: dict) -> MagicMock:
    """Return a mock LLM that yields the given JSON dict as its text response."""
    llm = MagicMock()
    llm.generate.return_value = MagicMock(text=json.dumps(json_response))
    return llm


def _all_pass() -> dict:
    return {
        "single_visual_world": {"result": "PASS", "reason": ""},
        "no_repeated_beats": {"result": "PASS", "reason": ""},
        "hook_ending_loop": {"result": "PASS", "reason": ""},
        "no_disclaimer_paragraphs": {"result": "PASS", "reason": ""},
    }


# ── Canonical production script fixture ──────────────────────────────────────

_ANT_MOUNTAIN_SCRIPT = """\
A tiny ant—with legs smaller than a grain of rice—has decided to climb Mount Everest.

[Visual: A tiny ant crawls across a massive rock, then the image expands into towering Himalayan peaks.]

A bird sees the ant moving along the path and asks, "You need to cover 2,000 kilometers.
How on earth are you going to do that?"

The ant doesn't boast. It answers with a philosophy:

"Every single step I take brings me closer. My mind, my eyes, and my entire existence are
filled with the mountain. Through relentless effort, I will reach it."

Most people fail not because they lack talent, but because they quit when the mountain looks too big.

You cannot build an unshakable life on borrowed effort, shortcuts, or handouts.
Build your own foundation through self-reliance and honest work. Real strength comes from
standing on your own two feet, doing the work brick by brick—not because every step is
dramatic, but because the foundation becomes yours.

[NARRATIVE_ENDING]

So when your Himalayas seem impossible, remember the ant. It does not need a giant leap,
a perfect day, or proof that the summit is near. It needs another continuous, unbroken step.
"""


# ── Guard clause: prompt text ─────────────────────────────────────────────────

class TestQualityGatePromptGuardClause:
    """The prompt itself must contain the idiom guard clause."""

    def test_guard_clause_present(self):
        """_QUALITY_GATE_PROMPT must contain the single_visual_world guard clause."""
        assert "single visual world check" in _QUALITY_GATE_PROMPT.lower()

    def test_brick_by_brick_explicitly_listed(self):
        assert "brick by brick" in _QUALITY_GATE_PROMPT

    def test_build_your_own_foundation_explicitly_listed(self):
        assert "build your own foundation" in _QUALITY_GATE_PROMPT

    def test_standing_on_your_own_two_feet_explicitly_listed(self):
        assert "standing on your own two feet" in _QUALITY_GATE_PROMPT

    def test_three_conditions_required_for_fail(self):
        """Guard must specify ALL THREE conditions must hold before FAILing."""
        assert "ALL THREE" in _QUALITY_GATE_PROMPT or "all three" in _QUALITY_GATE_PROMPT.lower()

    def test_phrase_alone_does_not_constitute_visual_world(self):
        assert "phrase alone" in _QUALITY_GATE_PROMPT


# ── Regression: ant/mountain + idiomatic "brick by brick" passes ──────────────

class TestSingleVisualWorldFalsePositive:
    """LLM verdict PASS for idiomatic language must propagate correctly."""

    def test_ant_mountain_script_with_brick_idiom_passes(self):
        """The canonical script with 'brick by brick' must not raise."""
        llm = _make_llm(_all_pass())
        # Must not raise ScriptQualityGateError
        _run_script_quality_gate(_ANT_MOUNTAIN_SCRIPT, llm)

    def test_isolated_idiom_paragraphs_do_not_fail(self):
        """A script with multiple idiomatic phrases but one visual world passes."""
        script = (
            "He walked into the arena for the ten-thousandth time.\n\n"
            "[Visual: A man enters a sunlit training hall.]\n\n"
            "Greatness is built step by step, brick by brick, one honest day at a time.\n\n"
            "Lay the groundwork now. The foundation you build is yours to keep.\n\n"
            "[NARRATIVE_ENDING]\n\n"
            "Standing on your own two feet means returning tomorrow, and the day after.\n"
        )
        llm = _make_llm(_all_pass())
        _run_script_quality_gate(script, llm)  # must not raise

    def test_gate_passes_when_llm_returns_pass_for_all_checks(self):
        """No exception raised when all four checks return PASS."""
        llm = _make_llm(_all_pass())
        _run_script_quality_gate("Any script content.", llm)


# ── Genuine FAIL: second developed visual world still raises ──────────────────

class TestSingleVisualWorldGenuineFail:
    """A second developed visual world with dedicated [Visual:] directions must still fail."""

    def test_eagle_story_after_ant_story_fails(self):
        """Script developing an independent eagle narrative fails single_visual_world."""
        response = _all_pass()
        response["single_visual_world"] = {
            "result": "FAIL",
            "reason": (
                "The script establishes an ant/mountain journey, then pivots to an "
                "independent eagle story across three scenes with dedicated [Visual:] "
                "directions unrelated to the mountain."
            ),
        }
        llm = _make_llm(response)
        with pytest.raises(ScriptQualityGateError, match="Single visual world"):
            _run_script_quality_gate("script with two full stories", llm)

    def test_lamp_metaphor_developed_independently_fails(self):
        """An independently developed lamp metaphor with its own visual arc fails."""
        response = _all_pass()
        response["single_visual_world"] = {
            "result": "FAIL",
            "reason": "A lamp metaphor is introduced and developed across four separate scenes.",
        }
        llm = _make_llm(response)
        with pytest.raises(ScriptQualityGateError, match="Single visual world"):
            _run_script_quality_gate("script with lamp world", llm)

    def test_error_message_includes_reason(self):
        """ScriptQualityGateError message must include the LLM-provided reason."""
        reason = "Eagle story introduced with three dedicated visual scenes."
        response = _all_pass()
        response["single_visual_world"] = {"result": "FAIL", "reason": reason}
        llm = _make_llm(response)
        with pytest.raises(ScriptQualityGateError, match=reason):
            _run_script_quality_gate("script", llm)


# ── Other checks unaffected ───────────────────────────────────────────────────

class TestOtherGateChecksUnaffected:
    """Guard clause must not change behaviour of the other three checks."""

    def test_repeated_beats_fail_still_raises(self):
        response = _all_pass()
        response["no_repeated_beats"] = {
            "result": "FAIL",
            "reason": "The same point about patience appears twice in the story section.",
        }
        llm = _make_llm(response)
        with pytest.raises(ScriptQualityGateError, match="No repeated beats"):
            _run_script_quality_gate("script", llm)

    def test_hook_ending_loop_fail_still_raises(self):
        response = _all_pass()
        response["hook_ending_loop"] = {
            "result": "FAIL",
            "reason": "NARRATIVE_ENDING is a subscribe CTA with no narrative content.",
        }
        llm = _make_llm(response)
        with pytest.raises(ScriptQualityGateError, match="Hook-to-ending loop"):
            _run_script_quality_gate("script", llm)

    def test_llm_failure_does_not_raise(self):
        """LLM/parse failure must be non-blocking (logs warning, passes through)."""
        llm = MagicMock()
        llm.generate.side_effect = RuntimeError("LLM unavailable")
        _run_script_quality_gate("script", llm)  # must not raise
