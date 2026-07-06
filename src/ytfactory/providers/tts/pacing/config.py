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
class ProfilePauses:
    """Per-category pause ranges for one pacing profile."""

    short: PauseRange        # normal sentence — low emotional weight
    medium: PauseRange       # important statement — notable idea
    long: PauseRange         # major realization — profound insight
    concept_pre: PauseRange  # extra pause added before a key-concept opener


# Pause durations in milliseconds per profile.
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
