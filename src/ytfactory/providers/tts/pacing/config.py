"""Pacing profiles and pause duration ranges for the Contemplative Pacing Engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PacingProfile(str, Enum):
    NORMAL = "normal"
    DOCUMENTARY = "documentary"
    SPIRITUAL = "spiritual"
    MEDITATION = "meditation"
    SLOW_REFLECTION = "slow_reflection"


@dataclass(frozen=True)
class PauseRange:
    """Inclusive millisecond range from which a pause duration is sampled."""

    min_ms: int
    max_ms: int

    def clamp(self, value: int) -> int:
        return max(self.min_ms, min(self.max_ms, value))


@dataclass(frozen=True)
class ThoughtPauseRanges:
    """Per-depth silence ranges for thought-based pacing (one per profile)."""

    small: PauseRange  # simple complete thought
    realization: PauseRange  # meaningful insight / important realization
    insight: PauseRange  # deep philosophical point — maximum contemplative space


@dataclass(frozen=True)
class ProfilePauses:
    """Per-category pause ranges for one pacing profile."""

    short: PauseRange  # normal sentence — low emotional weight
    medium: PauseRange  # important statement — notable idea
    long: PauseRange  # major realization — profound insight
    concept_pre: PauseRange  # extra pause added before a key-concept opener


# ── Thought-based pause tables (ThoughtAnalyzer / PauseInjector) ─────────────
#
# Each profile defines silence ranges for three depth categories:
#   small       — complete but simple thought (brief breathing space)
#   realization — meaningful insight (let the idea land)
#   insight     — deep philosophical point (full contemplative space)
#
# "spiritual" ranges match the channel's target feel (calm monk / philosopher).
#
THOUGHT_PROFILE_PAUSES: dict[str, ThoughtPauseRanges] = {
    "normal": ThoughtPauseRanges(
        small=PauseRange(400, 700),
        realization=PauseRange(800, 1200),
        insight=PauseRange(1200, 1800),
    ),
    "documentary": ThoughtPauseRanges(
        small=PauseRange(600, 900),
        realization=PauseRange(1200, 1800),
        insight=PauseRange(1800, 2500),
    ),
    "spiritual": ThoughtPauseRanges(
        small=PauseRange(800, 1200),
        realization=PauseRange(1200, 1800),
        insight=PauseRange(1800, 2500),
    ),
    "meditation": ThoughtPauseRanges(
        small=PauseRange(1200, 1800),
        realization=PauseRange(2000, 3000),
        insight=PauseRange(3000, 4500),
    ),
    "slow_reflection": ThoughtPauseRanges(
        small=PauseRange(1500, 2000),
        realization=PauseRange(2500, 3500),
        insight=PauseRange(3500, 5000),
    ),
}


# ── Sentence-based pause tables (SentenceAnalyzer — legacy) ──────────────────
#
#   normal          — plain narration, slight breathiness
#   documentary     — nature/history doc style, dignified pacing
#   spiritual       — calm teacher / monk, generous silence (default for this channel)
#   meditation      — very slow, each phrase fully lands
#   slow_reflection — maximum contemplative space
#
PROFILE_PAUSES: dict[str, ProfilePauses] = {
    "normal": ProfilePauses(
        short=PauseRange(200, 400),
        medium=PauseRange(500, 800),
        long=PauseRange(800, 1200),
        concept_pre=PauseRange(0, 200),
    ),
    "documentary": ProfilePauses(
        short=PauseRange(400, 600),
        medium=PauseRange(800, 1200),
        long=PauseRange(1200, 1800),
        concept_pre=PauseRange(200, 400),
    ),
    "spiritual": ProfilePauses(
        short=PauseRange(500, 700),
        medium=PauseRange(1200, 1800),
        long=PauseRange(2000, 2500),
        concept_pre=PauseRange(300, 500),
    ),
    "meditation": ProfilePauses(
        short=PauseRange(700, 1000),
        medium=PauseRange(1800, 2500),
        long=PauseRange(2500, 3500),
        concept_pre=PauseRange(400, 700),
    ),
    "slow_reflection": ProfilePauses(
        short=PauseRange(1000, 1500),
        medium=PauseRange(2500, 3500),
        long=PauseRange(3500, 5000),
        concept_pre=PauseRange(500, 1000),
    ),
}


# ── Arc-phase pause scaling (scene_position → multiplier) ─────────────────────
#
# Scales thought-block pause durations based on where a scene sits in the video.
# Hook/opening scenes get minimal pauses (fast pace, retain viewers).
# Build/climax scenes get reduced pauses (maintain momentum at turning points).
# Resolution scenes keep full contemplative pauses.

ARC_PAUSE_SCALE: list[tuple[float, float]] = [
    # (position_threshold, multiplier) — first match wins
    (0.10, 0.3),   # hook: 0%–10% — minimal pauses, maximum pace
    (0.20, 0.6),   # opening: 10%–20% — brisk but settling in
    (0.65, 0.7),   # build: 20%–65% — slightly tighter than default
    (0.80, 0.5),   # climax: 65%–80% — fast cuts at turning points
    (1.01, 1.0),   # resolution: 80%–100% — full contemplative pauses
]


def arc_pause_multiplier(scene_position: float) -> float:
    """Return the pause duration multiplier for a given scene position (0.0–1.0)."""
    for threshold, multiplier in ARC_PAUSE_SCALE:
        if scene_position < threshold:
            return multiplier
    return 1.0
