"""Rendering Quality scorer.

Rules evaluated (points budgeted out of 100):
  REND_003 — final.mp4 exists                     (40 pts)
  REND_001 — per-scene clip exists                (25 pts)
  REND_004 — final.mp4 size >= 100 KB             (20 pts)
  REND_002 — per-scene clip size >= 10 KB         (10 pts)
  REND_005 — all expected clips present           ( 5 pts)
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.models import RCAReport
from ytfactory.review.scoring.framework import BaseCategoryScorer
from ytfactory.review.scoring.models import RuleContribution
from ytfactory.review.validation.models import ValidationReport

_POINTS = {
    "REND_003": 40.0,
    "REND_001": 25.0,
    "REND_004": 20.0,
    "REND_002": 10.0,
    "REND_005": 5.0,
    "REND_007": 10.0,
}


class RenderingScorer(BaseCategoryScorer):
    category = "rendering"
    default_weight = 0.20

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
