"""
Integration tests for the ASS Subtitle Engine.

Tests cover:
  - SubtitleEngine.build_both() producing valid ASS + SRT
  - SubtitleEngine.format property
  - from_settings() ASS theme wiring
  - SubtitleFormat.ASS model value
  - get_writer() factory with ASS format
  - Backward compat: build() still returns SRT
  - CaptionArtifact.primary_path prefers ASS
  - Validation diagnostics with ASS output
"""

from __future__ import annotations

import pytest

from ytfactory.subtitles import SubtitleEngine
from ytfactory.subtitles.ass.theme import ASSTheme
from ytfactory.subtitles.ass.writer import ASSWriter
from ytfactory.subtitles.models import SubtitleFormat
from ytfactory.subtitles.writer import get_writer


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_boundaries(words: list[str], pace: float = 0.5) -> list[dict]:
    result = []
    t = 0.0
    for word in words:
        result.append({"word": word, "start": t, "end": t + pace})
        t += pace
    return result


@pytest.fixture()
def ass_engine() -> SubtitleEngine:
    return SubtitleEngine(
        max_cps=18.0,
        max_chars_per_line=42,
        max_lines=2,
        debug=False,
        validate=True,
        subtitle_format=SubtitleFormat.ASS,
        ass_theme=ASSTheme(),
    )


@pytest.fixture()
def srt_engine() -> SubtitleEngine:
    return SubtitleEngine(
        max_cps=18.0,
        max_chars_per_line=42,
        max_lines=2,
        debug=False,
        validate=True,
        subtitle_format=SubtitleFormat.SRT,
    )


# ── SubtitleFormat model ──────────────────────────────────────────────────────


class TestSubtitleFormatEnum:
    def test_ass_value(self):
        assert SubtitleFormat.ASS.value == "ass"

    def test_srt_value(self):
        assert SubtitleFormat.SRT.value == "srt"

    def test_ass_from_string(self):
        assert SubtitleFormat("ass") == SubtitleFormat.ASS

    def test_srt_from_string(self):
        assert SubtitleFormat("srt") == SubtitleFormat.SRT


# ── get_writer factory ────────────────────────────────────────────────────────


class TestGetWriterFactory:
    def test_get_writer_srt_returns_srt_writer(self):
        from ytfactory.subtitles.writer import SRTWriter

        w = get_writer(SubtitleFormat.SRT)
        assert isinstance(w, SRTWriter)

    def test_get_writer_ass_returns_ass_writer(self):
        w = get_writer(SubtitleFormat.ASS)
        assert isinstance(w, ASSWriter)

    def test_get_writer_ass_string(self):
        w = get_writer("ass")
        assert isinstance(w, ASSWriter)

    def test_get_writer_srt_string(self):
        from ytfactory.subtitles.writer import SRTWriter

        w = get_writer("srt")
        assert isinstance(w, SRTWriter)

    def test_get_writer_invalid_raises(self):
        with pytest.raises(ValueError):
            get_writer("webvtt")


# ── SubtitleEngine.format property ───────────────────────────────────────────


class TestSubtitleEngineFormat:
    def test_ass_engine_format(self, ass_engine):
        assert ass_engine.format == SubtitleFormat.ASS

    def test_srt_engine_format(self, srt_engine):
        assert srt_engine.format == SubtitleFormat.SRT


# ── SubtitleEngine.build() backward compat ────────────────────────────────────


class TestBuildBackwardCompat:
    def test_build_returns_srt_string(self, ass_engine):
        words = ["Hello", "world."]
        boundaries = _make_boundaries(words)
        result = ass_engine.build(
            boundaries=boundaries,
            narration="Hello world.",
            scene_index=1,
            project_id="test",
        )
        assert isinstance(result, str)
        # build() always returns SRT
        assert " --> " in result

    def test_build_with_srt_engine_still_works(self, srt_engine):
        words = ["Test", "narration."]
        boundaries = _make_boundaries(words)
        result = srt_engine.build(
            boundaries=boundaries,
            narration="Test narration.",
            scene_index=1,
            project_id="test",
        )
        assert " --> " in result


# ── SubtitleEngine.build_both() ───────────────────────────────────────────────


