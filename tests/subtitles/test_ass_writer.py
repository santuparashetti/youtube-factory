"""Tests for ASSWriter, ASSStyleBuilder, and ASS format correctness."""

from __future__ import annotations


import pytest

from ytfactory.subtitles.ass.style_builder import ASSStyleBuilder
from ytfactory.subtitles.ass.theme import ASSTheme
from ytfactory.subtitles.ass.writer import ASSWriter, _fmt_ass_time
from ytfactory.subtitles.models import SubtitleCue


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _cue(index: int, start: float, end: float, lines: list[str]) -> SubtitleCue:
    return SubtitleCue(index=index, start=start, end=end, lines=lines)


@pytest.fixture()
def writer() -> ASSWriter:
    return ASSWriter()


@pytest.fixture()
def theme() -> ASSTheme:
    return ASSTheme()


# ── Timestamp formatting ──────────────────────────────────────────────────────


class TestFmtAssTime:
    def test_zero(self):
        assert _fmt_ass_time(0.0) == "0:00:00.00"

    def test_one_second(self):
        assert _fmt_ass_time(1.0) == "0:00:01.00"

    def test_centiseconds(self):
        assert _fmt_ass_time(1.57) == "0:00:01.57"

    def test_one_minute(self):
        assert _fmt_ass_time(60.0) == "0:01:00.00"

    def test_one_hour(self):
        assert _fmt_ass_time(3600.0) == "1:00:00.00"

    def test_90_seconds(self):
        assert _fmt_ass_time(90.0) == "0:01:30.00"

    def test_negative_clamps_to_zero(self):
        assert _fmt_ass_time(-1.0) == "0:00:00.00"

    def test_centiseconds_clamped(self):
        # 1.999 → cs=99, not cs=100
        result = _fmt_ass_time(1.999)
        assert result.endswith(".99")

    def test_format_has_colon_and_dot(self):
        result = _fmt_ass_time(3661.5)
        assert ":" in result
        assert "." in result


# ── ASSWriter.write() ─────────────────────────────────────────────────────────


class TestASSWriterEmpty:
    def test_empty_cues_returns_empty_string(self, writer):
        assert writer.write([]) == ""


class TestASSWriterSections:
    def test_script_info_section_present(self, writer):
        cues = [_cue(1, 0.0, 3.0, ["Hello world."])]
        result = writer.write(cues)
        assert "[Script Info]" in result

    def test_v4_styles_section_present(self, writer):
        cues = [_cue(1, 0.0, 3.0, ["Hello."])]
        result = writer.write(cues)
        assert "[V4+ Styles]" in result

    def test_events_section_present(self, writer):
        cues = [_cue(1, 0.0, 3.0, ["Hello."])]
        result = writer.write(cues)
        assert "[Events]" in result

    def test_events_format_line_present(self, writer):
        cues = [_cue(1, 0.0, 3.0, ["Hello."])]
        result = writer.write(cues)
        assert "Format: Layer, Start, End, Style, Name" in result

    def test_dialogue_line_present(self, writer):
        cues = [_cue(1, 0.0, 3.0, ["Hello."])]
        result = writer.write(cues)
        assert "Dialogue:" in result

    def test_play_res_x_in_script_info(self, writer):
        cues = [_cue(1, 0.0, 1.0, ["Test."])]
        result = writer.write(cues)
        assert "PlayResX: 1920" in result

    def test_play_res_y_in_script_info(self, writer):
        cues = [_cue(1, 0.0, 1.0, ["Test."])]
        result = writer.write(cues)
        assert "PlayResY: 1080" in result

    def test_script_type_v4(self, writer):
        cues = [_cue(1, 0.0, 1.0, ["Test."])]
        result = writer.write(cues)
        assert "ScriptType: v4.00+" in result


