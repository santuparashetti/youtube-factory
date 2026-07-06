"""Contemplative Pacing Engine — thought-block pause injection for spiritual/documentary TTS."""

from .analyzer import SentenceAnalyzer
from .config import PROFILE_PAUSES, THOUGHT_PROFILE_PAUSES, PacingProfile
from .injector import PauseInjector
from .models import (
    PauseCategory,
    SentenceAnalysis,
    ThoughtBlock,
    ThoughtPauseCategory,
)
from .thought_analyzer import ThoughtAnalyzer

__all__ = [
    "PacingProfile",
    "PROFILE_PAUSES",
    "THOUGHT_PROFILE_PAUSES",
    "PauseCategory",
    "SentenceAnalysis",
    "ThoughtBlock",
    "ThoughtPauseCategory",
    "SentenceAnalyzer",
    "ThoughtAnalyzer",
    "PauseInjector",
]