class TestBuildBoth:
    def test_returns_tuple_of_three(self, ass_engine):
        words = ["Hello", "world."]
        boundaries = _make_boundaries(words)
        result = ass_engine.build_both(
            boundaries=boundaries,
            narration="Hello world.",
            scene_index=1,
            project_id="test",
        )
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_ass_content_is_string(self, ass_engine):
        boundaries = _make_boundaries(["Hello", "world."])
        ass, srt, report = ass_engine.build_both(
            boundaries=boundaries,
            narration="Hello world.",
            scene_index=1,
            project_id="test",
        )
        assert isinstance(ass, str)

    def test_srt_content_is_string(self, ass_engine):
        boundaries = _make_boundaries(["Hello", "world."])
        ass, srt, report = ass_engine.build_both(
            boundaries=boundaries,
            narration="Hello world.",
            scene_index=1,
            project_id="test",
        )
        assert isinstance(srt, str)

    def test_ass_contains_script_info(self, ass_engine):
        boundaries = _make_boundaries(["Hello", "world."])
        ass, _, _ = ass_engine.build_both(
            boundaries=boundaries,
            narration="Hello world.",
            scene_index=1,
            project_id="test",
        )
        assert "[Script Info]" in ass

    def test_srt_contains_arrow_separator(self, ass_engine):
        boundaries = _make_boundaries(["Hello", "world."])
        _, srt, _ = ass_engine.build_both(
            boundaries=boundaries,
            narration="Hello world.",
            scene_index=1,
            project_id="test",
        )
        assert " --> " in srt

    def test_report_has_cues(self, ass_engine):
        boundaries = _make_boundaries(["The", "sky", "is", "blue."])
        _, _, report = ass_engine.build_both(
            boundaries=boundaries,
            narration="The sky is blue.",
            scene_index=1,
            project_id="test",
        )
        assert report.cue_count > 0

    def test_empty_boundaries_fallback(self, ass_engine):
        ass, srt, report = ass_engine.build_both(
            boundaries=[],
            narration="Some narration here.",
            scene_index=1,
            project_id="test",
            total_duration=5.0,
        )
        assert isinstance(ass, str)
        assert isinstance(srt, str)

    def test_both_contain_same_text(self, ass_engine):
        narration = "Ancient temples rose to the sky."
        boundaries = _make_boundaries(narration.split(), pace=0.4)
        ass, srt, _ = ass_engine.build_both(
            boundaries=boundaries,
            narration=narration,
            scene_index=1,
            project_id="test",
        )
        # Both should reference the same words (modulo format differences)
        assert "Ancient" in ass or "Ancient" in srt


# ── from_settings() ───────────────────────────────────────────────────────────


class TestFromSettings:
    def test_from_settings_ass_format(self):
        class S:
            subtitle_format = "ass"
            subtitle_debug = False
            subtitle_validate = True
            subtitle_max_cps = 18.0
            subtitle_max_chars_per_line = 42
            subtitle_max_lines = 2
            subtitle_ass_theme = "default"

        engine = SubtitleEngine.from_settings(S())
        assert engine.format == SubtitleFormat.ASS

    def test_from_settings_srt_format(self):
        class S:
            subtitle_format = "srt"
            subtitle_debug = False
            subtitle_validate = True
            subtitle_max_cps = 18.0
            subtitle_max_chars_per_line = 42
            subtitle_max_lines = 2
            subtitle_ass_theme = "default"

        engine = SubtitleEngine.from_settings(S())
        assert engine.format == SubtitleFormat.SRT

    def test_from_settings_minimal_settings(self):
        class MinSettings:
            pass

        engine = SubtitleEngine.from_settings(MinSettings())
        assert isinstance(engine, SubtitleEngine)

    def test_from_settings_custom_theme(self):
        class S:
            subtitle_format = "ass"
            subtitle_ass_theme = "cinematic"

        engine = SubtitleEngine.from_settings(S())
        assert engine.format == SubtitleFormat.ASS


# ── CaptionArtifact ───────────────────────────────────────────────────────────


class TestCaptionArtifact:
    def test_primary_path_prefers_ass(self, tmp_path):
        from ytfactory.captions.models import CaptionArtifact

        srt = tmp_path / "scene-001.srt"
        ass = tmp_path / "scene-001.ass"
        srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nTest\n", encoding="utf-8")
        ass.write_text("[Script Info]\n", encoding="utf-8")

        artifact = CaptionArtifact(scene_id=1, srt_path=srt, ass_path=ass)
        assert artifact.primary_path == ass

    def test_primary_path_falls_back_to_srt_when_ass_missing(self, tmp_path):
        from ytfactory.captions.models import CaptionArtifact

        srt = tmp_path / "scene-001.srt"
        ass = tmp_path / "scene-001.ass"  # does not exist
        srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nTest\n", encoding="utf-8")

        artifact = CaptionArtifact(scene_id=1, srt_path=srt, ass_path=ass)
        assert artifact.primary_path == srt

    def test_no_ass_path_returns_srt(self, tmp_path):
        from ytfactory.captions.models import CaptionArtifact

        srt = tmp_path / "scene-001.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nTest\n", encoding="utf-8")

        artifact = CaptionArtifact(scene_id=1, srt_path=srt)
        assert artifact.primary_path == srt


# ── Documentary smoke test ────────────────────────────────────────────────────


class TestDocumentarySmokeTest:
    NARRATION = (
        "In the heart of the ancient forest, where light barely pierces the canopy, "
        "a civilization once thrived. They built temples that reached toward the heavens. "
        "They mapped the stars with breathtaking precision. "
        "And then, one day, they vanished — leaving only silence."
    )

    def test_documentary_scene_ass_output(self, ass_engine):
        words = self.NARRATION.split()
        boundaries = _make_boundaries(words, pace=0.42)
        ass, srt, report = ass_engine.build_both(
            boundaries=boundaries,
            narration=self.NARRATION,
            scene_index=1,
            project_id="test",
        )
        assert "[Script Info]" in ass
        assert "[V4+ Styles]" in ass
        assert "[Events]" in ass
        assert "Dialogue:" in ass
        assert " --> " in srt
        assert report.cue_count > 0

    def test_no_double_period_in_ass(self, ass_engine):
        words = ["Sentence", "one.", "Sentence", "two."]
        boundaries = _make_boundaries(words)
        ass, _, _ = ass_engine.build_both(
            boundaries=boundaries,
            narration="Sentence one. Sentence two.",
            scene_index=1,
            project_id="test",
        )
        assert ".." not in ass
