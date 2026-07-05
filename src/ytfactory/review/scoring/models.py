"""Domain models for the Quality Scoring Engine V1.

Every scoring category produces a CategoryScore; the engine aggregates
them into a QualityScoreReport with an overall score, grade, and verdict.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class RuleContribution:
    """Points contributed by a single validation rule to a category score."""

    rule_id: str
    points_available: float     # max points this rule can award
    points_earned: float        # actual points awarded (0..points_available)
    status: str                 # "pass" | "partial" | "fail" | "warning" | "skip" | "absent"
    evidence: str               # human-readable explanation

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CategoryScore:
    """Quality score for a single scoring category (0–100)."""

    category: str               # "script" | "narration" | "subtitle" | "image" |
    #                           #   "motion" | "audio" | "rendering" | "storytelling"
    raw_score: float            # 0–100 unweighted
    weighted_score: float       # raw_score * weight
    weight: float               # fraction of overall score (0.0–1.0)
    confidence: float           # 0.0–1.0: 1.0 = all rules ran with full data
    evidence: list[str]         # items explaining why points were lost
    summary: str                # one-line human-readable verdict
    failed_rules: list[str]     # rule IDs whose checks reduced the score
    contributions: list[RuleContribution] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "raw_score": round(self.raw_score, 2),
            "weighted_score": round(self.weighted_score, 2),
            "weight": self.weight,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
            "summary": self.summary,
            "failed_rules": self.failed_rules,
            "contributions": [c.to_dict() for c in self.contributions],
        }


@dataclass
class QualityScoreReport:
    """Top-level Quality Scoring Engine V1 report."""

    project_id: str
    timestamp: str

    # Per-category scores, keyed by category name
    category_scores: dict[str, CategoryScore] = field(default_factory=dict)

    # Overall
    overall_score: float = 0.0          # 0–100 weighted average
    letter_grade: str = "F"             # A+, A, B, C, D, F
    verdict: str = "FAIL"               # PASS | FAIL

    # Thresholds used for this run
    publish_threshold: float = 70.0
    warning_threshold: float = 60.0
    critical_threshold: float = 50.0

    # Diagnostics
    improvement_recommendations: list[str] = field(default_factory=list)
    processing_time_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "version": "v1",
            "project_id": self.project_id,
            "timestamp": self.timestamp,
            "overall_score": round(self.overall_score, 2),
            "letter_grade": self.letter_grade,
            "verdict": self.verdict,
            "publish_threshold": self.publish_threshold,
            "warning_threshold": self.warning_threshold,
            "critical_threshold": self.critical_threshold,
            "category_scores": {k: v.to_dict() for k, v in self.category_scores.items()},
            "improvement_recommendations": self.improvement_recommendations,
            "processing_time_seconds": self.processing_time_seconds,
        }
