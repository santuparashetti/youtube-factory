"""
ThemeManager — built-in ASS themes + settings-driven customization.

Built-in themes:

  default        — white text, black outline, 52px Arial Bold, 50% shadow box.
                   Professional documentary look, works on any background.

  minimal        — same as default but thinner outline, no shadow box.
                   Cleaner for light backgrounds.

  high_contrast  — larger font, heavier outline, darker box.
                   Accessibility / small-screen safe.

Themes are immutable.  Per-setting overrides use ``dataclasses.replace()`` so
the base theme is never mutated.

To add a theme: add an entry to ``ThemeManager._THEMES`` and document it here.
"""

from __future__ import annotations

import dataclasses

from .theme import ASSTheme


class ThemeManager:
    """
    Provide and customize ASS themes.

    Usage::

        theme = ThemeManager.get("default")
        theme = ThemeManager.from_settings(settings)
    """

    _THEMES: dict[str, ASSTheme] = {
        "default": ASSTheme(),
        "minimal": ASSTheme(
            name="minimal",
            outline=1.0,
            shadow=0.0,
            back_color="&H00000000",
        ),
        "high_contrast": ASSTheme(
            name="high_contrast",
            font_size=58,
            outline=3.0,
            shadow=2.0,
            back_color="&H99000000",
            border_style=3,
        ),
        "cinematic": ASSTheme(
            name="cinematic",
            font="Georgia",
            font_size=48,
            bold=False,
            italic=True,
            outline=1.5,
            shadow=1.5,
            back_color="&H60000000",
            margin_v=80,
        ),
    }

    @classmethod
    def get(cls, name: str) -> ASSTheme:
        """Return a built-in theme by name. Falls back to 'default'."""
        return cls._THEMES.get(name, cls._THEMES["default"])

    @classmethod
    def available_themes(cls) -> list[str]:
        return list(cls._THEMES.keys())

    @classmethod
    def from_settings(cls, settings) -> ASSTheme:
        """
        Build an ASSTheme from Settings, applying per-field overrides.

        Starts from the theme named by ``subtitle_ass_theme`` (default: "default"),
        then overrides individual fields when the corresponding setting is present.

        Settings read (all optional, fall back to theme defaults):
          subtitle_ass_theme
          subtitle_ass_font
          subtitle_ass_font_size
          subtitle_ass_bold
          subtitle_ass_italic
          subtitle_ass_primary_color
          subtitle_ass_outline_color
          subtitle_ass_back_color
          subtitle_ass_outline
          subtitle_ass_shadow
          subtitle_ass_margin_l
          subtitle_ass_margin_r
          subtitle_ass_margin_v
          subtitle_ass_alignment
          subtitle_ass_border_style
          subtitle_ass_play_res_x
          subtitle_ass_play_res_y
        """
        theme_name = getattr(settings, "subtitle_ass_theme", "default")
        base = cls.get(theme_name)

        overrides: dict = {}

        _maybe(settings, "subtitle_ass_font", "font", overrides)
        _maybe(settings, "subtitle_ass_font_size", "font_size", overrides)
        _maybe(settings, "subtitle_ass_bold", "bold", overrides)
        _maybe(settings, "subtitle_ass_italic", "italic", overrides)
        _maybe(settings, "subtitle_ass_primary_color", "primary_color", overrides)
        _maybe(settings, "subtitle_ass_outline_color", "outline_color", overrides)
        _maybe(settings, "subtitle_ass_back_color", "back_color", overrides)
        _maybe(settings, "subtitle_ass_outline", "outline", overrides)
        _maybe(settings, "subtitle_ass_shadow", "shadow", overrides)
        _maybe(settings, "subtitle_ass_margin_l", "margin_l", overrides)
        _maybe(settings, "subtitle_ass_margin_r", "margin_r", overrides)
        _maybe(settings, "subtitle_ass_margin_v", "margin_v", overrides)
        _maybe(settings, "subtitle_ass_alignment", "alignment", overrides)
        _maybe(settings, "subtitle_ass_border_style", "border_style", overrides)
        _maybe(settings, "subtitle_ass_play_res_x", "play_res_x", overrides)
        _maybe(settings, "subtitle_ass_play_res_y", "play_res_y", overrides)

        if not overrides:
            return base

        return dataclasses.replace(base, **overrides)


def _maybe(settings, setting_key: str, field_name: str, out: dict) -> None:
    """Copy settings.<setting_key> into out[field_name] if the attribute exists."""
    val = getattr(settings, setting_key, None)
    if val is not None:
        out[field_name] = val
