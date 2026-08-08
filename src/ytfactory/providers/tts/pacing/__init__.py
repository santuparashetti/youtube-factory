"""Contemplative Pacing Engine — thought-block pause injection for spiritual/documentary TTS."""

from .analyzer import SentenceAnalyzer
from .config import ARC_PAUSE_SCALE, PROFILE_PAUSES, THOUGHT_PROFILE_PAUSES, PacingProfile, arc_pause_multiplier
from .injector import PauseInjector
from .models import (
    PauseCategory,
    SentenceAnalysis,
    ThoughtBlock,
    ThoughtPauseCategory,
)
from .thought_analyzer import ThoughtAnalyzer

__all__ = [
    "ARC_PAUSE_SCALE",
    "PacingProfile",
    "PROFILE_PAUSES",
    "THOUGHT_PROFILE_PAUSES",
    "arc_pause_multiplier",
    "PauseCategory",
    "SentenceAnalysis",
    "ThoughtBlock",
    "ThoughtPauseCategory",
    "SentenceAnalyzer",
    "ThoughtAnalyzer",
    "PauseInjector",
]
