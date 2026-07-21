from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EmotionalIntensity(Enum):
    NORMAL = "normal"
    EMOTIONAL = "emotional"
    PEAK = "peak"
    REFLECTION = "reflection"


@dataclass
class ScriptSegment:
    text: str
    start_time: float | None = None
    end_time: float | None = None
    is_hook: bool = False
    is_rehook: bool = False
    is_frame_label: bool = False
    is_bridge: bool = False
    resolves_story: bool = False
    emotional_intensity: EmotionalIntensity = EmotionalIntensity.NORMAL


@dataclass
class RetentionScoreResult:
    total: float
    breakdown: dict[str, float]
    violations: list[str]
    passed: bool


@dataclass
class PostRenderFindings:
    static_shot_violations: list[tuple[float, float]] = field(default_factory=list)
    text_overlay_violations: list[tuple[float, float, str]] = field(default_factory=list)
    missing_hold_violations: list[tuple[float, float]] = field(default_factory=list)
    rehook_gap_violations: list[tuple[float, float]] = field(default_factory=list)
    frame_naming_violations: list[tuple[float, float]] = field(default_factory=list)
