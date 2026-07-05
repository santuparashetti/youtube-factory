"""Configuration for Auto Remediation Engine V1."""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Strategy constants ─────────────────────────────────────────────────────────

# All supported remediation strategies (cheapest → most expensive)
STRATEGIES: list[str] = [
    "retry_validation",  # re-run validation only, no regeneration
    "regenerate_subtitles",  # delete and re-generate subtitle files
    "regenerate_audio",  # delete and re-generate audio + timing
    "regenerate_image",  # delete and re-generate scene image
    "regenerate_video_clip",  # delete and re-render scene video clip
    "full_regeneration",  # last resort: wipe all artifacts and rebuild
]

# Maps EFL canonical engine names to the cheapest adequate strategy
ENGINE_STRATEGY_MAP: dict[str, str] = {
    "Research Engine": "retry_validation",
    "Script Generation Engine": "retry_validation",
    "Script Pacing Engine": "retry_validation",
    "Scene Planner": "retry_validation",
    "Speech Optimizer": "regenerate_audio",
    "TTS Engine": "regenerate_audio",
    "Image Prompt Engine": "regenerate_image",
    "Image Generation Engine": "regenerate_image",
    "Motion Engine": "regenerate_video_clip",
    "ASS Subtitle Engine": "regenerate_subtitles",
    "Video Renderer": "regenerate_video_clip",
    "Video Quality Review Engine": "retry_validation",
}

# Maps validation category to a fallback strategy when engine mapping is absent
CATEGORY_STRATEGY_MAP: dict[str, str] = {
    "script": "retry_validation",
    "narration": "regenerate_audio",
    "audio": "regenerate_audio",
    "subtitle": "regenerate_subtitles",
    "image": "regenerate_image",
    "motion": "regenerate_video_clip",
    "rendering": "regenerate_video_clip",
    "story": "retry_validation",
}

# Strategy cost estimates in relative units (not real USD — used for comparison)
STRATEGY_COST: dict[str, float] = {
    "retry_validation": 0.0,
    "regenerate_subtitles": 0.1,
    "regenerate_audio": 0.5,
    "regenerate_image": 1.0,
    "regenerate_video_clip": 0.3,
    "full_regeneration": 10.0,
}


@dataclass
class RemediationConfig:
    """All tunable knobs for the Auto Remediation Engine V1."""

    # ── Quality gate ──────────────────────────────────────────────────────────
    quality_threshold: float = 70.0  # stop when overall score ≥ this
    min_confidence: int = 60  # skip actions for issues below this

    # ── Retry limits ──────────────────────────────────────────────────────────
    max_retries: int = 3  # maximum remediation cycles before giving up

    # ── Cost guard ────────────────────────────────────────────────────────────
    max_cost_estimate: float = 20.0  # stop if total estimated cost exceeds this

    # ── Scope control ─────────────────────────────────────────────────────────
    # Only remediate issues at these severities (subset of critical|high|medium|low)
    remediate_severities: list[str] = field(
        default_factory=lambda: ["critical", "high"]
    )

    # ── Execution control ─────────────────────────────────────────────────────
    dry_run: bool = False  # plan only — do not execute or re-validate
    require_approval: bool = False  # print plan and prompt for Y/N before executing

    # ── Safety ────────────────────────────────────────────────────────────────
    enable_rollback: bool = True  # back up artifacts before deleting them
    allow_full_regeneration: bool = False  # permit full_regeneration as last resort
