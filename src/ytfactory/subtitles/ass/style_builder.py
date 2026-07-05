"""
ASSStyleBuilder — converts an ASSTheme into the [V4+ Styles] section.

ASS style line format (v4.00+ specification):

  Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,
          OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,
          ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,
          Alignment, MarginL, MarginR, MarginV, Encoding

This builder generates exactly one style entry ("Default") consumed by ASSWriter.
Multiple named styles are reserved for future speaker-style support.
"""

from __future__ import annotations

from .theme import ASSTheme

_FORMAT_LINE = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
    "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, Encoding"
)


class ASSStyleBuilder:
    """Build [V4+ Styles] section from one or more ASSTheme objects."""

    def build_section(
        self, theme: ASSTheme, extra_themes: list[ASSTheme] | None = None
    ) -> str:
        """
        Produce the full [V4+ Styles] section including header.

        The primary theme becomes the "Default" style.
        Each entry in extra_themes becomes an additional named style
        using theme.name as the style name.
        """
        lines = ["[V4+ Styles]", _FORMAT_LINE]
        lines.append(self._style_line(theme, style_name="Default"))

        if extra_themes:
            for t in extra_themes:
                lines.append(self._style_line(t, style_name=t.name))

        return "\n".join(lines)

    def _style_line(self, theme: ASSTheme, style_name: str) -> str:
        """
        Format a single Style: line from an ASSTheme.

        Fields are ordered exactly as the Format: header specifies.
        """
        return (
            f"Style: {style_name},"
            f"{theme.font},"
            f"{theme.font_size},"
            f"{theme.primary_color},"
            f"{theme.secondary_color},"
            f"{theme.outline_color},"
            f"{theme.back_color},"
            f"{theme.bold_flag()},"
            f"{theme.italic_flag()},"
            f"{theme.underline_flag()},"
            f"{theme.strikeout_flag()},"
            f"{theme.scale_x},"
            f"{theme.scale_y},"
            f"{theme.spacing:.1f},"
            f"{theme.angle:.1f},"
            f"{theme.border_style},"
            f"{theme.outline:.1f},"
            f"{theme.shadow:.1f},"
            f"{theme.alignment},"
            f"{theme.margin_l},"
            f"{theme.margin_r},"
            f"{theme.margin_v},"
            f"{theme.encoding}"
        )
