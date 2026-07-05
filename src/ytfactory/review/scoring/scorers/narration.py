"""Narration Quality scorer.

Rules evaluated (points budgeted out of 100):
  NARR_001 — non-empty narration per scene        (40 pts)
  NARR_002 — word count per scene in range        (30 pts)
  NARR_003 — no single block > 100 words          (15 pts)
  NARR_004 — avg words per scene >= 10            (15 pts)
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.models import RCAReport
from ytfactory.review.scoring.framework import BaseCategoryScorer
from ytfactory.review.scoring.models import RuleContribution
from ytfactory.review.validation.models import ValidationReport

_POINTS = {
    "NARR_001": 40.0,
    "NARR_002": 30.0,
    "NARR_003": 15.0,
    "NARR_004": 15.0,
}


class NarrationScorer(BaseCategoryScorer):
    category = "narration"
    default_weight = 0.15

    def _score_category(
        self,
        project_dir: Path,
        scenes: list[dict],
        validation_report: ValidationReport,
        rca_report: RCAReport,
        context: dict,
    ) -> list[RuleContribution]:
        results = self._results_for(validation_report)
        return [
            self._contribute(rule_id, pts, results) for rule_id, pts in _POINTS.items()
        ]
