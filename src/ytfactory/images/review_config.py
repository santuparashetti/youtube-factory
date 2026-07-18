"""Configuration for the per-scene Image Review Engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ImageReviewConfig:
    """Controls image review behaviour during generation.

    All thresholds map directly to the spec pass criteria:
      - score >= min_score
      - confidence >= min_confidence
      - no HIGH severity issues
      - maximum one MEDIUM issue
    """

    enabled: bool = False
    provider: str = "local"
    local_model: str = "minicpm_v2_6"
    min_score: float = 90.0
    min_confidence: float = 80.0
    max_attempts: int = 3
    auto_remediate: bool = True
    debug: bool = False
    # ADR-0015: staged Human Subject QA Gate
    human_qa_enabled: bool = True

    @classmethod
    def from_settings(cls, settings: object) -> "ImageReviewConfig":
        """Build from a Settings instance (duck-typed for testability)."""
        return cls(
            enabled=getattr(settings, "image_review_enabled", False),
            provider=getattr(settings, "vision_review_provider", "local"),
            local_model=getattr(settings, "vision_review_local_model", "minicpm_v2_6"),
            min_score=getattr(settings, "image_review_min_score", 90.0),
            min_confidence=getattr(settings, "image_review_confidence", 80.0),
            max_attempts=int(getattr(settings, "image_review_max_attempts", 3)),
            auto_remediate=getattr(settings, "image_review_auto_remediate", True),
            debug=getattr(settings, "image_review_debug", False),
            human_qa_enabled=getattr(settings, "image_human_qa_enabled", True),
        )

    def passes(
        self,
        score: float,
        confidence: float,
        high_count: int,
        medium_count: int,
    ) -> bool:
        """Return True when all pass criteria are satisfied."""
        return (
            score >= self.min_score
            and confidence >= self.min_confidence
            and high_count == 0
            and medium_count <= 1
        )
