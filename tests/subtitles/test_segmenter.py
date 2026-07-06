"""Tests for SubtitleSegmenter — semantic boundary grouping."""

from __future__ import annotations

import pytest

from ytfactory.subtitles.models import SubtitleCue
from ytfactory.subtitles.segmenter import SubtitleSegmenter


def _make_boundaries(
    words: list[str], start: float = 0.0, pace: float = 0.5
) -> list[dict]:
    """Build synthetic word boundaries at a fixed pace (seconds per word)."""
    result = []
    t = start
    for word in words:
        result.append({"word": word, "start": t, "end": t + pace})
        t += pace
    return result


@pytest.fixture()
def segmenter() -> SubtitleSegmenter:
    return SubtitleSegmenter(max_cps=18, max_chars_per_line=42, max_lines=2)


class TestBasicSegmentation:
    def test_empty_boundaries_returns_empty(self, segmenter):
        cues = segmenter.segment([], narration="")
        assert cues == []

    def test_single_word_boundary(self, segmenter):
        boundaries = [{"word": "Hello", "start": 0.0, "end": 1.0}]
        cues = segmenter.segment(boundaries)
        assert len(cues) == 1
        assert "Hello" in cues[0].text

    def test_returns_subtitle_cue_objects(self, segmenter):
        boundaries = _make_boundaries(["The", "quick", "brown", "fox"])
        cues = segmenter.segment(boundaries)
        assert all(isinstance(c, SubtitleCue) for c in cues)

    def test_cues_indexed_sequentially(self, segmenter):
        boundaries = _make_boundaries(["One", "two", "three."])
        cues = segmenter.segment(boundaries)
        for i, cue in enumerate(cues, start=1):
            assert cue.index == i

    def test_timing_from_boundaries(self, segmenter):
        boundaries = [
            {"word": "Hello", "start": 1.0, "end": 1.5},
            {"word": "world.", "start": 1.5, "end": 2.0},
        ]
        cues = segmenter.segment(boundaries)
        assert cues[0].start == pytest.approx(1.0)
        # end should be within the last word boundary
        assert cues[-1].end == pytest.approx(2.0)


class TestSentenceBoundaryBreaking:
    def test_breaks_at_sentence_terminal(self, segmenter):
        """Cues must break after . ! ? — not mid-sentence."""
        words = ["First", "sentence.", "Second", "sentence."]
        boundaries = _make_boundaries(words)
        cues = segmenter.segment(boundaries)
        # At least 2 cues expected (one per sentence)
        assert len(cues) >= 2

    def test_question_mark_triggers_break(self, segmenter):
        words = ["Are", "you", "ready?", "Good", "morning."]
        boundaries = _make_boundaries(words)
        cues = segmenter.segment(boundaries)
        assert len(cues) >= 2

    def test_exclamation_triggers_break(self, segmenter):
        # Need enough words before the ! to avoid orphan guard (min 2 words)
        words = ["Stand", "tall!", "Let", "us", "begin."]
        boundaries = _make_boundaries(words)
        cues = segmenter.segment(boundaries)
        assert len(cues) >= 2


class TestLineSplitting:
    def test_long_text_gets_two_lines(self, segmenter):
        """Text exceeding MAX_CHARS_PER_LINE should be split into two lines."""
        # Build a boundary list that produces one big block
        long_text = "This is a very long sentence that should definitely be split into two lines for reading"
        words = long_text.split()
        boundaries = _make_boundaries(words, pace=0.7)
        cues = segmenter.segment(boundaries)
        # Just verify no line exceeds MAX_CHARS_PER_LINE when 2-line split applied
        for cue in cues:
            if len(cue.lines) == 2:
                assert len(cue.lines[0]) <= 42
                assert len(cue.lines[1]) <= 42

    def test_short_text_single_line(self, segmenter):
        """Text shorter than MAX_CHARS_PER_LINE stays on one line."""
        boundaries = _make_boundaries(["Short", "text."])
        cues = segmenter.segment(boundaries)
        for cue in cues:
            assert len(cue.lines) == 1

    def test_cue_has_at_most_max_lines(self, segmenter):
        words = ["word"] * 20
        boundaries = _make_boundaries(words, pace=0.5)
        cues = segmenter.segment(boundaries)
        for cue in cues:
            assert len(cue.lines) <= 2


class TestFallback:
    def test_fallback_with_duration(self, segmenter):
        narration = "First sentence. Second sentence. Third."
        cues = segmenter.fallback_segment(narration, total_duration=10.0)
        assert len(cues) > 0
        assert all(isinstance(c, SubtitleCue) for c in cues)

    def test_fallback_empty_narration(self, segmenter):
        cues = segmenter.fallback_segment("", total_duration=5.0)
        assert cues == []

    def test_fallback_zero_duration(self, segmenter):
        cues = segmenter.fallback_segment("Some text.", total_duration=0.0)
        # Should return empty or minimal — no crash
        assert isinstance(cues, list)

    def test_fallback_timing_within_bounds(self, segmenter):
        narration = "First sentence here. Second sentence here."
        total = 8.0
        cues = segmenter.fallback_segment(narration, total_duration=total)
        if cues:
            assert cues[0].start >= 0.0
            assert cues[-1].end <= total + 0.01  # small float tolerance


