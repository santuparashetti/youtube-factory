"""Subtitle Quality scorer.

Rules evaluated (points budgeted out of 100):
  SUBT_001 — SRT file exists per scene            (35 pts)
  SUBT_002 — no timestamp overlaps                (25 pts)
  SUBT_003 — reading speed within CPS limit       (15 pts)
  SUBT_004 — chars per line within limit          (10 pts)
  SUBT_005 — no empty subtitle cues              (10 pts)
  SUBT_006 — subtitle/narration word overlap       ( 5 pts)
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.models import RCAReport
from ytfactory.review.scoring.framework import BaseCategoryScorer
from ytfactory.review.scoring.models import RuleContribution
from ytfactory.review.validation.models import ValidationReport

_POINTS = {
    "SUBT_001": 35.0,
    "SUBT_002": 25.0,
    "SUBT_003": 15.0,
    "SUBT_004": 10.0,
    "SUBT_005": 10.0,
    "SUBT_006":  5.0,
}


class SubtitleScorer(BaseCategoryScorer):
    category = "subtitle"
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
