"""Regression tests for image-prompt pipeline hardening (2026-08-16).

Focus areas:
  1. PROMPT INTEGRITY    — structural corruption detection
  2. COMPOSITOR TEXT     — readable text / word-appears / Devanagari / single-line-of-writing
  3. CHARACTER LEAKAGE   — recurring animal (ant) injected into non-ant scenes
  4. SEMANTIC QA         — deterministic vs LLM check separation
"""

from __future__ import annotations

import pytest

from ytfactory.images.prompt_synthesis import (
    SynthesisIssue,
    validate_scene_prompt_qa,
    validate_synthesis_result,
)
from ytfactory.images.prompt_validator import validate_prompt_contradictions


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _check_names(issues: list[SynthesisIssue]) -> list[str]:
    return [i.check for i in issues]


# ─────────────────────────────────────────────────────────────────────────────
# 1. PROMPT INTEGRITY — structural corruption (pre-existing checks, no regression)
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptIntegrity:
    def test_empty_prompt_blocked(self) -> None:
        issues = validate_synthesis_result("", scene_index=1, character_presence=[])
        assert "empty_prompt" in _check_names(issues)

    def test_broken_join_blocked(self) -> None:
        prompt = "A vast landscape with a The mountain rising beyond it, 16:9 aspect ratio."
        issues = validate_synthesis_result(prompt, scene_index=2, character_presence=[])
        assert "broken_join" in _check_names(issues)

    def test_trailing_truncation_blocked(self) -> None:
        prompt = "A silhouette on a ridge, sunlight pouring in, the"
        issues = validate_synthesis_result(prompt, scene_index=3, character_presence=[])
        assert "trailing_truncation" in _check_names(issues)

    def test_leading_orphan_blocked(self) -> None:
        prompt = "A Standing figure on a cliff, watching the horizon, 16:9 aspect ratio."
        issues = validate_synthesis_result(prompt, scene_index=4, character_presence=[])
        assert "leading_orphan" in _check_names(issues)

    def test_mid_sentence_splice_blocked(self) -> None:
        prompt = "Looking at a In the foreground, the rock face rises steeply, 16:9 aspect ratio."
        issues = validate_synthesis_result(prompt, scene_index=5, character_presence=[])
        assert "mid_sentence_splice" in _check_names(issues)

    def test_clean_prompt_no_integrity_issues(self) -> None:
        prompt = (
            "A tiny ant crawls across a granite rock towards a Himalayan peak. "
            "Photorealistic environment, illustrated ant, 16:9 aspect ratio."
        )
        issues = validate_synthesis_result(prompt, scene_index=6, character_presence=["ant"])
        integrity_checks = {
            "empty_prompt", "broken_join", "trailing_truncation",
            "leading_orphan", "mid_sentence_splice", "readable_text",
        }
        found = {i.check for i in issues} & integrity_checks
        assert not found, f"Unexpected integrity issues on clean prompt: {found}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. COMPOSITOR TEXT — readable text rendered as image content
# ─────────────────────────────────────────────────────────────────────────────

class TestCompositorText:

    def _check_readable(self, prompt: str) -> bool:
        issues = validate_synthesis_result(
            prompt + " 16:9 aspect ratio.", scene_index=1, character_presence=[]
        )
        return "readable_text" in _check_names(issues)

    def test_word_appears_single_quotes(self) -> None:
        """Scene 8: 'The word 'Tapas' appears in bold, Sanskrit-style script'"""
        prompt = (
            "The word 'Tapas' appears in bold, Sanskrit-style script across the sky, "
            "glowing faintly. The environment is photorealistic."
        )
        assert self._check_readable(prompt)

    def test_word_appears_no_quotes(self) -> None:
        prompt = "The word Dridhabhumih appears above the ant, glowing faintly."
        assert self._check_readable(prompt)

    def test_title_graphic_appears(self) -> None:
        """Scene 6: title graphic 'Greatness is never built overnight' appears"""
        prompt = (
            "The title graphic 'Greatness is never built overnight' appears in a "
            "simple, elegant font at the center of the frame."
        )
        assert self._check_readable(prompt)

    def test_title_graphic_pops_up(self) -> None:
        prompt = "A host speaks to camera while the title graphic pops up in the background."
        assert self._check_readable(prompt)

    def test_in_devanagari_script(self) -> None:
        """Scene 13: 'rendered in flowing Devanagari script'"""
        prompt = (
            "The Sanskrit sutra is rendered in flowing Devanagari script, "
            "illuminated with a soft inner light."
        )
        assert self._check_readable(prompt)

    def test_appears_in_devanagari_script(self) -> None:
        prompt = "The sutra appears in Devanagari script across the stone face."
        assert self._check_readable(prompt)

    def test_in_bold_sanskrit_style_lettering(self) -> None:
        """Scene 17: 'in bold, Sanskrit-style lettering'"""
        prompt = "The word Dridhabhumih appears in bold, Sanskrit-style lettering above the ant."
        assert self._check_readable(prompt)

    def test_in_sanskrit_style_script(self) -> None:
        prompt = "A mantra glows in Sanskrit-style script across the sky."
        assert self._check_readable(prompt)

    def test_single_line_of_writing_colon(self) -> None:
        """Scene 18: 'a single line of writing: Day 127: ...'"""
        prompt = (
            "A hand turns a journal page, revealing a single line of writing: "
            "'Day 127: 30 minutes of focused learning.'"
        )
        assert self._check_readable(prompt)

    def test_lines_of_text_appear(self) -> None:
        """Scene 13: 'two smaller lines of text appear in English'"""
        prompt = "Lines of text appear in English below the Sanskrit inscription."
        assert self._check_readable(prompt)

    def test_clean_no_readable_text(self) -> None:
        prompt = (
            "A massive stone tablet with deep, abstract chisel marks — not readable text, "
            "only the visual impression of ancient inscription. A flame burns at the base. "
            "Photorealistic environment, no text, no watermark, 16:9 aspect ratio."
        )
        assert not self._check_readable(prompt)

    def test_compositor_readable_text_is_blocking(self) -> None:
        """readable_text must be in _BLOCKING_CHECKS so it triggers repair."""
        from ytfactory.images.prompt_synthesis import _BLOCKING_CHECKS
        assert "readable_text" in _BLOCKING_CHECKS

    def test_validate_prompt_contradictions_check_e(self) -> None:
        """prompt_validator also flags readable text via Check E."""
        prompt = (
            "The word 'Tapas' appears in bold, Sanskrit-style script across the sky. "
            "Photorealistic environment, 16:9 aspect ratio."
        )
        errors = validate_prompt_contradictions(prompt, scene_idx=8)
        assert any("ERROR" in e and "readable text" in e for e in errors), errors


