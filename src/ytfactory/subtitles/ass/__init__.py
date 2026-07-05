"""
ASS Subtitle Engine — Advanced SubStation Alpha format support.

Entry points:
  ASSWriter       — serialize cues → .ass file string
  ASSTheme        — immutable style configuration
  ThemeManager    — built-in themes + settings-driven customization
  ASSStyleBuilder — low-level [V4+ Styles] section builder
"""

from .style_builder import ASSStyleBuilder
from .theme import ASSTheme
from .theme_manager import ThemeManager
from .writer import ASSWriter

__all__ = ["ASSWriter", "ASSTheme", "ThemeManager", "ASSStyleBuilder"]
