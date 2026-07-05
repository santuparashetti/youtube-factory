"""Image Quality scorer.

Rules evaluated (points budgeted out of 100):
  IMG_001 — image file exists per scene           (35 pts)
  IMG_002 — image size >= 1 KB                    (20 pts)
  IMG_003 — visual_prompt present per scene       (20 pts)
  IMG_004 — no repeated visual prompts            (10 pts)
  IMG_005 — shot_type assigned                    ( 5 pts)
  IMG_006 — style markers in prompt               (10 pts)
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.models import RCAReport
from ytfactory.review.scoring.framework import BaseCategoryScorer
from ytfactory.review.scoring.models import RuleContribution
from ytfactory.review.validation.models import ValidationReport

_POINTS = {
    "IMG_001": 35.0,
    "IMG_002": 20.0,
    "IMG_003": 20.0,
    "IMG_004": 10.0,
    "IMG_005":  5.0,
    "IMG_006": 10.0,
}


class ImageScorer(BaseCategoryScorer):
    category = "image"
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
            self._contribute(rule_id, pts, results)
            for rule_id, pts in _POINTS.items()
        ]
