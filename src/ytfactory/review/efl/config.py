"""Configuration for the Engine Feedback Loop V1."""

from __future__ import annotations

from dataclasses import dataclass, field

# Priority levels in descending order of severity
PRIORITY_LEVELS: list[str] = ["critical", "high", "medium", "low"]

# Canonical engine names as defined in the EFL V1 specification
ENGINE_TARGETS: list[str] = [
    "Research Engine",
    "Script Generation Engine",
    "Script Pacing Engine",
    "Speech Optimizer",
    "TTS Engine",
    "Scene Planner",
    "Image Prompt Engine",
    "Image Generation Engine",
    "Motion Engine",
    "ASS Subtitle Engine",
    "Video Renderer",
    "Video Quality Review Engine",
]

# Maps RCA primary_engine strings to canonical EFL engine targets
ENGINE_NORMALIZATION: dict[str, str] = {
    "ScriptWriter": "Script Generation Engine",
    "Script Generation Engine": "Script Generation Engine",
    "Script Pacing Engine": "Script Pacing Engine",
    "TTS Engine": "TTS Engine",
    "VoiceGenerator": "TTS Engine",
    "Speech Optimizer": "Speech Optimizer",
    "ASS Subtitle Engine": "ASS Subtitle Engine",
    "CaptionGenerator": "ASS Subtitle Engine",
    "Image Prompt Engine": "Image Prompt Engine",
    "ImageGenerator": "Image Generation Engine",
    "Image Generation Engine": "Image Generation Engine",
    "Scene Planner": "Scene Planner",
    "Motion Engine": "Motion Engine",
    "Video Renderer": "Video Renderer",
    "VideoRenderer": "Video Renderer",
    "Research Engine": "Research Engine",
    "Video Quality Review Engine": "Video Quality Review Engine",
    "Review Engine": "Video Quality Review Engine",
}

# How priorities map to the next level up when escalating
_ESCALATION_MAP: dict[str, str] = {
    "low": "medium",
    "medium": "high",
    "high": "critical",
    "critical": "critical",
}


def normalize_engine(engine: str) -> str:
    """Map any RCA engine string to the canonical EFL engine target name."""
    return ENGINE_NORMALIZATION.get(engine, engine)


def escalate_priority(priority: str) -> str:
    """Bump a priority up one level (recurring issue escalation)."""
    return _ESCALATION_MAP.get(priority, priority)


def severity_to_priority(severity: str) -> str:
    """Convert a validation/RCA severity to an EFL priority level."""
    return severity if severity in PRIORITY_LEVELS else "medium"


@dataclass
class EFLConfig:
    """Controls all configurable aspects of the Engine Feedback Loop."""

    enabled: bool = True

    # Whether to generate feedback from WARNING-status issues (in addition to FAILs)
    include_warnings: bool = True

    # Suppress feedback below this confidence threshold (0–100)
    min_confidence_to_report: int = 0

    # Category quality-score threshold — below this, generate feedback even if
    # the RCA found no matching issues (ensures gaps are surfaced)
    category_score_feedback_threshold: float = 60.0

    # Issues recurring >= this many times across scenes get priority escalated
    recurring_escalation_threshold: int = 2

    # Per-rule overrides: rule_id → {"enabled": bool}
    rule_overrides: dict[str, dict] = field(default_factory=dict)

    def is_rule_enabled(self, rule_id: str) -> bool:
        override = self.rule_overrides.get(rule_id, {})
        return override.get("enabled", True)