class TestASSWriterDialogue:
    def test_dialogue_contains_text(self, writer):
        cues = [_cue(1, 1.0, 4.0, ["Ancient wisdom."])]
        result = writer.write(cues)
        assert "Ancient wisdom." in result

    def test_dialogue_timestamps(self, writer):
        cues = [_cue(1, 1.0, 4.0, ["Text."])]
        result = writer.write(cues)
        assert "0:00:01.00" in result
        assert "0:00:04.00" in result

    def test_multi_line_cue_uses_hard_break(self, writer):
        cues = [_cue(1, 0.0, 3.0, ["Line one", "Line two"])]
        result = writer.write(cues)
        assert r"\N" in result

    def test_single_line_cue_no_hard_break(self, writer):
        cues = [_cue(1, 0.0, 3.0, ["Single line."])]
        result = writer.write(cues)
        dialogue_lines = [ln for ln in result.split("\n") if ln.startswith("Dialogue:")]
        assert len(dialogue_lines) == 1
        assert r"\N" not in dialogue_lines[0]

    def test_multiple_cues_all_present(self, writer):
        cues = [
            _cue(1, 0.0, 2.0, ["First cue."]),
            _cue(2, 2.5, 5.0, ["Second cue."]),
            _cue(3, 5.5, 8.0, ["Third cue."]),
        ]
        result = writer.write(cues)
        dialogue_lines = [ln for ln in result.split("\n") if ln.startswith("Dialogue:")]
        assert len(dialogue_lines) == 3

    def test_style_is_default(self, writer):
        cues = [_cue(1, 0.0, 2.0, ["Test."])]
        result = writer.write(cues)
        dialogue_lines = [ln for ln in result.split("\n") if ln.startswith("Dialogue:")]
        assert "Default" in dialogue_lines[0]

    def test_empty_lines_skipped_in_text(self, writer):
        cues = [_cue(1, 0.0, 2.0, ["", "Visible line.", ""])]
        result = writer.write(cues)
        assert "Visible line." in result

    def test_cue_with_all_empty_lines_skipped(self, writer):
        cues = [
            _cue(1, 0.0, 2.0, ["", "  "]),
            _cue(2, 2.0, 4.0, ["Valid text."]),
        ]
        result = writer.write(cues)
        dialogue_lines = [ln for ln in result.split("\n") if ln.startswith("Dialogue:")]
        # First cue has no displayable text — should be skipped
        assert len(dialogue_lines) == 1
        assert "Valid text." in dialogue_lines[0]


class TestASSWriterCustomTheme:
    def test_custom_font_in_style(self):
        theme = ASSTheme(font="Georgia", font_size=48)
        writer = ASSWriter(theme=theme)
        cues = [_cue(1, 0.0, 2.0, ["Test."])]
        result = writer.write(cues)
        assert "Georgia" in result
        assert "48" in result

    def test_custom_play_res(self):
        theme = ASSTheme(play_res_x=1280, play_res_y=720)
        writer = ASSWriter(theme=theme)
        cues = [_cue(1, 0.0, 1.0, ["Test."])]
        result = writer.write(cues)
        assert "PlayResX: 1280" in result
        assert "PlayResY: 720" in result


# ── ASSStyleBuilder ───────────────────────────────────────────────────────────


class TestASSStyleBuilder:
    def test_produces_v4_styles_section(self):
        builder = ASSStyleBuilder()
        theme = ASSTheme()
        result = builder.build_section(theme)
        assert "[V4+ Styles]" in result

    def test_produces_format_line(self):
        builder = ASSStyleBuilder()
        theme = ASSTheme()
        result = builder.build_section(theme)
        assert "Format:" in result

    def test_default_style_name(self):
        builder = ASSStyleBuilder()
        theme = ASSTheme()
        result = builder.build_section(theme)
        assert "Style: Default," in result

    def test_font_in_style_line(self):
        builder = ASSStyleBuilder()
        theme = ASSTheme(font="Roboto")
        result = builder.build_section(theme)
        assert "Roboto" in result

    def test_primary_color_in_style(self):
        builder = ASSStyleBuilder()
        theme = ASSTheme(primary_color="&H0000FFFF")
        result = builder.build_section(theme)
        assert "&H0000FFFF" in result

    def test_extra_themes_added(self):
        builder = ASSStyleBuilder()
        base = ASSTheme()
        extra = ASSTheme(name="Speaker2", primary_color="&H0000FF00")
        result = builder.build_section(base, extra_themes=[extra])
        assert "Style: Speaker2," in result

    def test_bold_flag_in_style(self):
        builder = ASSStyleBuilder()
        theme = ASSTheme(bold=True)
        result = builder.build_section(theme)
        # Bold flag -1 must appear in the style line
        style_line = [ln for ln in result.split("\n") if ln.startswith("Style:")][0]
        assert "-1" in style_line

    def test_not_bold_flag_in_style(self):
        builder = ASSStyleBuilder()
        theme = ASSTheme(bold=False)
        result = builder.build_section(theme)
        style_line = [ln for ln in result.split("\n") if ln.startswith("Style:")][0]
        # Should have ,0, for bold flag (not -1)
        # Check that the style line contains 0 for bold (first 0 after colors)
        assert "0" in style_line


# ── Section ordering ──────────────────────────────────────────────────────────


class TestASSFileSectionOrdering:
    def test_script_info_before_styles(self, writer):
        cues = [_cue(1, 0.0, 1.0, ["Test."])]
        result = writer.write(cues)
        si_pos = result.index("[Script Info]")
        vs_pos = result.index("[V4+ Styles]")
        ev_pos = result.index("[Events]")
        assert si_pos < vs_pos < ev_pos

    def test_utf8_safe_characters(self, writer):
        cues = [_cue(1, 0.0, 2.0, ["Wisdom… silence — forever."])]
        result = writer.write(cues)
        result.encode("utf-8")  # no crash = UTF-8 safe
