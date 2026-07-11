"""Tests for SpeechFormatter — including regression for double-period clipping bug."""

from __future__ import annotations

import pytest

from video_core.providers.tts.formatter import SpeechFormatter


@pytest.fixture()
def fmt() -> SpeechFormatter:
    return SpeechFormatter()


# ── Regression: double-period clipping bug ────────────────────────────────────


class TestDoublePeriodBug:
    """
    Root cause: SpeechOptimizer outputs phrases with \\n\\n separators.
    Old _prepare_text() did re.sub(r"\\n+", ". ", text) — when a phrase
    already ended with ".", this produced ".." which Edge TTS handled
    inconsistently, clipping the first word of the next phrase.
    """

    def test_phrase_ending_with_period_then_paragraph_break(self, fmt):
        text = "In the beginning there was light.\n\nAll was still."
        result = fmt.format(text, style="spiritual")
        assert ".." not in result, f"Double period found in: {result!r}"
        assert result.endswith("All was still.") or "All was still" in result

    def test_phrase_ending_with_period_multiple_breaks(self, fmt):
        text = "First phrase ends here.\n\n\nSecond phrase begins."
        result = fmt.format(text, style="spiritual")
        assert ".." not in result, f"Double period found in: {result!r}"

    def test_phrase_without_trailing_period(self, fmt):
        text = "A phrase without period\n\nNext phrase here."
        result = fmt.format(text, style="spiritual")
        assert ".." not in result

    def test_no_double_period_after_ellipsis(self, fmt):
        # Ellipsis followed by newline should not produce ".. " or "..."
        text = "Pause here...\n\nAnd continue."
        result = fmt.format(text, style="spiritual")
        assert ".." not in result

    def test_normalize_punctuation_catches_residual_double_period(self, fmt):
        result = fmt.normalize_punctuation("word.. next word.")
        assert ".." not in result
        assert result == "word. next word."

    def test_normalize_punctuation_catches_triple_period(self, fmt):
        result = fmt.normalize_punctuation("word... next.")
        assert "..." not in result


# ── Paragraph normalization ───────────────────────────────────────────────────


class TestParagraphNormalization:
    def test_spiritual_style_converts_newlines_to_period_space(self, fmt):
        text = "Line one\n\nLine two"
        result = fmt.format(text, style="spiritual")
        assert "\n" not in result
        assert "Line one" in result
        assert "Line two" in result

    def test_non_spiritual_style_collapses_double_newlines(self, fmt):
        text = "Para one\n\nPara two"
        result = fmt.format(text, style=None)
        assert "\n" not in result

    def test_single_newline_removed(self, fmt):
        text = "Line one\nLine two"
        result = fmt.format(text, style="spiritual")
        assert "\n" not in result

    def test_empty_text_returns_empty(self, fmt):
        assert fmt.format("", style=None) == ""

    def test_whitespace_only_returns_empty(self, fmt):
        result = fmt.format("   \n  \n  ", style=None)
        assert result.strip() == ""


# ── Markdown stripping ────────────────────────────────────────────────────────


class TestMarkdownStripping:
    def test_strips_bold(self, fmt):
        result = fmt.strip_markdown("**Bold text** here")
        assert "**" not in result
        assert "Bold text" in result

    def test_strips_italic(self, fmt):
        result = fmt.strip_markdown("*italic* and _also italic_")
        assert "*" not in result
        assert "_" not in result

    def test_strips_headings(self, fmt):
        result = fmt.strip_markdown("# Big heading\n## Sub")
        assert "#" not in result
        assert "Big heading" in result

    def test_strips_links(self, fmt):
        result = fmt.strip_markdown("[Click here](https://example.com)")
        assert "[" not in result
        assert "]" not in result
        # Link text preserved
        assert "Click here" in result

    def test_strips_bullet_markers(self, fmt):
        result = fmt.strip_markdown("- item one\n- item two")
        assert "- " not in result


# ── Unicode normalization ─────────────────────────────────────────────────────


class TestUnicodeNormalization:
    def test_curly_double_quotes_normalized(self, fmt):
        result = fmt.normalize_unicode("“hello”")
        assert "“" not in result
        assert "”" not in result
        assert "hello" in result

    def test_curly_single_quotes_normalized(self, fmt):
        result = fmt.normalize_unicode("‘world’")
        assert "‘" not in result
        assert "’" not in result

    def test_em_dash_normalized(self, fmt):
        result = fmt.normalize_unicode("one—two")
        assert "—" not in result

    def test_en_dash_normalized(self, fmt):
        result = fmt.normalize_unicode("1–2")
        assert "–" not in result

    def test_ellipsis_char_normalized(self, fmt):
        result = fmt.normalize_unicode("wait…")
        assert "…" not in result


# ── Whitespace collapsing ─────────────────────────────────────────────────────


class TestWhitespaceCollapsing:
    def test_multiple_spaces_collapsed(self, fmt):
        result = fmt.collapse_whitespace("word   word")
        assert "   " not in result
        assert "word word" in result

    def test_leading_trailing_stripped(self, fmt):
        result = fmt.collapse_whitespace("  text  ")
        assert result == "text"

    def test_tab_normalized(self, fmt):
        result = fmt.collapse_whitespace("word\tword")
        assert "\t" not in result


# ── Dialogue handling ─────────────────────────────────────────────────────────


class TestDialogueHandling:
    def test_quoted_dialogue_preserved(self, fmt):
        text = 'He said "come here" and left.'
        result = fmt.format(text, style=None)
        assert "come here" in result

    def test_nested_quotes_not_mangled(self, fmt):
        text = "She whispered 'wait' quietly."
        result = fmt.format(text, style=None)
        assert "wait" in result


# ── Full pipeline smoke test ──────────────────────────────────────────────────


class TestFullPipeline:
    def test_realistic_spiritual_scene(self, fmt):
        narration = (
            "**In ancient times**, humanity looked to the stars.\n\n"
            "They found meaning in their journey.\n\n"
            "The “light within” guided them home."
        )
        result = fmt.format(narration, style="spiritual")
        assert "**" not in result
        assert "\n" not in result
        assert ".." not in result
        assert "light within" in result
        assert "humanity looked to the stars" in result

    def test_realistic_documentary_scene(self, fmt):
        narration = (
            "## Chapter One\n\n"
            "The discovery changed everything.\n"
            "Scientists were *shocked* by the findings."
        )
        result = fmt.format(narration, style=None)
        assert "#" not in result
        assert "*" not in result
        assert "\n" not in result
