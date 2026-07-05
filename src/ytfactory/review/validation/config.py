"""Configuration for Video Validation Rules V1.

Every rule supports:
  - enable/disable (per-rule or globally)
  - severity override
  - threshold override
  - project-specific configuration via the `rules` dict
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RuleConfig:
    """Per-rule override settings."""

    enabled: bool = True
    severity: str | None = None  # None = use rule default
    threshold: float | None = None  # None = use rule default

    def severity_or(self, default: str) -> str:
        return self.severity if self.severity is not None else default

    def threshold_or(self, default: float) -> float:
        return self.threshold if self.threshold is not None else default


@dataclass
class ValidationRulesConfig:
    """All configuration for the Video Validation Rules V1 framework.

    Pass a populated `rules` dict to override individual rules, e.g.::

        cfg = ValidationRulesConfig(rules={"SCRIPT_002": RuleConfig(enabled=False)})
    """

    # Global switch — False disables all rules without changing per-rule state
    enabled: bool = True

    # Per-rule overrides (key = rule_id, e.g. "SCRIPT_001")
    rules: dict[str, RuleConfig] = field(default_factory=dict)

    # ── Script ───────────────────────────────────────────────────────────
    script_min_words: int = 200
    script_max_words: int = 5000
    script_min_sentences: int = 3
    script_paragraph_similarity_threshold: float = 0.8  # Jaccard

    # ── Narration (per scene) ─────────────────────────────────────────────
    narration_min_words: int = 5
    narration_max_words: int = 300
    narration_max_single_block_words: int = 100

    # ── Subtitle ─────────────────────────────────────────────────────────
    subtitle_max_cps: float = 18.0  # characters per second
    subtitle_max_chars_per_line: int = 42
    subtitle_narration_overlap_threshold: float = 0.3  # Jaccard minimum

    # ── Image ─────────────────────────────────────────────────────────────
    image_min_size_bytes: int = 1_000
    image_prompt_similarity_threshold: float = 0.5  # Jaccard for dupe detection
    image_style_markers: list[str] = field(
        default_factory=lambda: [
            "cinematic",
            "realistic",
            "documentary",
            "photorealistic",
            "high quality",
            "4k",
            "sharp focus",
            "detailed",
            "professional",
            "high resolution",
            "dramatic",
            "natural lighting",
        ]
    )

    # ── Motion ────────────────────────────────────────────────────────────
    motion_min_scene_duration_seconds: float = 2.0
    motion_max_scene_duration_seconds: float = 120.0

    # ── Audio ─────────────────────────────────────────────────────────────
    audio_min_size_bytes: int = 1_000
    audio_short_clip_bytes: int = 5_000  # size proxy for clips likely < 1s

    # AUD_005: Quiet start detection — measures first 300 ms vs rest of clip.
    # Flag if opening section is more than this many dB quieter than the rest.
    audio_quiet_start_threshold_db: float = 6.0
    # Duration of the "opening window" to check (seconds)
    audio_quiet_start_window_seconds: float = 0.3

    # ── Rendering ─────────────────────────────────────────────────────────
    rendering_min_clip_size_bytes: int = 10_000
    rendering_min_final_size_bytes: int = 100_000

    # REND_006: Black-frame detection
    # Minimum consecutive black duration (seconds) before a segment is flagged.
    rendering_black_frame_min_duration: float = 0.1  # 100 ms
    # Fraction of each frame that must be black to count as a "black frame".
    rendering_black_frame_pic_threshold: float = 0.98
    # Seconds to skip at the start of each clip — covers intentional fade-in.
    rendering_black_frame_skip_start_seconds: float = 1.0
    # Seconds to skip at the end of each clip — covers intentional fade-out.
    rendering_black_frame_skip_end_seconds: float = 1.0

    # ── Story ─────────────────────────────────────────────────────────────
    story_min_scenes: int = 3
    story_max_scenes: int = 50

    # ── Pass policy ───────────────────────────────────────────────────────
    fail_on_warnings: bool = False

    # ── Rule config helpers ───────────────────────────────────────────────

    def get_rule(self, rule_id: str) -> RuleConfig:
        return self.rules.get(rule_id, RuleConfig())

    def is_enabled(self, rule_id: str) -> bool:
        return self.enabled and self.get_rule(rule_id).enabled

    def severity_for(self, rule_id: str, default: str) -> str:
        return self.get_rule(rule_id).severity_or(default)

    def threshold_for(self, rule_id: str, default: float) -> float:
        return self.get_rule(rule_id).threshold_or(default)
