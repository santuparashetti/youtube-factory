"""CTA Overlay Engine — data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CTAVariant(str, Enum):
    """Whether the full or compact CTA is rendered."""

    FULL = "full"  # full panel, 6s target — only when pause ≥ min_pause_ms_for_full_cta
    COMPACT = "compact"  # corner badge, shorter cycle — used when pause is shorter or on fallback


class PlacementPath(str, Enum):
    """Which code path determined the CTA timestamp."""

    PRIMARY_CONTEXTUAL = "primary_contextual"  # insight-tier pause found, subtitle-safe
    FALLBACK_TIMING = "fallback_timing"  # no safe pause found → fixed fallback_timing %
    POST_HOOK = "post_hook"  # placed immediately after scene 1 (hook) ends


class CTAZone(str, Enum):
    """Allowed safe placement zones for the CTA overlay."""

    BOTTOM_CENTER = "bottom_center"
    UPPER_LEFT = "upper_left"
    UPPER_RIGHT = "upper_right"


@dataclass
class CTAPlacement:
    """Complete description of where and how the CTA is placed."""

    timestamp: float  # seconds — start of CTA in final video
    duration: float  # seconds — total CTA display duration
    variant: CTAVariant
    placement_path: PlacementPath
    subtitle_safe: bool  # True when placement checked clear of subtitle region
    zone: CTAZone  # spatial position in the video frame
    pause_type: str | None  # PauseType value from vad.py, or None for fallback
    pause_duration: float = 0.0  # seconds — length of the underlying pause
    cta_end: float = 0.0  # convenience: timestamp + duration

    def __post_init__(self) -> None:
        self.cta_end = self.timestamp + self.duration


@dataclass
class CTARenderResult:
    """Result of a single overlay render attempt."""

    success: bool
    output_path: str = ""
    error: str = ""
    template_used: str = ""
    retry_count: int = 0


@dataclass
class CTAReviewResult:
    """Outcome of CTA validation (spec: 3-step escalation)."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    retry_count: int = 0
    fallback_template: str | None = None
    reason_code: str | None = None  # populated when CTA blocks the pipeline

    # Detailed checks
    timing_valid: bool = True
    subtitle_safe: bool = True
    branding_loaded: bool = True
    animation_completed: bool = True
    bgm_duck_applied: bool = False


@dataclass
class CTAResult:
    """Top-level result returned by CTAPipeline.run()."""

    success: bool
    enabled: bool
    placement: CTAPlacement | None
    review: CTAReviewResult
    output_video: str = ""
    timing_metadata_path: str = ""
    review_report_path: str = ""

    def to_dict(self) -> dict:
        p = self.placement
        return {
            "success": self.success,
            "enabled": self.enabled,
            "output_video": self.output_video,
            "timing_metadata": (
                {
                    "timestamp": p.timestamp,
                    "duration": p.duration,
                    "cta_end": p.cta_end,
                    "variant": p.variant.value,
                    "placement_path": p.placement_path.value,
                    "subtitle_safe": p.subtitle_safe,
                    "zone": p.zone.value,
                    "pause_type": p.pause_type,
                    "pause_duration": p.pause_duration,
                }
                if p
                else None
            ),
            "review": {
                "passed": self.review.passed,
                "errors": self.review.errors,
                "warnings": self.review.warnings,
                "retry_count": self.review.retry_count,
                "fallback_template": self.review.fallback_template,
                "reason_code": self.review.reason_code,
                "timing_valid": self.review.timing_valid,
                "subtitle_safe": self.review.subtitle_safe,
                "branding_loaded": self.review.branding_loaded,
                "animation_completed": self.review.animation_completed,
                "bgm_duck_applied": self.review.bgm_duck_applied,
            },
        }