# ─────────────────────────────────────────────────────────────────────────────
# 3. CHARACTER LEAKAGE — recurring animal in non-character or wrong scenes
# ─────────────────────────────────────────────────────────────────────────────

class TestCharacterLeakage:

    def test_ant_in_environment_only_scene_error(self) -> None:
        """F1: environment-only scene (character_presence=[]) with ant in prompt."""
        prompt = (
            "A rugged construction site at golden hour. The ant, a tiny illustrated "
            "silhouette, is barely visible in the foreground soil. "
            "Photorealistic environment, 16:9 aspect ratio."
        )
        issues = validate_scene_prompt_qa(
            prompt, scene_index=11, character_presence=[]
        )
        assert any(i.check == "qa_character_leakage_error" for i in issues), issues

    def test_ant_in_non_ant_scene_warning(self) -> None:
        """F2: character_presence has worker but ant appears in prompt."""
        prompt = (
            "A lone worker lays bricks. The ant, illustrated in ink outline, "
            "crawls across the edge of the foundation. "
            "Photorealistic environment, 16:9 aspect ratio."
        )
        issues = validate_scene_prompt_qa(
            prompt, scene_index=12, character_presence=["worker"]
        )
        assert any(i.check == "qa_unlisted_animal_warning" for i in issues), issues

    def test_ant_in_ant_scene_no_leakage(self) -> None:
        """Ant scene with character_presence=['ant'] must not flag F2."""
        prompt = (
            "A tiny ant crawls across a granite rock towards a Himalayan peak. "
            "Illustrated storybook style, photorealistic environment, 16:9 aspect ratio."
        )
        issues = validate_scene_prompt_qa(
            prompt, scene_index=1, character_presence=["ant"]
        )
        leakage_checks = {"qa_character_leakage_error", "qa_unlisted_animal_warning"}
        found = {i.check for i in issues} & leakage_checks
        assert not found, f"False-positive leakage on ant scene: {found}"

    def test_negated_ant_no_false_positive(self) -> None:
        """'no ant' in environment-only scene should not trigger leakage."""
        prompt = (
            "A vast Himalayan landscape with no ant, no character, only stone and sky. "
            "Photorealistic environment, 16:9 aspect ratio."
        )
        issues = validate_scene_prompt_qa(
            prompt, scene_index=12, character_presence=[]
        )
        assert not any(i.check == "qa_character_leakage_error" for i in issues), issues

    def test_prompt_validator_check_f_environment_only(self) -> None:
        """prompt_validator Check F: character_presence=[] + ant in prompt."""
        prompt = (
            "The ant crawls across the foundation. "
            "Photorealistic environment, 16:9 aspect ratio."
        )
        errors = validate_prompt_contradictions(
            prompt, scene_idx=12, character_presence=[]
        )
        assert any("ERROR" in e and "character_presence=[]" in e for e in errors), errors

    def test_prompt_validator_check_f_with_characters_no_flag(self) -> None:
        """prompt_validator Check F only fires when character_presence=[] is passed."""
        prompt = "The ant crawls across the foundation. 16:9 aspect ratio."
        # If character_presence is None (not provided), Check F must not fire.
        errors = validate_prompt_contradictions(prompt, scene_idx=12, character_presence=None)
        assert not any("character_presence=[]" in e for e in errors), errors

    def test_bird_leakage_in_non_bird_scene(self) -> None:
        """F2 fires for bird as well (not just ant)."""
        prompt = (
            "A worker focuses at a desk. A bird perches on the windowsill, "
            "observing the scene. Photorealistic environment, 16:9 aspect ratio."
        )
        issues = validate_scene_prompt_qa(
            prompt, scene_index=7, character_presence=["worker"]
        )
        assert any(i.check == "qa_unlisted_animal_warning" for i in issues), issues

    def test_character_presence_none_skips_f1(self) -> None:
        """When character_presence is None (metadata absent), F1 must not fire."""
        prompt = (
            "A lone ant crosses the stone. Photorealistic environment, 16:9 aspect ratio."
        )
        issues = validate_scene_prompt_qa(
            prompt, scene_index=5, character_presence=None
        )
        assert not any(i.check == "qa_character_leakage_error" for i in issues), issues


