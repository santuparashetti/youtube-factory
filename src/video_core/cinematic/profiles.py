"""
Rendering profiles for the Cinematic Motion Engine.

Each profile controls:
- How much the camera moves (scale ranges, drift amount)
- How motion is interpolated (easing curve)
- Which motion types are available (simplified vs full emotion mapping)

The profile system is the single place to tune the quality/speed trade-off.
Profiles are selected via ``Settings.render_profile`` (default: "cinematic").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RenderProfile(str, Enum):
    """Named rendering quality profiles."""

    DRAFT = "draft"  # Static — fastest render, no motion
    BALANCED = "balanced"  # Simple 3-category motion, linear easing
    CINEMATIC = "cinematic"  # Full 8-type emotion-aware motion, smooth easing
    PREMIUM = "premium"  # Full motion + wider scale range + long easing


@dataclass(frozen=True)
class ProfileConfig:
    """
    Camera motion parameters for one rendering profile.

    Scale ranges are expressed as zoom multipliers (1.0 = full frame).
    A scene whose dominant emotion maps to "medium" scale gets
    start_scale = scale_range_medium[0], end_scale = scale_range_medium[1]
    (or reversed for pull-out motions).

    Attributes:
        scale_range_small:  (start, end) for low-intensity motions.
        scale_range_medium: (start, end) for standard motions.
        scale_range_large:  (start, end) for high-energy motions.
        drift_amount: Fraction of frame width the camera travels in a drift
                      (0.05 = 5% of frame width). 0.0 = no horizontal drift.
        easing: Interpolation curve applied to zoompan — "linear" or
                "ease_in_out". ease_in_out feels more cinematic but requires
                a custom zoompan expression in Phase 3.
        motion_map: Profile-specific Emotion name → (motion_type, scale_tier).
                    "draft" maps everything to static; others use emotion tables.
        reference_duration_seconds: Reference scene duration (seconds) for
            scaling drift magnitude. Longer scenes get proportionally larger
            drift so the motion feels continuous rather than fading to a hold.
        max_drift_scale_factor: Upper bound on duration-based drift scaling to
            prevent extreme zoompan values for very short or very long scenes.
    """

    scale_range_small: tuple[float, float]
    scale_range_medium: tuple[float, float]
    scale_range_large: tuple[float, float]
    drift_amount: float
    easing: str
    motion_map: dict[str, tuple[str, str]]
    reference_duration_seconds: float = 5.0
    max_drift_scale_factor: float = 2.0


# ── Emotion → (motion_type, scale_tier) maps ─────────────────────────────────

_STATIC_MAP: dict[str, tuple[str, str]] = {
    e: ("static", "small")
    for e in [
        "curiosity",
        "wonder",
        "reflection",
        "mystery",
        "peace",
        "hope",
        "compassion",
        "urgency",
        "sadness",
        "awe",
        "determination",
        "revelation",
    ]
}

# Balanced: three motion categories, linear easing, moderate scale
_BALANCED_MAP: dict[str, tuple[str, str]] = {
    "curiosity": ("push_in", "medium"),
    "wonder": ("pull_out", "medium"),
    "reflection": ("drift", "small"),
    "mystery": ("push_in", "small"),
    "peace": ("drift", "small"),
    "hope": ("pull_out", "small"),
    "compassion": ("push_in", "small"),
    "urgency": ("push_in", "large"),
    "sadness": ("pull_out", "small"),
    "awe": ("pull_out", "large"),
    "determination": ("push_in", "medium"),
    "revelation": ("drift", "small"),
}

# Cinematic & Premium: full eight motion types, emotion-tuned
_CINEMATIC_MAP: dict[str, tuple[str, str]] = {
    "curiosity": ("push_in", "medium"),
    "wonder": ("pull_out_wide", "large"),
    "reflection": ("drift", "small"),
    "mystery": ("push_in_slow", "small"),
    "peace": ("drift", "small"),
    "hope": ("tilt_up", "small"),
    "compassion": ("push_in", "small"),
    "urgency": ("push_in_fast", "large"),
    "sadness": ("pull_out", "medium"),
    "awe": ("pull_out_wide", "large"),
    "determination": ("push_in", "medium"),
    "revelation": ("drift", "small"),
  }

# Acceptable-motion sets for the motion-variety rebalancer.
# Each emotion maps to a small ranked set of alternatives appropriate to its
# emotional register.  The rebalancer falls back within the same emotion rather
# than substituting an unrelated motion type.
_ACCEPTABLE_MOTIONS: dict[str, list[str]] = {
    "curiosity": ["push_in", "drift"],
    "wonder": ["pull_out", "drift"],
    "reflection": ["drift", "push_in"],
    "mystery": ["push_in", "drift"],
    "peace": ["drift", "push_in"],
    "hope": ["pull_out", "push_in"],
    "compassion": ["push_in", "drift"],
    "urgency": ["push_in", "drift"],
    "sadness": ["pull_out", "drift"],
    "awe": ["pull_out", "drift"],
    "determination": ["push_in", "drift"],
    "revelation": ["drift", "push_in"],
}


def get_acceptable_motions(emotion: str) -> list[str]:
    """Return ranked acceptable motion types for an emotion."""
    return list(_ACCEPTABLE_MOTIONS.get(emotion, ["drift"]))


# ── Profile registry ─────────────────────────────────────────────────────────

_PROFILE_CONFIGS: dict[str, ProfileConfig] = {
    RenderProfile.DRAFT: ProfileConfig(
        scale_range_small=(1.0, 1.0),
        scale_range_medium=(1.0, 1.0),
        scale_range_large=(1.0, 1.0),
        drift_amount=0.0,
        easing="linear",
        motion_map=_STATIC_MAP,
    ),
    RenderProfile.BALANCED: ProfileConfig(
        scale_range_small=(1.0, 1.10),
        scale_range_medium=(1.0, 1.15),
        scale_range_large=(1.0, 1.20),
        drift_amount=0.05,
        easing="linear",
        motion_map=_BALANCED_MAP,
    ),
    RenderProfile.CINEMATIC: ProfileConfig(
        scale_range_small=(1.0, 1.10),
        scale_range_medium=(1.0, 1.15),
        scale_range_large=(1.0, 1.22),
        drift_amount=0.06,
        easing="ease_in_out",
        motion_map=_CINEMATIC_MAP,
    ),
    RenderProfile.PREMIUM: ProfileConfig(
        scale_range_small=(1.0, 1.10),
        scale_range_medium=(1.0, 1.18),
        scale_range_large=(1.0, 1.25),
        drift_amount=0.07,
        easing="ease_in_out",
        motion_map=_CINEMATIC_MAP,  # same categories, wider range
    ),
}


def get_profile_config(profile: str) -> ProfileConfig:
    """Return ProfileConfig for the given profile name (case-insensitive)."""
    key = profile.lower().strip()
    return _PROFILE_CONFIGS.get(key, _PROFILE_CONFIGS[RenderProfile.BALANCED])
