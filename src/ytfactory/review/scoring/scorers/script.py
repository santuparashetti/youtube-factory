"""Script Quality scorer.

Rules evaluated (points budgeted out of 100):
  SCRIPT_001 — script exists and is non-empty     (40 pts)
  SCRIPT_002 — word count within range            (25 pts)
  SCRIPT_003 — no repeated paragraphs             (15 pts)
  SCRIPT_004 — minimum sentence count             (12 pts)
  SCRIPT_005 — sufficient content lines           ( 8 pts)
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.models import RCAReport
from ytfactory.review.scoring.framework import BaseCategoryScorer
from ytfactory.review.scoring.models import RuleContribution
from ytfactory.review.validation.models import ValidationReport

_POINTS = {
    "SCRIPT_001": 40.0,
    "SCRIPT_002": 25.0,
    "SCRIPT_003": 15.0,
    "SCRIPT_004": 12.0,
    "SCRIPT_005": 8.0,
}


class ScriptScorer(BaseCategoryScorer):
    category = "script"
    default_weight = 0.10

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
