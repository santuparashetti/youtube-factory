"""Contemplative Pacing Engine — sentence-level pause injection for spiritual/documentary TTS."""

from .analyzer import SentenceAnalyzer
from .config import PROFILE_PAUSES, PacingProfile
from .injector import PauseInjector
from .models import PauseCategory, SentenceAnalysis

__all__ = [
    "PacingProfile",
    "PROFILE_PAUSES",
    "PauseCategory",
    "SentenceAnalysis",
    "SentenceAnalyzer",
    "PauseInjector",
]
