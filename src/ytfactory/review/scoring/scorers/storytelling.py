"""Storytelling Quality scorer.

Storytelling covers narrative structure across scenes.  It consumes the
``story`` validation category results.

Rules evaluated (points budgeted out of 100):
  STOR_004 — unique narration per scene           (30 pts)
  STOR_001 — sequential 1-based scene indices     (20 pts)
  STOR_002 — scene count in valid range           (20 pts)
  STOR_005 — opening scene has >= 10 word narration (15 pts)
  STOR_003 — unique scene titles                  (15 pts)
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.models import RCAReport
from ytfactory.review.scoring.framework import BaseCategoryScorer
from ytfactory.review.scoring.models import RuleContribution
from ytfactory.review.validation.models import ValidationReport

_POINTS = {
    "STOR_004": 30.0,
    "STOR_001": 20.0,
    "STOR_002": 20.0,
    "STOR_005": 15.0,
    "STOR_003": 15.0,
}


class StorytellingScorer(BaseCategoryScorer):
    category = "storytelling"
    default_weight = 0.05

    def _score_category(
        self,
        project_dir: Path,
        scenes: list[dict],
        validation_report: ValidationReport,
        rca_report: RCAReport,
        context: dict,
    ) -> list[RuleContribution]:
        # Story rules live under the "story" validation category
        results = self._results_for(validation_report, category="story")
        return [
            self._contribute(rule_id, pts, results) for rule_id, pts in _POINTS.items()
        ]
