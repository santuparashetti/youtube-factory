"""Audio Quality scorer.

Rules evaluated (points budgeted out of 100):
  AUD_001 — audio file exists per scene           (45 pts)
  AUD_002 — audio size >= 1 KB                    (25 pts)
  AUD_003 — audio size >= 5 KB (speech heuristic) (20 pts)
  AUD_004 — voice clarity analysis                (10 pts)  always SKIP (no librosa)
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.models import RCAReport
from ytfactory.review.scoring.framework import BaseCategoryScorer
from ytfactory.review.scoring.models import RuleContribution
from ytfactory.review.validation.models import ValidationReport

_POINTS = {
    "AUD_001": 45.0,
    "AUD_002": 25.0,
    "AUD_003": 20.0,
    "AUD_004": 10.0,
}


class AudioScorer(BaseCategoryScorer):
    category = "audio"
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