# ─────────────────────────────────────────────────────────────────────────────
# 4. SEMANTIC QA SEPARATION — deterministic vs LLM checks
# ─────────────────────────────────────────────────────────────────────────────

class TestSemanticQASeparation:
    """Verify deterministic checks are in place without requiring an LLM call."""

    def test_hybrid_style_photorealistic_char_error(self) -> None:
        """B1: photorealistic character triggers qa_photo_char_error."""
        prompt = (
            "A photorealistic human figure stands at the summit, "
            "hyper-detailed skin texture. 16:9 aspect ratio."
        )
        issues = validate_scene_prompt_qa(
            prompt, scene_index=3, character_presence=["host"]
        )
        assert any(i.check == "qa_photo_char_error" for i in issues), issues

    def test_cartoon_environment_error(self) -> None:
        """B2: cartoon environment triggers qa_cartoon_env_error."""
        prompt = (
            "A hand-drawn animated background with rolling cartoon hills. "
            "An illustrated ant walks in the foreground. 16:9 aspect ratio."
        )
        issues = validate_scene_prompt_qa(
            prompt, scene_index=4, character_presence=["ant"]
        )
        assert any(i.check == "qa_cartoon_env_error" for i in issues), issues

    def test_compositor_ui_element_error(self) -> None:
        """E: subscribe button in prompt triggers qa_compositor_text_error."""
        prompt = (
            "The scene fades to a clean background with a subscribe button "
            "centered in the frame. 16:9 aspect ratio."
        )
        issues = validate_scene_prompt_qa(
            prompt, scene_index=21, character_presence=[]
        )
        assert any(i.check == "qa_compositor_text_error" for i in issues), issues

    def test_validate_synthesis_result_no_llm_needed(self) -> None:
        """validate_synthesis_result is purely deterministic — no LLM dependency."""
        # If this function raises, it means it unexpectedly tries to call an LLM.
        prompt = (
            "A wide shot of an ancient stone tablet in a dark cavern, "
            "lit by a small flame. Photorealistic, no text, 16:9 aspect ratio."
        )
        issues = validate_synthesis_result(prompt, scene_index=13, character_presence=[])
        # Good prompt — minimal issues expected
        assert isinstance(issues, list)

    def test_validate_scene_prompt_qa_no_llm_needed(self) -> None:
        """validate_scene_prompt_qa is purely deterministic — no LLM dependency."""
        prompt = (
            "A clean photorealistic construction site. "
            "No characters, no text, 16:9 aspect ratio."
        )
        issues = validate_scene_prompt_qa(
            prompt, scene_index=11,
            narration="A lone worker builds a steady routine.",
            character_presence=[],
        )
        assert isinstance(issues, list)

    def test_text_branding_directive_caught_by_synthesis(self) -> None:
        """text_branding (imperative form) is separate from readable_text."""
        prompt = "Show the title text 'Greatness' in the center. 16:9 aspect ratio."
        issues = validate_synthesis_result(prompt, scene_index=6, character_presence=[])
        checks = _check_names(issues)
        # Either text_branding or readable_text must fire (or both)
        assert "text_branding" in checks or "readable_text" in checks, checks

    def test_clean_correct_prompt_passes_all_deterministic_checks(self) -> None:
        """A well-formed prompt with correct metadata passes all deterministic QA."""
        prompt = (
            "A tiny ant, illustrated in hand-painted 2D storybook style with visible "
            "ink outlines, crawls across the weathered surface of a massive granite rock. "
            "The environment is photorealistic: cold, thin air and pale blue sky. "
            "Cinematic wide shot, deep depth of field, 16:9 aspect ratio."
        )
        synthesis_issues = validate_synthesis_result(
            prompt, scene_index=1, character_presence=["ant"]
        )
        qa_issues = validate_scene_prompt_qa(
            prompt, scene_index=1,
            narration="A tiny ant crawls across a massive rock.",
            character_presence=["ant"],
        )
        error_checks = {
            "empty_prompt", "broken_join", "trailing_truncation", "leading_orphan",
            "mid_sentence_splice", "readable_text", "text_branding",
            "qa_photo_char_error", "qa_cartoon_env_error",
            "qa_compositor_text_error", "qa_character_leakage_error",
        }
        all_issues = synthesis_issues + qa_issues
        found_errors = {i.check for i in all_issues} & error_checks
        assert not found_errors, f"Unexpected errors on clean prompt: {found_errors}"
