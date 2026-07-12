"""Cinematic Motion Engine configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CinematicConfig:
    """
    Top-level configuration for the Cinematic Motion Engine.

    Passed to both MotionPlanner and TransitionPlanner so all cinematic
    decisions flow from a single source of truth.

    Attributes:
        profile: Rendering quality profile — one of draft | balanced |
                 cinematic | premium. Controls motion intensity, easing
                 curves, and transition types.
    """

    profile: str = "balanced"
