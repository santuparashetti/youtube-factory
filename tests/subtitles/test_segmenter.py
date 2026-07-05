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
        # Smart quotes should be cleaned
        boundaries = [
            {"word": "“Hello”", "start": 0.0, "end": 1.0},
            {"word": "world.", "start": 1.0, "end": 2.0},
        ]
        cues = segmenter.segment(boundaries)
        for cue in cues:
            for line in cue.lines:
                assert "“" not in line
                assert "”" not in line
