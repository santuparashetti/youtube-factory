"""Configuration for the per-scene Image Review Engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EscalationConfig:
    """Controls the tier-escalation and prompt-refinement threshold policy."""

    target_quality_score: float = 9.2
    retry_threshold: float = 8.5
    premium_model_threshold: float = 8.5
    max_prompt_refinements: int = 1
    max_model_escalations: int = 2

    @classmethod
    def from_settings(cls, settings: object) -> "EscalationConfig":
        """Build from a Settings instance (duck-typed for testability)."""
        return cls(
            target_quality_score=float(getattr(settings, "image_escalation_target_quality_score", 9.2)),
            retry_threshold=float(getattr(settings, "image_escalation_retry_threshold", 8.5)),
            premium_model_threshold=float(getattr(settings, "image_escalation_premium_model_threshold", 8.5)),
            max_prompt_refinements=int(getattr(settings, "image_escalation_max_prompt_refinements", 1)),
            max_model_escalations=int(getattr(settings, "image_escalation_max_model_escalations", 2)),
        )


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
    target_quality_score: float = 85.0
    # ADR-0015: staged Human Subject QA Gate
    human_qa_enabled: bool = True
    # Check for visible hands in scenes where hand-avoidance composition was applied.
    hand_avoidance_check_enabled: bool = True
    # Anatomy hard-floor defense-in-depth: if anatomy sub-score is below this,
    # the composite is capped at anatomy_quality_cap regardless of other sub-scores.
    anatomy_floor_threshold: float = 6.0
    anatomy_quality_cap: float = 6.0

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
            target_quality_score=getattr(settings, "image_review_target_quality_score", 85.0),
            human_qa_enabled=getattr(settings, "image_human_qa_enabled", True),
            hand_avoidance_check_enabled=getattr(settings, "image_hand_avoidance_check_enabled", True),
            anatomy_floor_threshold=getattr(settings, "image_review_anatomy_floor_threshold", 6.0),
            anatomy_quality_cap=getattr(settings, "image_review_anatomy_quality_cap", 6.0),
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
