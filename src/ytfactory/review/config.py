"""Review engine configuration — thresholds and pass/fail policy."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReviewConfig:
    """All tunable knobs for the Video Quality Review Engine V1.

    Attributes intentionally named to serve as extension points for future
    Quality Scoring Engine and Root Cause Analysis Engine.
    """

    # ── Scene constraints ─────────────────────────────────────────────────
    min_scenes: int = 3
    max_scenes: int = 50
    min_scene_duration_seconds: float = 2.0
    max_scene_duration_seconds: float = 120.0

    # ── Duration constraints ──────────────────────────────────────────────
    min_total_duration_seconds: float = 60.0
    max_total_duration_seconds: float = 3600.0

    # ── Asset constraints ─────────────────────────────────────────────────
    min_image_size_bytes: int = 1_000  # 1 KB — catches 0-byte stubs
    min_audio_size_bytes: int = 1_000
    min_video_size_bytes: int = 10_000  # 10 KB — per-scene clip
    min_final_video_size_bytes: int = 100_000  # 100 KB — final.mp4

    # ── Content constraints ───────────────────────────────────────────────
    min_narration_words: int = 5

    # ── Pass / Fail policy ────────────────────────────────────────────────
    # FAIL only on errors; warnings alone → PASS
    fail_on_warnings: bool = False

    # ── Extension points (consumed by future Quality Scoring Engine) ──────
    quality_score_pass_threshold: float = 0.7

    # ── Stage weights (reserved for future Quality Scoring Engine) ────────
    stage_weights: dict[str, float] = field(
        default_factory=lambda: {
            "asset_integrity": 0.35,
            "timeline": 0.20,
            "content": 0.25,
            "production_quality": 0.20,
        }
    )
