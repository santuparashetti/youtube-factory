"""Motion Quality scorer.

Rules evaluated (points budgeted out of 100):
  MOT_002 — duration > 0 per scene                (35 pts)  checked first
  MOT_001 — duration in valid range               (30 pts)
  MOT_004 — transition assigned per scene         (20 pts)
  MOT_003 — shot_type assigned per scene          (15 pts)
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.models import RCAReport
from ytfactory.review.scoring.framework import BaseCategoryScorer
from ytfactory.review.scoring.models import RuleContribution
from ytfactory.review.validation.models import ValidationReport

_POINTS = {
    "MOT_002": 35.0,
    "MOT_001": 30.0,
    "MOT_004": 20.0,
    "MOT_003": 15.0,
}


class MotionScorer(BaseCategoryScorer):
    category = "motion"
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
            self._contribute(rule_id, pts, results)
            for rule_id, pts in _POINTS.items()
        ]
