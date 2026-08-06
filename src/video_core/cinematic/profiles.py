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

    DRAFT = "draft"        # Static — fastest render, no motion
    BALANCED = "balanced"  # Simple 3-category motion, linear easing
    CINEMATIC = "cinematic"  # Full 8-type emotion-aware motion, smooth easing
    PREMIUM = "premium"    # Full motion + wider scale range + long easing
    PAN_ONLY = "pan_only"  # Pure pan/drift — no zoom-in or zoom-out, preserves full frame


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
    distribution_targets: dict[str, float] | None = None


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

# Cinematic & Premium: full motion-type library, emotion-tuned. New motion
# types (Cinematic Camera System) are mapped to the emotions where their
# named intent fits best; legacy 8-type entries are kept as the fallback
# family for the acceptable-motions rebalancer.
_CINEMATIC_MAP: dict[str, tuple[str, str]] = {
    "curiosity": ("push_slow", "medium"),
    "wonder": ("drift_float", "small"),
    "reflection": ("pull_reflection", "medium"),
    "mystery": ("push_suspense", "small"),
    "peace": ("hold_breathing", "small"),
    "hope": ("drift_vertical_up", "small"),
    "compassion": ("pull_ending", "medium"),
    "urgency": ("push_hero", "large"),
    "sadness": ("pull_isolation", "medium"),
    "awe": ("push_emotional", "large"),
    "determination": ("push_emotional", "medium"),
    "revelation": ("push_slow", "medium"),
  }

# Balanced: conservative subset of the new motion library layered onto the
# original 3-category set — deliberately excludes macro/hero/reveal_corner
# families, which stay reserved for cinematic/premium.
_BALANCED_MAP: dict[str, tuple[str, str]] = {
    "curiosity": ("push_in", "medium"),
    "wonder": ("pull_out", "medium"),
    "reflection": ("drift_float", "small"),
    "mystery": ("push_in", "small"),
    "peace": ("drift_float", "small"),
    "hope": ("pull_out", "small"),
    "compassion": ("push_in", "small"),
    "urgency": ("push_in", "large"),
    "sadness": ("pull_out", "small"),
    "awe": ("pull_out", "large"),
    "determination": ("push_in", "medium"),
    "revelation": ("drift_float", "small"),
}

# Acceptable-motion sets for the motion-variety rebalancer.
# Each emotion maps to a small ranked set of alternatives appropriate to its
# emotional register.  The rebalancer falls back within the same emotion rather
# than substituting an unrelated motion type.
# Pan-only: all motions are constant-zoom drift/pan — no push-in or pull-out.
# drift       → horizontal pan, zoom = 1.0 + drift_amount (headroom only)
# drift_vertical_up → upward tilt pan, constant zoom
# hold_tripod → very slow lateral drift, near-static (breathing filter, constant z)
_PAN_ONLY_MAP: dict[str, tuple[str, str]] = {
    "curiosity":   ("drift",             "medium"),
    "wonder":      ("drift_vertical_up", "small"),
    "reflection":  ("hold_tripod",       "small"),
    "mystery":     ("drift",             "small"),
    "peace":       ("hold_tripod",       "small"),
    "hope":        ("drift_vertical_up", "small"),
    "compassion":  ("hold_tripod",       "small"),
    "urgency":     ("drift",             "medium"),
    "sadness":     ("hold_tripod",       "small"),
    "awe":         ("drift_vertical_up", "medium"),
    "determination": ("drift",           "medium"),
    "revelation":  ("drift_vertical_up", "small"),
}

_ACCEPTABLE_MOTIONS: dict[str, list[str]] = {
    "curiosity": ["push_slow", "push_in", "push_reveal", "drift_float"],
    "wonder": ["drift_float", "drift_horizon", "pull_out", "pull_wide"],
    "reflection": ["pull_reflection", "pull_ending", "drift", "drift_float"],
    "mystery": ["push_suspense", "push_in", "drift", "hold_breathing"],
    "peace": ["hold_breathing", "hold_tripod", "drift_float", "drift"],
    "hope": ["drift_vertical_up", "drift_float", "pull_out", "push_reveal"],
    "compassion": ["pull_ending", "pull_reflection", "push_slow", "drift"],
    "urgency": ["push_hero", "push_emotional", "push_in", "drift"],
    "sadness": ["pull_isolation", "pull_reflection", "pull_out", "drift"],
    "awe": ["push_emotional", "push_hero", "reveal_window", "pull_wide"],
    "determination": ["push_emotional", "push_hero", "push_in", "drift"],
    "revelation": ["push_slow", "push_reveal", "pull_ending", "drift"],
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
        scale_range_small=(1.0, 1.22),
        scale_range_medium=(1.0, 1.35),
        scale_range_large=(1.0, 1.48),
        drift_amount=0.06,
        easing="ease_in_out",
        motion_map=_CINEMATIC_MAP,
        max_drift_scale_factor=1.2,
        distribution_targets={
            "push": 0.45,
            "pull": 0.20,
            "drift": 0.25,
            "static": 0.10,
        },
    ),
    RenderProfile.PREMIUM: ProfileConfig(
        scale_range_small=(1.0, 1.22),
        scale_range_medium=(1.0, 1.35),
        scale_range_large=(1.0, 1.48),
        drift_amount=0.07,
        easing="ease_in_out",
        motion_map=_CINEMATIC_MAP,
        max_drift_scale_factor=1.2,
        distribution_targets={
            "push": 0.45,
            "pull": 0.20,
            "drift": 0.25,
            "static": 0.10,
        },
    ),
    # Pan-only: drift motions with minimal constant zoom (headroom only).
    # No push-in or pull-out — the full frame composition is always preserved.
    RenderProfile.PAN_ONLY: ProfileConfig(
        scale_range_small=(1.0, 1.08),
        scale_range_medium=(1.0, 1.10),
        scale_range_large=(1.0, 1.12),
        drift_amount=0.08,
        easing="ease_in_out",
        motion_map=_PAN_ONLY_MAP,
        max_drift_scale_factor=1.2,
    ),
}


def get_profile_config(profile: str) -> ProfileConfig:
    """Return ProfileConfig for the given profile name (case-insensitive)."""
    key = profile.lower().strip()
    return _PROFILE_CONFIGS.get(key, _PROFILE_CONFIGS[RenderProfile.BALANCED])
