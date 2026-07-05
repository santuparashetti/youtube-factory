"""Configuration for the Quality Scoring Engine V1."""

from __future__ import annotations

from dataclasses import dataclass, field


# Default category weights — must sum to 1.0
DEFAULT_WEIGHTS: dict[str, float] = {
    "script": 0.10,
    "narration": 0.15,
    "subtitle": 0.10,
    "image": 0.15,
    "motion": 0.10,
    "audio": 0.15,
    "rendering": 0.20,
    "storytelling": 0.05,
}


@dataclass
class QualityScoringConfig:
    """Controls all configurable aspects of the Quality Scoring Engine."""

    # PASS/FAIL and warning thresholds
    publish_threshold: float = 70.0    # overall_score >= this → PASS
    warning_threshold: float = 60.0    # below this → surface a warning
    critical_threshold: float = 50.0   # below this → pipeline should halt

    # Category weights — must sum to 1.0
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    # Per-category minimum score — a category can override the global verdict
    # e.g. {"rendering": 40.0} means rendering < 40 always fails regardless of overall
    category_minimums: dict[str, float] = field(default_factory=dict)

    # Grade scale: minimum score (inclusive) for each grade, descending
    grade_scale: list[tuple[float, str]] = field(
        default_factory=lambda: [
            (95.0, "A+"),
            (90.0, "A"),
            (80.0, "B"),
            (70.0, "C"),
            (60.0, "D"),
            (0.0,  "F"),
        ]
    )

    def letter_grade(self, score: float) -> str:
        for threshold, grade in self.grade_scale:
            if score >= threshold:
                return grade
        return "F"

    def verdict_for(self, overall_score: float, category_scores: dict[str, float]) -> str:
        """Return PASS or FAIL based on overall score and per-category minimums."""
        if overall_score < self.publish_threshold:
            return "FAIL"
        for cat, minimum in self.category_minimums.items():
            cat_score = category_scores.get(cat, 0.0)
            if cat_score < minimum:
                return "FAIL"
        return "PASS"
