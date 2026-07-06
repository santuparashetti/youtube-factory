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


# ── Thought-based pacing models ───────────────────────────────────────────────

class ThoughtPauseCategory(str, Enum):
    """Depth classification for a thought block, mapped to silence duration ranges."""

    NONE = "none"               # last block — no trailing silence
    SMALL = "small"             # simple complete thought: 0.8–1.2 s
    REALIZATION = "realization" # meaningful insight: 1.5–2.5 s
    INSIGHT = "insight"         # deep philosophical point: 2.5–4.0 s


@dataclass
class ThoughtBlock:
    """One semantic thought unit in the narration.

    A block is one or more grammatical sentences that form a single complete
    idea. Silence is inserted AFTER the block (not after every sentence) to
    give the listener time to absorb the thought before the next one begins.
    """

    sentences: list[str]            # component sentences (for reference)
    text: str                       # joined text synthesised as one utterance
    pause_ms: int                   # silence to insert after this block (0 = last)
    pause_category: ThoughtPauseCategory
    triggers: list[str] = field(default_factory=list)
