"""Tests for ASSTheme and ThemeManager."""

from __future__ import annotations

import dataclasses

import pytest

from ytfactory.subtitles.ass.theme import ASSTheme
from ytfactory.subtitles.ass.theme_manager import ThemeManager


class TestASSTheme:
    def test_default_theme_has_expected_font(self):
        t = ASSTheme()
        assert t.font == "Arial"

    def test_default_font_size(self):
        t = ASSTheme()
        assert t.font_size == 52

    def test_default_is_bold(self):
        t = ASSTheme()
        assert t.bold is True

    def test_bold_flag_true(self):
        t = ASSTheme(bold=True)
        assert t.bold_flag() == -1

    def test_bold_flag_false(self):
        t = ASSTheme(bold=False)
        assert t.bold_flag() == 0

    def test_italic_flag_false(self):
        t = ASSTheme(italic=False)
        assert t.italic_flag() == 0

    def test_italic_flag_true(self):
        t = ASSTheme(italic=True)
        assert t.italic_flag() == -1

    def test_underline_flag(self):
        assert ASSTheme(underline=True).underline_flag() == -1
        assert ASSTheme(underline=False).underline_flag() == 0

    def test_strikeout_flag(self):
        assert ASSTheme(strikeout=True).strikeout_flag() == -1
        assert ASSTheme(strikeout=False).strikeout_flag() == 0

    def test_primary_color_is_white(self):
        t = ASSTheme()
        assert t.primary_color == "&H00FFFFFF"

    def test_outline_color_is_black(self):
        t = ASSTheme()
        assert t.outline_color == "&H00000000"

    def test_back_color_is_semi_transparent(self):
        # &H80 alpha = 128/255 ≈ 50% transparent
        t = ASSTheme()
        assert t.back_color.startswith("&H80")

    def test_alignment_bottom_center(self):
        t = ASSTheme()
        assert t.alignment == 2

    def test_margins_are_positive(self):
        t = ASSTheme()
        assert t.margin_l > 0
        assert t.margin_r > 0
        assert t.margin_v > 0

    def test_theme_is_frozen(self):
        t = ASSTheme()
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            t.font = "Times New Roman"  # type: ignore[misc]

    def test_replace_creates_new_theme(self):
        base = ASSTheme()
        custom = dataclasses.replace(base, font="Georgia", font_size=48)
        assert custom.font == "Georgia"
        assert custom.font_size == 48
        assert base.font == "Arial"  # unchanged


class TestThemeManager:
    def test_get_default_returns_ass_theme(self):
        t = ThemeManager.get("default")
        assert isinstance(t, ASSTheme)

    def test_get_minimal(self):
        t = ThemeManager.get("minimal")
        assert t.name == "minimal"
        assert t.outline < ASSTheme().outline

    def test_get_high_contrast(self):
        t = ThemeManager.get("high_contrast")
        assert t.font_size > ASSTheme().font_size

    def test_get_cinematic(self):
        t = ThemeManager.get("cinematic")
        assert t.name == "cinematic"

    def test_unknown_theme_falls_back_to_default(self):
        t = ThemeManager.get("nonexistent_theme_xyz")
        assert t.name == "default"

    def test_available_themes_includes_default(self):
        themes = ThemeManager.available_themes()
        assert "default" in themes

    def test_available_themes_returns_list(self):
        assert isinstance(ThemeManager.available_themes(), list)
        assert len(ThemeManager.available_themes()) >= 3

    def test_from_settings_no_overrides(self):
        class MinSettings:
            pass

        t = ThemeManager.from_settings(MinSettings())
        assert isinstance(t, ASSTheme)
        assert t.name == "default"

    def test_from_settings_theme_name(self):
        class S:
            subtitle_ass_theme = "minimal"

        t = ThemeManager.from_settings(S())
        assert t.name == "minimal"

    def test_from_settings_font_override(self):
        class S:
            subtitle_ass_theme = "default"
            subtitle_ass_font = "Helvetica"

        t = ThemeManager.from_settings(S())
        assert t.font == "Helvetica"

    def test_from_settings_font_size_override(self):
        class S:
            subtitle_ass_theme = "default"
            subtitle_ass_font_size = 64

        t = ThemeManager.from_settings(S())
        assert t.font_size == 64

    def test_from_settings_color_override(self):
        class S:
            subtitle_ass_theme = "default"
            subtitle_ass_primary_color = "&H0000FFFF"  # yellow

        t = ThemeManager.from_settings(S())
        assert t.primary_color == "&H0000FFFF"

    def test_from_settings_bold_override(self):
        class S:
            subtitle_ass_theme = "default"
            subtitle_ass_bold = False

        t = ThemeManager.from_settings(S())
        assert t.bold is False
