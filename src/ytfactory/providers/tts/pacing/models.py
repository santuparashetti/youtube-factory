"""Data models for the Contemplative Pacing Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PauseCategory(str, Enum):
    """Semantic weight class of a sentence, mapped to pause duration ranges."""

    NONE = "none"         # last sentence — no trailing silence
    SHORT = "short"       # score 0–2: connecting/transitional sentence
    MEDIUM = "medium"     # score 3–4: important, notable statement
    LONG = "long"         # score 5+:  major realization, profound insight


@dataclass
class SentenceAnalysis:
    """Analysis result for one sentence in a narration."""

    text: str
    score: int
    pause_category: PauseCategory
    pause_ms: int           # total pause to insert AFTER this sentence in ms
    triggers: list[str] = field(default_factory=list)

    def is_silent(self) -> bool:
        return self.pause_ms == 0
