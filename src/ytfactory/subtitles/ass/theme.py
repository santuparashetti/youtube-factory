"""
ASSTheme — immutable configuration for ASS subtitle styling.

All visual properties live here.  The renderer and style builder
read from this object — nothing is hard-coded elsewhere.

Color format: &HAABBGGRR (ASS convention — reversed from RGB)
  AA = alpha: 00 = opaque, FF = fully transparent
  BB = blue channel
  GG = green channel
  RR = red channel

  &H00FFFFFF = white, opaque
  &H00000000 = black, opaque
  &H00FFFF00 = yellow, opaque (reserved for karaoke)
  &H80000000 = black, 50% transparent (shadow / box)

Alignment uses the numpad layout:
  7 8 9   (top)
  4 5 6   (middle)
  1 2 3   (bottom)
  2 = bottom-center — standard subtitle position

BorderStyle:
  1 = outline + drop shadow  (most common, professional)
  3 = opaque box behind text (accessibility / high contrast)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ASSTheme:
    """
    Immutable ASS style configuration.

    Passed to ASSStyleBuilder and ASSWriter at construction time.
    Create custom themes by replacing individual fields via ``dataclasses.replace()``.
    """

    name: str = "default"

    # ── Typography ──────────────────────────────────────────────────────────────
    font: str = "Arial"
    font_size: int = 52
    bold: bool = True
    italic: bool = False
    underline: bool = False
    strikeout: bool = False
    scale_x: int = 100
    scale_y: int = 100
    spacing: float = 0.0

    # ── Colors (ASS &HAABBGGRR) ─────────────────────────────────────────────────
    primary_color: str = "&H00FFFFFF"  # white — the subtitle text
    secondary_color: str = "&H00FFFF00"  # yellow — reserved for future karaoke
    outline_color: str = "&H00000000"  # black outline around text
    back_color: str = "&H80000000"  # 50% transparent black (shadow / box)

    # ── Outline & shadow ────────────────────────────────────────────────────────
    border_style: int = 1  # 1=outline+shadow, 3=opaque box
    outline: float = 2.0  # outline thickness in pixels
    shadow: float = 1.0  # drop shadow depth in pixels

    # ── Position ────────────────────────────────────────────────────────────────
    alignment: int = 2  # 2=bottom-center
    margin_l: int = 80  # left safe margin (pixels, 1920 reference)
    margin_r: int = 80  # right safe margin
    margin_v: int = 60  # vertical margin from bottom

    # ── Rotation ────────────────────────────────────────────────────────────────
    angle: float = 0.0  # rotation in degrees

    # ── Script resolution (match video dimensions) ─────────────────────────────
    play_res_x: int = 1920
    play_res_y: int = 1080

    # ── Encoding ────────────────────────────────────────────────────────────────
    encoding: int = 1  # 1 = Unicode / Latin extended

    def bold_flag(self) -> int:
        """ASS bold flag: -1 = bold, 0 = not bold."""
        return -1 if self.bold else 0

    def italic_flag(self) -> int:
        return -1 if self.italic else 0

    def underline_flag(self) -> int:
        return -1 if self.underline else 0

    def strikeout_flag(self) -> int:
        return -1 if self.strikeout else 0
