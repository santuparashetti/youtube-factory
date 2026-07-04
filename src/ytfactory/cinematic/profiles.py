"""
Rendering profiles for the Cinematic Motion Engine.

Each profile controls:
- How much the camera moves (scale ranges, drift amount)
- How motion is interpolated (easing curve)
- Which motion types are available (simplified vs full emotion mapping)

The profile system is the single place to tune the quality/speed trade-off.
Phase 4 will wire profiles to Settings; here they are pure data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RenderProfile(str, Enum):
    """Named rendering quality profiles."""
    DRAFT     = "draft"      # Static — fastest render, no motion
    BALANCED  = "balanced"   # Simple 3-category motion, linear easing
    CINEMATIC = "cinematic"  # Full 8-type emotion-aware motion, smooth easing
    PREMIUM   = "premium"    # Full motion + wider scale range + long easing


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
    """
    scale_range_small:  tuple[float, float]
    scale_range_medium: tuple[float, float]
    scale_range_large:  tuple[float, float]
    drift_amount:       float
    easing:             str
    motion_map:         dict[str, tuple[str, str]]


# ── Emotion → (motion_type, scale_tier) maps ─────────────────────────────────

_STATIC_MAP: dict[str, tuple[str, str]] = {
    e: ("static", "small") for e in [
        "curiosity", "wonder", "reflection", "mystery", "peace",
        "hope", "compassion", "urgency", "sadness", "awe",
        "determination", "revelation",
    ]
}

# Balanced: three motion categories, linear easing, moderate scale
_BALANCED_MAP: dict[str, tuple[str, str]] = {
    "curiosity":     ("push_in",  "medium"),
    "wonder":        ("pull_out", "medium"),
    "reflection":    ("drift",    "small"),
    "mystery":       ("push_in",  "small"),
    "peace":         ("static",   "small"),
    "hope":          ("pull_out", "small"),
    "compassion":    ("push_in",  "small"),
    "urgency":       ("push_in",  "large"),
    "sadness":       ("pull_out", "small"),
    "awe":           ("pull_out", "large"),
    "determination": ("push_in",  "medium"),
    "revelation":    ("static",   "small"),
}

# Cinematic & Premium: full eight motion types, emotion-tuned
_CINEMATIC_MAP: dict[str, tuple[str, str]] = {
    "curiosity":     ("push_in",       "medium"),
    "wonder":        ("pull_out_wide", "large"),
    "reflection":    ("drift",         "small"),
    "mystery":       ("push_in_slow",  "small"),
    "peace":         ("static",        "small"),
    "hope":          ("tilt_up",       "small"),
    "compassion":    ("push_in",       "small"),
    "urgency":       ("push_in_fast",  "large"),
    "sadness":       ("pull_out",      "medium"),
    "awe":           ("pull_out_wide", "large"),
    "determination": ("push_in",       "medium"),
    "revelation":    ("static",        "small"),
}


# ── Profile registry ─────────────────────────────────────────────────────────

_PROFILE_CONFIGS: dict[str, ProfileConfig] = {
    RenderProfile.DRAFT: ProfileConfig(
        scale_range_small  = (1.0, 1.0),
        scale_range_medium = (1.0, 1.0),
        scale_range_large  = (1.0, 1.0),
        drift_amount       = 0.0,
        easing             = "linear",
        motion_map         = _STATIC_MAP,
    ),
    RenderProfile.BALANCED: ProfileConfig(
        scale_range_small  = (1.0, 1.07),
        scale_range_medium = (1.0, 1.12),
        scale_range_large  = (1.0, 1.15),
        drift_amount       = 0.04,
        easing             = "linear",
        motion_map         = _BALANCED_MAP,
    ),
    RenderProfile.CINEMATIC: ProfileConfig(
        scale_range_small  = (1.0, 1.07),
        scale_range_medium = (1.0, 1.12),
        scale_range_large  = (1.0, 1.18),
        drift_amount       = 0.05,
        easing             = "ease_in_out",
        motion_map         = _CINEMATIC_MAP,
    ),
    RenderProfile.PREMIUM: ProfileConfig(
        scale_range_small  = (1.0, 1.10),
        scale_range_medium = (1.0, 1.15),
        scale_range_large  = (1.0, 1.22),
        drift_amount       = 0.06,
        easing             = "ease_in_out",
        motion_map         = _CINEMATIC_MAP,  # same categories, wider range
    ),
}


def get_profile_config(profile: str) -> ProfileConfig:
    """Return ProfileConfig for the given profile name (case-insensitive)."""
    key = profile.lower().strip()
    return _PROFILE_CONFIGS.get(key, _PROFILE_CONFIGS[RenderProfile.BALANCED])
