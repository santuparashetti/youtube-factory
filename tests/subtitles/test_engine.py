"""
Tests for SubtitleEngine — integration tests for the full pipeline.
"""

from __future__ import annotations

import pytest

from ytfactory.subtitles.engine import SubtitleEngine
from ytfactory.subtitles.models import SubtitleReport


def _make_boundaries(words: list[str], pace: float = 0.5) -> list[dict]:
    """Build synthetic word boundaries at a fixed pace."""
    result = []
    t = 0.0
    for word in words:
        result.append({"word": word, "start": t, "end": t + pace})
        t += pace
    return result


@pytest.fixture()
def engine() -> SubtitleEngine:
    return SubtitleEngine(
        max_cps=18.0,
        max_chars_per_line=42,
        max_lines=2,
        debug=False,
        validate=True,
    )


class TestBuildReturnsString:
    def test_basic_build(self, engine, tmp_path):
        boundaries = _make_boundaries(["Hello", "world."])
        result = engine.build(
            boundaries=boundaries,
            narration="Hello world.",
            scene_index=1,
            project_id="test-project",
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_boundaries_fallback(self, engine, tmp_path):
        result = engine.build(
            boundaries=[],
            narration="Some narration text here.",
            scene_index=1,
            project_id="test-project",
            total_duration=5.0,
        )
        assert isinstance(result, str)

    def test_empty_narration_no_crash(self, engine, tmp_path):
        result = engine.build(
            boundaries=[],
            narration="",
            scene_index=1,
            project_id="test-project",
            total_duration=5.0,
        )
        assert isinstance(result, str)


class TestSRTOutput:
    def test_output_is_valid_srt(self, engine):
        words = ["The", "ancient", "mountain", "stands", "eternal."]
        boundaries = _make_boundaries(words)
        srt = engine.build(
            boundaries=boundaries,
            narration=" ".join(words),
            scene_index=1,
            project_id="test-project",
        )
        lines = srt.strip().split("\n")
        # First line should be a number (cue index)
        assert lines[0].strip().isdigit()
        # Second line should contain " --> "
        assert " --> " in lines[1]

    def test_no_double_period_in_output(self, engine):
        words = ["Sentence", "one.", "Sentence", "two."]
        boundaries = _make_boundaries(words)
        srt = engine.build(
            boundaries=boundaries,
            narration=" ".join(words),
            scene_index=1,
            project_id="test-project",
        )
        assert ".." not in srt

    def test_no_malformed_punctuation(self, engine):
        words = ["Test", "comma,.period"]
        boundaries = _make_boundaries(words)
        srt = engine.build(
            boundaries=boundaries,
            narration=" ".join(words),
            scene_index=1,
            project_id="test-project",
        )
        assert ",." not in srt


class TestBuildReport:
    def test_returns_tuple(self, engine):
        words = ["Hello", "world."]
        boundaries = _make_boundaries(words)
        result = engine.build_report(
            boundaries=boundaries,
            narration="Hello world.",
            scene_index=2,
            project_id="test-project",
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_report_type(self, engine):
        words = ["Hello", "world."]
        boundaries = _make_boundaries(words)
        srt, report = engine.build_report(
            boundaries=boundaries,
            narration="Hello world.",
            scene_index=3,
            project_id="test-project",
        )
        assert isinstance(report, SubtitleReport)
        assert report.scene_index == 3

    def test_report_cue_count_nonzero(self, engine):
        words = ["The", "sky", "is", "blue."]
        boundaries = _make_boundaries(words)
        _, report = engine.build_report(
            boundaries=boundaries,
            narration=" ".join(words),
            scene_index=1,
            project_id="test-project",
        )
        assert report.cue_count > 0

    def test_report_dict_serializable(self, engine):
        words = ["Hello", "world."]
        boundaries = _make_boundaries(words)
        _, report = engine.build_report(
            boundaries=boundaries,
            narration="Hello world.",
            scene_index=1,
            project_id="test-project",
        )
        d = report.to_dict()
        import json

        json.dumps(d)  # no crash = serializable


class TestFromSettings:
    def test_from_settings_constructs(self):
        class FakeSettings:
            subtitle_debug = False
            subtitle_validate = True
            subtitle_max_cps = 18.0
            subtitle_max_chars_per_line = 42
            subtitle_max_lines = 2
            subtitle_format = "srt"

        engine = SubtitleEngine.from_settings(FakeSettings())
        assert isinstance(engine, SubtitleEngine)

    def test_from_settings_defaults_fallback(self):
        class MinimalSettings:
            pass  # no subtitle_* attrs

        engine = SubtitleEngine.from_settings(MinimalSettings())
        assert isinstance(engine, SubtitleEngine)


class TestRealisticDocumentaryScene:
    """End-to-end smoke test with realistic documentary narration."""

    NARRATION = (
        "In the heart of the ancient forest, where light barely pierces the canopy, "
        "a civilization once thrived. They built temples that reached toward the heavens. "
        "They mapped the stars with breathtaking precision. "
        "And then, one day, they vanished — leaving only silence."
    )

    def test_documentary_scene_produces_clean_subtitles(self, engine):
        words = self.NARRATION.split()
        boundaries = _make_boundaries(words, pace=0.42)
        srt = engine.build(
            boundaries=boundaries,
            narration=self.NARRATION,
            scene_index=1,
            project_id="test-project",
        )
        assert isinstance(srt, str)
        assert len(srt) > 0
        assert " --> " in srt
        # No double periods
        assert ".." not in srt
        # No malformed punctuation
        assert ",." not in srt
        assert "?." not in srt

    def test_line_lengths_within_limit(self, engine):
        words = self.NARRATION.split()
        boundaries = _make_boundaries(words, pace=0.42)
        srt = engine.build(
            boundaries=boundaries,
            narration=self.NARRATION,
            scene_index=1,
            project_id="test-project",
        )
        # Extract subtitle text lines (skip index and timestamp lines)
        for line in srt.split("\n"):
            if line.strip() and " --> " not in line and not line.strip().isdigit():
                assert len(line) <= 42, f"Line too long: {line!r}"
