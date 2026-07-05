"""Tests for SRTWriter — SRT serialization."""

from __future__ import annotations

import pytest

from ytfactory.subtitles.models import SubtitleCue, SubtitleFormat
from ytfactory.subtitles.writer import SRTWriter, get_writer


def _cue(index: int, start: float, end: float, *lines: str) -> SubtitleCue:
    return SubtitleCue(index=index, start=start, end=end, lines=list(lines))


@pytest.fixture()
def writer() -> SRTWriter:
    return SRTWriter()


class TestSRTFormatting:
    def test_empty_list_returns_empty_string(self, writer):
        assert writer.write([]) == ""

    def test_single_cue_format(self, writer):
        cue = _cue(1, 0.0, 2.5, "Hello world")
        srt = writer.write([cue])
        assert "1\n" in srt
        assert "00:00:00,000 --> 00:00:02,500" in srt
        assert "Hello world" in srt

    def test_two_line_cue(self, writer):
        cue = _cue(1, 0.0, 3.0, "Line one", "Line two")
        srt = writer.write([cue])
        assert "Line one\nLine two" in srt

    def test_multiple_cues_separated_by_blank_line(self, writer):
        cues = [
            _cue(1, 0.0, 2.0, "First"),
            _cue(2, 2.5, 4.5, "Second"),
        ]
        srt = writer.write(cues)
        assert "\n\n" in srt
        assert "1\n" in srt
        assert "2\n" in srt

    def test_timestamp_format_hh_mm_ss_mmm(self, writer):
        cue = _cue(1, 65.5, 68.0, "Test")
        srt = writer.write([cue])
        # 65.5s = 00:01:05,500
        assert "00:01:05,500" in srt

    def test_timestamp_handles_hour_rollover(self, writer):
        cue = _cue(1, 3661.0, 3663.0, "Test")
        srt = writer.write([cue])
        # 3661s = 01:01:01,000
        assert "01:01:01,000" in srt

    def test_milliseconds_clamped(self, writer):
        cue = _cue(1, 0.9999, 2.9999, "Test")
        srt = writer.write([cue])
        # Should not produce ",1000" — must clamp to 999
        assert ",1000" not in srt

    def test_empty_lines_skipped(self, writer):
        cue = _cue(1, 0.0, 2.0, "Valid", "", "   ")
        srt = writer.write([cue])
        # Only the valid line should appear after the timestamp line
        assert "Valid" in srt
        assert "   " not in srt


class TestGetWriter:
    def test_srt_format_returns_srt_writer(self):
        w = get_writer(SubtitleFormat.SRT)
        assert isinstance(w, SRTWriter)

    def test_srt_string_accepted(self):
        w = get_writer("srt")
        assert isinstance(w, SRTWriter)

    def test_unsupported_format_raises(self):
        with pytest.raises((ValueError, Exception)):
            get_writer("webvtt")
