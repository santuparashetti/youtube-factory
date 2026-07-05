"""Tests for TimingEngine — gap/overlap repair."""

from __future__ import annotations

import pytest

from ytfactory.subtitles.models import SubtitleCue
from ytfactory.subtitles.timing import TimingEngine


def _cue(index: int, start: float, end: float, text: str = "Text") -> SubtitleCue:
    return SubtitleCue(index=index, start=start, end=end, lines=[text])


@pytest.fixture()
def engine() -> TimingEngine:
    return TimingEngine()


class TestEmptyInput:
    def test_empty_list_returns_empty(self, engine):
        result, (overlaps, gaps) = engine.repair([])
        assert result == []
        assert overlaps == 0
        assert gaps == 0


class TestOverlapRepair:
    def test_overlap_corrected(self, engine):
        cues = [
            _cue(1, 0.0, 3.0),
            _cue(2, 2.5, 5.0),  # overlaps with cue 1
        ]
        result, (overlaps, _) = engine.repair(cues)
        assert overlaps >= 1
        # First cue end should be before second cue start
        assert result[0].end <= result[1].start + 0.001

    def test_no_overlap_unchanged(self, engine):
        cues = [
            _cue(1, 0.0, 2.0),
            _cue(2, 2.5, 5.0),
        ]
        result, (overlaps, _) = engine.repair(cues)
        assert overlaps == 0


class TestGapRepair:
    def test_tiny_gap_closed(self, engine):
        cues = [
            _cue(1, 0.0, 2.0),
            _cue(2, 2.1, 5.0),  # 0.1s gap — should be closed
        ]
        result, (_, gaps) = engine.repair(cues)
        assert gaps >= 1
        # The first cue end should be extended to close the gap
        assert result[0].end == pytest.approx(2.1, abs=0.01)

    def test_large_gap_preserved(self, engine):
        cues = [
            _cue(1, 0.0, 2.0),
            _cue(2, 5.0, 8.0),  # 3s gap — intentional pause
        ]
        result, (_, gaps) = engine.repair(cues)
        # Gap should not be closed
        assert result[1].start == pytest.approx(5.0)


class TestDurationClamping:
    def test_short_cue_extended(self, engine):
        cues = [_cue(1, 0.0, 0.2)]  # only 0.2s — below minimum
        result, _ = engine.repair(cues)
        assert result[0].duration >= 0.5

    def test_long_cue_truncated(self, engine):
        cues = [_cue(1, 0.0, 10.0)]  # 10s — above maximum
        result, _ = engine.repair(cues)
        assert result[0].duration <= 7.0 + 0.001

    def test_normal_duration_preserved(self, engine):
        cues = [_cue(1, 0.0, 3.5)]
        result, _ = engine.repair(cues)
        assert result[0].duration == pytest.approx(3.5)


class TestRenumbering:
    def test_indices_sequential_after_repair(self, engine):
        cues = [
            _cue(5, 0.0, 2.0),
            _cue(10, 3.0, 5.0),
            _cue(15, 6.0, 8.0),
        ]
        result, _ = engine.repair(cues)
        assert [c.index for c in result] == [1, 2, 3]

    def test_single_cue_indexed_one(self, engine):
        cues = [_cue(42, 0.0, 2.0)]
        result, _ = engine.repair(cues)
        assert result[0].index == 1
