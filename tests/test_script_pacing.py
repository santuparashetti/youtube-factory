"""Tests for SCRIPT_PACING_AND_DURATION_RULES_V2 — prompts, validation logic, and node helpers."""

from __future__ import annotations

import pytest

from ytfactory.agents.prompts.script_writer import (
    DURATION_TOLERANCE_MINUTES,
    NARRATION_WPM,
    TARGET_IDEAL_MINUTES,
    build_compress_prompt,
    build_expand_pacing_prompt,
    build_review_prompt,
    build_write_script_prompt,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _word_count(text: str) -> int:
    return len(text.split())


def _estimated_minutes(word_count: int) -> float:
    return word_count / NARRATION_WPM


def _duration_ok(estimated: float, target: int) -> bool:
    return abs(estimated - target) <= DURATION_TOLERANCE_MINUTES


# ── Constants ──────────────────────────────────────────────────────────────────


class TestConstants:
    def test_narration_wpm(self):
        assert NARRATION_WPM == 130

    def test_tolerance_is_one_minute(self):
        assert DURATION_TOLERANCE_MINUTES == 1

    def test_default_target(self):
        assert TARGET_IDEAL_MINUTES == 7


# ── Duration validation logic ──────────────────────────────────────────────────


class TestDurationValidation:
    def test_exact_target_passes(self):
        assert _duration_ok(7.0, 7) is True

    def test_exactly_one_over_passes(self):
        assert _duration_ok(8.0, 7) is True

    def test_exactly_one_under_passes(self):
        assert _duration_ok(6.0, 7) is True

    def test_one_point_one_over_fails(self):
        assert _duration_ok(8.1, 7) is False

    def test_one_point_one_under_fails(self):
        assert _duration_ok(5.9, 7) is False

    def test_target_5_at_max_passes(self):
        assert _duration_ok(6.0, 5) is True

    def test_target_5_exceeds_fails(self):
        assert _duration_ok(6.1, 5) is False

    def test_target_10_at_max_passes(self):
        assert _duration_ok(11.0, 10) is True

    def test_target_10_exceeds_fails(self):
        assert _duration_ok(11.1, 10) is False

    def test_gap_calculation(self):
        estimated = 8.5
        target = 7
        gap = estimated - target
        assert abs(gap - 1.5) < 1e-9


# ── Word count and duration helpers ───────────────────────────────────────────


class TestWordCountHelpers:
    def test_word_count_empty(self):
        assert _word_count("") == 0

    def test_word_count_single(self):
        assert _word_count("hello") == 1

    def test_word_count_sentence(self):
        assert _word_count("this is a test sentence") == 5

    def test_estimated_minutes_zero(self):
        assert _estimated_minutes(0) == 0.0

    def test_estimated_minutes_one_minute(self):
        assert _estimated_minutes(NARRATION_WPM) == pytest.approx(1.0)

    def test_estimated_minutes_seven_minutes(self):
        assert _estimated_minutes(7 * NARRATION_WPM) == pytest.approx(7.0)


# ── build_write_script_prompt ─────────────────────────────────────────────────


class TestBuildWriteScriptPrompt:
    def _make(self, target=7):
        return build_write_script_prompt(
            topic="Test Topic",
            research_md="Research content.",
            script_outline="Outline content.",
            welcome="Welcome to Atma Theory.",
            closing="Think deeper.",
            topic_transition="Today we explore",
            target_minutes=target,
        )

    def test_contains_topic(self):
        assert "Test Topic" in self._make()

    def test_contains_target_minutes(self):
        prompt = self._make(target=8)
        assert "8 minutes" in prompt

    def test_contains_tolerance_window_7min(self):
        prompt = self._make(target=7)
        assert "6–8 minutes" in prompt

    def test_contains_tolerance_window_5min(self):
        prompt = self._make(target=5)
        assert "4–6 minutes" in prompt

    def test_max_words_reflects_target_plus_one(self):
        prompt = self._make(target=7)
        max_words = (7 + 1) * NARRATION_WPM  # 1040
        assert str(max_words) in prompt

    def test_contains_welcome(self):
        assert "Welcome to Atma Theory." in self._make()

    def test_contains_closing(self):
        assert "Think deeper." in self._make()

    def test_contains_research(self):
        assert "Research content." in self._make()

    def test_no_filler_instruction_present(self):
        assert "pad" in self._make().lower() or "filler" in self._make().lower()

    def test_pacing_preference_mentioned(self):
        assert "pacing" in self._make().lower() or "slower" in self._make().lower()

    def test_different_targets_produce_different_prompts(self):
        assert self._make(target=5) != self._make(target=10)


# ── build_review_prompt ───────────────────────────────────────────────────────


class TestBuildReviewPrompt:
    def _make(self, target=7):
        return build_review_prompt(
            topic="Some Topic",
            script="A short script.",
            word_count=910,
            estimated_minutes=7.0,
            target_minutes=target,
        )

    def test_contains_topic(self):
        assert "Some Topic" in self._make()

    def test_contains_target_range(self):
        prompt = self._make(target=8)
        assert "7–9 minutes" in prompt

    def test_contains_max_boundary(self):
        prompt = self._make(target=7)
        max_m = 7 + DURATION_TOLERANCE_MINUTES
        assert f"> {max_m} minutes" in prompt

    def test_contains_script(self):
        assert "A short script." in self._make()

    def test_no_labels_instruction(self):
        prompt = self._make()
        assert "No commentary" in prompt or "no labels" in prompt.lower()


# ── build_compress_prompt ─────────────────────────────────────────────────────


class TestBuildCompressPrompt:
    def _make(self, target=7):
        return build_compress_prompt(
            script="Long script content.",
            word_count=1500,
            estimated_minutes=11.5,
            target_minutes=target,
        )

    def test_contains_word_count(self):
        assert "1500 words" in self._make()

    def test_contains_max_words(self):
        prompt = self._make(target=7)
        max_words = (7 + 1) * NARRATION_WPM
        assert str(max_words) in prompt

    def test_contains_ideal_words(self):
        prompt = self._make(target=7)
        ideal_words = 7 * NARRATION_WPM
        assert str(ideal_words) in prompt

    def test_preserve_instruction(self):
        assert "Preserve" in self._make() or "preserve" in self._make()

    def test_no_rewrite_instruction(self):
        prompt = self._make()
        assert "rewrite" in prompt.lower()

    def test_never_remove_hook(self):
        assert "Opening hook" in self._make()


# ── build_expand_pacing_prompt ────────────────────────────────────────────────


class TestBuildExpandPacingPrompt:
    def _make(self, target=7):
        return build_expand_pacing_prompt(
            script="Short script.",
            word_count=520,
            estimated_minutes=4.0,
            target_minutes=target,
        )

    def test_contains_word_count(self):
        assert "520 words" in self._make()

    def test_contains_shortfall(self):
        prompt = self._make(target=7)
        assert "3.0 minutes" in prompt  # shortfall = 7 - 4.0

    def test_contains_minimum_words(self):
        prompt = self._make(target=7)
        min_words = (7 - 1) * NARRATION_WPM  # 780
        assert str(min_words) in prompt

    def test_pacing_instruction_present(self):
        prompt = self._make()
        assert "pacing" in prompt.lower() or "slower" in prompt.lower()

    def test_no_filler_instruction(self):
        prompt = self._make()
        assert "filler" in prompt.lower()

    def test_preservation_rules_present(self):
        prompt = self._make()
        assert "Preserve" in prompt or "preserve" in prompt

    def test_preferred_approach_before_word_addition(self):
        prompt = self._make()
        pacing_pos = prompt.lower().find("pacing")
        padding_pos = prompt.lower().find("filler")
        # Pacing guidance should appear before the filler-avoidance rule
        assert pacing_pos < padding_pos

    def test_different_targets_produce_different_prompts(self):
        assert self._make(target=5) != self._make(target=10)


# ── Integration: prompt content matches V2 spec requirements ──────────────────


class TestV2SpecCompliance:
    """Each test maps to a requirement in SCRIPT_PACING_AND_DURATION_RULES_V2.md."""

    def test_duration_is_hard_target_not_range(self):
        # V2: "Requested duration is a hard target"
        prompt = build_write_script_prompt(
            topic="T", research_md="R", script_outline="O",
            welcome="W", closing="C", topic_transition="Today",
            target_minutes=6,
        )
        assert "6 minutes" in prompt
        assert "hard limit" in prompt.lower() or "hard" in prompt.lower()

    def test_no_padding_instruction(self):
        # V2: "Never add filler"
        prompt = build_write_script_prompt(
            topic="T", research_md="R", script_outline="O",
            welcome="W", closing="C", topic_transition="Today",
            target_minutes=7,
        )
        assert "pad" in prompt.lower() or "filler" in prompt.lower()

    def test_pacing_over_padding_in_expand_prompt(self):
        # V2: "If base script is shorter: slow narration naturally"
        prompt = build_expand_pacing_prompt(
            script="Short.", word_count=300, estimated_minutes=2.3, target_minutes=7
        )
        assert "slower" in prompt.lower() or "pacing" in prompt.lower()
        assert "filler" in prompt.lower()

    def test_preserve_base_script_in_enhancer_prompt(self):
        # V2: "Preserve structure, flow, tone and simplicity"
        from ytfactory.agents.prompts.script_enhancer import build_enhance_script_prompt

        prompt = build_enhance_script_prompt(
            topic="T",
            script="Original script text.",
            target_minutes=7,
        )
        assert "preserve" in prompt.lower() or "source of truth" in prompt.lower()
        assert "Original script text." in prompt

    def test_tolerance_window_in_review_prompt(self):
        # V2: "Maximum variance ±1 minute"
        prompt = build_review_prompt(
            topic="T", script="S", word_count=900, estimated_minutes=6.9,
            target_minutes=7,
        )
        assert "6–8" in prompt  # min=6, max=8

    def test_validation_fails_outside_tolerance(self):
        # V2: "Fail validation if duration exceeds tolerance"
        assert _duration_ok(9.1, 7) is False  # 2.1 min over
        assert _duration_ok(4.9, 7) is False  # 2.1 min under

    def test_validation_passes_within_tolerance(self):
        assert _duration_ok(6.5, 7) is True
        assert _duration_ok(7.5, 7) is True
        assert _duration_ok(8.0, 7) is True
        assert _duration_ok(6.0, 7) is True