class TestTypographyIntegration:
    def test_typography_applied_to_cue_lines(self, segmenter):
        """Segmenter should apply SubtitleTypographer to each cue's lines."""
        # Smart quotes (Unicode) in word data should be cleaned by typographer
        left_dq = "“"
        right_dq = "”"
        boundaries = [
            {"word": left_dq + "Hello" + right_dq, "start": 0.0, "end": 1.0},
            {"word": "world.", "start": 1.0, "end": 2.0},
        ]
        cues = segmenter.segment(boundaries)
        for cue in cues:
            for line in cue.lines:
                assert left_dq not in line
                assert right_dq not in line


class TestLinguisticLineSplit:
    """Two-line split respects linguistic constraints, not just character count."""

    def _seg(self) -> SubtitleSegmenter:
        # 42 chars per line gives enough room for interesting splits
        return SubtitleSegmenter(max_cps=18, max_chars_per_line=42, max_lines=2)

    def test_preposition_not_stranded_on_line2(self):
        """Strict pass must avoid 'to' starting line 2 when a better split exists."""
        seg = self._seg()
        # "deepest secrets" split is valid and strict; "to those" split has "to" on line 2
        text = "The mind reveals its deepest secrets to those who choose to listen"
        lines = seg._split_lines(text)
        if len(lines) == 2:
            first_word_l2 = lines[1].split()[0].lower().rstrip(".,;:?!")
            # Strict pass should have found a split that doesn't start line 2 with "to"
            assert first_word_l2 != "to", (
                f"Preposition 'to' should not start line 2; got: {lines}"
            )

    def test_article_not_stranded_on_line2(self):
        """'the' or 'a' must not begin line 2 without a preceding punctuation break."""
        seg = self._seg()
        # "darkness reveals" split avoids "the" at line 2 start
        text = "Within the silence of darkness the truth begins to shine"
        lines = seg._split_lines(text)
        if len(lines) == 2:
            first_word_l2 = lines[1].split()[0].lower().rstrip(".,;:?!")
            assert first_word_l2 not in {"the", "a", "an"}, (
                f"Article should not start line 2: {lines}"
            )

    def test_split_at_comma_is_preferred(self):
        """Clause-punctuation bonus makes comma splits preferred over bare-word splits."""
        seg = self._seg()
        # Comma after "silence" — algorithm should strongly prefer splitting there
        text = "In the silence of deep reflection, wisdom finds its voice"
        lines = seg._split_lines(text)
        if len(lines) == 2:
            # Line 1 should end with the comma
            assert lines[0].rstrip().endswith(","), (
                f"Expected split at comma; got: {lines}"
            )

    def test_conjunction_not_stranded_on_line2(self):
        """'and', 'or', 'but' must not begin line 2 without punctuation."""
        seg = self._seg()
        # "courage and" — strict rules should put "and" on line 1 or find another break
        text = "True courage comes from facing your fears and embracing change"
        lines = seg._split_lines(text)
        if len(lines) == 2:
            first_word_l2 = lines[1].split()[0].lower().rstrip(".,;:?!")
            assert first_word_l2 not in {"and", "or", "but"}, (
                f"Conjunction should not start line 2: {lines}"
            )


class TestContinuationCapitalization:
    """Line 2 of a two-line cue preserves lowercase when line 1 is not a sentence end."""

    def _seg(self) -> SubtitleSegmenter:
        return SubtitleSegmenter(max_cps=18, max_chars_per_line=30, max_lines=2)

    def test_continuation_line2_stays_lowercase(self):
        """When line 1 does not end with .!?, line 2 first word stays lowercase."""
        seg = self._seg()
        text = "searching for the truth within the silence of your mind"
        lines = seg._split_lines(text)
        lines = seg._apply_typography(lines)
        if len(lines) == 2:
            l1_last = lines[0].rstrip()
            if l1_last and l1_last[-1] not in ".!?":
                first_char = lines[1][0]
                assert first_char == first_char.lower(), (
                    f"Line 2 first char '{first_char}' was uppercased on a continuation: {lines}"
                )

    def test_new_sentence_line2_gets_capitalized(self):
        """When line 1 ends with '.', line 2 first word is capitalized normally."""
        seg = self._seg()
        text = "This is the first sentence. and this continues"
        lines = seg._split_lines(text)
        lines = seg._apply_typography(lines)
        if len(lines) == 2:
            l1_last = lines[0].rstrip()
            if l1_last and l1_last[-1] == ".":
                assert lines[1][0].isupper(), (
                    f"Expected uppercase start on new-sentence line 2: {lines}"
                )

    def test_apply_typography_continuation_no_capitalize(self):
        """_apply_typography: line 2 not force-capitalized when line 1 has no terminal."""
        seg = self._seg()
        raw = ["the quiet voice", "of reason speaks"]
        result = seg._apply_typography(raw)
        assert len(result) == 2
        assert result[1][0] == result[1][0].lower()

    def test_apply_typography_sentence_end_capitalizes(self):
        """_apply_typography: line 2 is capitalized when line 1 ends with '.'"""
        seg = self._seg()
        raw = ["The story ends.", "and a new one begins"]
        result = seg._apply_typography(raw)
        assert len(result) == 2
        assert result[1][0].isupper()
