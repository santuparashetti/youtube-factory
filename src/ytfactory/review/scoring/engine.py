"""Quality Scoring Engine V1 — orchestrator.

Runs all 8 category scorers, computes the overall weighted score,
assigns a letter grade, determines PASS / FAIL, and generates
improvement recommendations.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from ytfactory.review.rca.models import RCAReport
from ytfactory.review.scoring.config import QualityScoringConfig
from ytfactory.review.scoring.framework import BaseCategoryScorer
from ytfactory.review.scoring.models import CategoryScore, QualityScoreReport
from ytfactory.review.scoring.scorers.audio import AudioScorer
from ytfactory.review.scoring.scorers.image import ImageScorer
from ytfactory.review.scoring.scorers.motion import MotionScorer
from ytfactory.review.scoring.scorers.narration import NarrationScorer
from ytfactory.review.scoring.scorers.rendering import RenderingScorer
from ytfactory.review.scoring.scorers.script import ScriptScorer
from ytfactory.review.scoring.scorers.storytelling import StorytellingScorer
from ytfactory.review.scoring.scorers.subtitle import SubtitleScorer
from ytfactory.review.validation.models import ValidationReport


class QualityScoringEngine:
    """Orchestrate all category scorers and produce a QualityScoreReport.

    Usage:
        engine = QualityScoringEngine()
        report = engine.score(project_dir, scenes, val_report, rca_report, context)
    """

    def __init__(self, config: QualityScoringConfig | None = None) -> None:
        self._config = config or QualityScoringConfig()
        self._scorers: list[BaseCategoryScorer] = [
            ScriptScorer(self._config),
            NarrationScorer(self._config),
            SubtitleScorer(self._config),
            ImageScorer(self._config),
            MotionScorer(self._config),
            AudioScorer(self._config),
            RenderingScorer(self._config),
            StorytellingScorer(self._config),
        ]

    # ── Public API ────────────────────────────────────────────────────────

    def score(
        self,
        project_dir: Path,
        scenes: list[dict],
        validation_report: ValidationReport,
        rca_report: RCAReport,
        context: dict,
    ) -> QualityScoreReport:
        """Run all scorers and return a complete QualityScoreReport."""
        t0 = time.perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()

        category_scores: dict[str, CategoryScore] = {}
        for scorer in self._scorers:
            try:
                cat_score = scorer.score(
                    project_dir, scenes, validation_report, rca_report, context
                )
                category_scores[cat_score.category] = cat_score
            except Exception:
                pass  # one broken scorer must not stop the others

        overall_score = _weighted_average(category_scores)
        letter_grade = self._config.letter_grade(overall_score)
        cat_raw = {k: v.raw_score for k, v in category_scores.items()}
        verdict = self._config.verdict_for(overall_score, cat_raw)
        recommendations = _recommendations(category_scores, self._config)

        elapsed = time.perf_counter() - t0

        return QualityScoreReport(
            project_id=validation_report.project_id,
            timestamp=timestamp,
            category_scores=category_scores,
            overall_score=round(overall_score, 2),
            letter_grade=letter_grade,
            verdict=verdict,
            publish_threshold=self._config.publish_threshold,
            warning_threshold=self._config.warning_threshold,
            critical_threshold=self._config.critical_threshold,
            improvement_recommendations=recommendations,
            processing_time_seconds=round(elapsed, 3),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _weighted_average(category_scores: dict[str, CategoryScore]) -> float:
    """Return the sum of each category's weighted_score."""
    if not category_scores:
        return 0.0
    total_weight = sum(cs.weight for cs in category_scores.values())
    if total_weight <= 0:
        return 0.0
    total_weighted = sum(cs.weighted_score for cs in category_scores.values())
    # Normalise in case weights don't sum to exactly 1.0; weighted_score is already
    # on the 0-100 scale (raw_score * weight), so no further multiplication needed
    return total_weighted / total_weight


def _recommendations(
    category_scores: dict[str, CategoryScore],
    config: QualityScoringConfig,
) -> list[str]:
    """Return up to 5 improvement recommendations sorted by impact."""
    impact = sorted(
        category_scores.items(),
        key=lambda kv: kv[1].weight * (100.0 - kv[1].raw_score),
        reverse=True,
    )
    recs: list[str] = []
    for cat, cs in impact:
        if cs.raw_score >= 80:
            continue
        if cs.raw_score < 50:
            level = "critical"
        elif cs.raw_score < 70:
            level = "poor"
        else:
            level = "fair"
        rule_hint = (
            f"; address: {', '.join(cs.failed_rules[:2])}" if cs.failed_rules else ""
        )
        recs.append(
            f"{cat.title()} quality is {level} ({cs.raw_score:.0f}/100){rule_hint}"
        )
        if len(recs) >= 5:
            break
    return recs
