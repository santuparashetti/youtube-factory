"""Base class and helpers for Quality Scoring Engine V1 category scorers.

Every concrete scorer inherits BaseCategoryScorer and implements _score_category(),
which returns a list of RuleContributions.  The base class aggregates them into a
fully-formed CategoryScore.

Scoring model
─────────────
Each rule is assigned a fixed ``points_available`` budget (summing to 100 per
category).  The fraction of checks that pass determines ``points_earned``:

  * PASS check     → full points for that check
  * WARNING check  → half points
  * FAIL check     → zero points
  * SKIP check     → excluded from denominator (neutral, reduces confidence)
  * no results     → treated as absent (neutral, like SKIP)

  raw_score = sum(earned) / sum(available_non_skip) * 100
  confidence = non_skip_checks / total_checks
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ytfactory.review.rca.models import RCAReport
from ytfactory.review.scoring.config import QualityScoringConfig
from ytfactory.review.scoring.models import CategoryScore, RuleContribution
from ytfactory.review.validation.models import ValidationReport, ValidationResult


class BaseCategoryScorer(ABC):
    """Abstract base for per-category quality scorers."""

    category: str = "unknown"
    default_weight: float = 0.10

    def __init__(self, config: QualityScoringConfig) -> None:
        self._config = config

    # ── Public API ────────────────────────────────────────────────────────

    def score(
        self,
        project_dir: Path,
        scenes: list[dict],
        validation_report: ValidationReport,
        rca_report: RCAReport,
        context: dict,
    ) -> CategoryScore:
        """Produce a CategoryScore for this category."""
        weight = self._config.weights.get(self.category, self.default_weight)

        try:
            contributions = self._score_category(
                project_dir, scenes, validation_report, rca_report, context
            )
        except Exception as exc:
            contributions = [
                RuleContribution(
                    rule_id="SCORE_ERROR",
                    points_available=100.0,
                    points_earned=0.0,
                    status="skip",
                    evidence=f"Scorer raised an exception: {exc}",
                )
            ]

        raw_score, confidence, evidence, failed_rules = self._aggregate(contributions)
        weighted_score = round(raw_score * weight, 4)
        summary = self._summarise(raw_score, failed_rules)

        return CategoryScore(
            category=self.category,
            raw_score=round(raw_score, 2),
            weighted_score=weighted_score,
            weight=weight,
            confidence=round(confidence, 3),
            evidence=evidence,
            summary=summary,
            failed_rules=failed_rules,
            contributions=contributions,
        )

    # ── Abstract ──────────────────────────────────────────────────────────

    @abstractmethod
    def _score_category(
        self,
        project_dir: Path,
        scenes: list[dict],
        validation_report: ValidationReport,
        rca_report: RCAReport,
        context: dict,
    ) -> list[RuleContribution]:
        """Return one RuleContribution per rule checked in this category."""
        ...

    # ── Helpers available to subclasses ──────────────────────────────────

    def _results_for(
        self,
        validation_report: ValidationReport,
        category: str | None = None,
    ) -> list[ValidationResult]:
        cat = category or self.category
        return [r for r in validation_report.results if r.category == cat]

    def _rule_results(
        self,
        results: list[ValidationResult],
        rule_id: str,
    ) -> list[ValidationResult]:
        return [r for r in results if r.rule_id == rule_id]

    def _contribute(
        self,
        rule_id: str,
        points: float,
        results: list[ValidationResult],
        rule_results: list[ValidationResult] | None = None,
    ) -> RuleContribution:
        """Build a RuleContribution from the validation results for one rule.

        If ``rule_results`` is supplied, uses them directly; otherwise filters
        ``results`` by ``rule_id``.
        """
        rr = (
            rule_results
            if rule_results is not None
            else self._rule_results(results, rule_id)
        )

        if not rr:
            # Rule never ran (no scenes, no data) — treat as absent/neutral
            return RuleContribution(
                rule_id=rule_id,
                points_available=points,
                points_earned=points,  # neutral: no penalty for absent data
                status="absent",
                evidence="",
            )

        pass_count = sum(1 for r in rr if r.status == "PASS")
        warn_count = sum(1 for r in rr if r.status == "WARNING")
        fail_count = sum(1 for r in rr if r.status == "FAIL")
        skip_count = sum(1 for r in rr if r.status == "SKIP")
        non_skip = len(rr) - skip_count

        if non_skip == 0:
            # All results are SKIP — neutral, excluded from denominator
            return RuleContribution(
                rule_id=rule_id,
                points_available=points,
                points_earned=points,
                status="skip",
                evidence="",
            )

        # Points earned: pass=full, warn=half, fail=zero
        earned = ((pass_count * 1.0 + warn_count * 0.5) / non_skip) * points

        if fail_count > 0 and warn_count == 0 and pass_count == 0:
            status = "fail"
        elif fail_count > 0 or warn_count > 0:
            status = "partial" if earned > 0 else "fail"
        elif warn_count > 0 and fail_count == 0:
            status = "warning"
        else:
            status = "pass"

        evidence = ""
        if fail_count or warn_count:
            total = fail_count + warn_count
            sample = next(
                (r.description for r in rr if r.status in ("FAIL", "WARNING")),
                f"{total} check(s) failed",
            )
            evidence = f"{rule_id}: {total}/{len(rr)} check(s) failed — {sample}"

        return RuleContribution(
            rule_id=rule_id,
            points_available=points,
            points_earned=round(earned, 4),
            status=status,
            evidence=evidence,
        )

    # ── Private aggregation ───────────────────────────────────────────────

    def _aggregate(
        self, contributions: list[RuleContribution]
    ) -> tuple[float, float, list[str], list[str]]:
        """Return (raw_score, confidence, evidence_list, failed_rules)."""
        available = sum(
            c.points_available
            for c in contributions
            if c.status not in ("skip", "absent")
        )
        earned = sum(
            c.points_earned for c in contributions if c.status not in ("skip", "absent")
        )

        non_neutral = sum(1 for c in contributions if c.status not in ("absent",))
        skip_count = sum(1 for c in contributions if c.status == "skip")

        raw_score = (earned / available * 100) if available > 0 else 100.0
        confidence = (
            (non_neutral - skip_count) / non_neutral if non_neutral > 0 else 1.0
        )

        evidence = [c.evidence for c in contributions if c.evidence]
        failed_rules = [
            c.rule_id
            for c in contributions
            if c.status in ("fail", "partial", "warning")
        ]

        return raw_score, confidence, evidence, failed_rules

    def _summarise(self, raw_score: float, failed_rules: list[str]) -> str:
        if raw_score >= 90:
            return f"{self.category.title()} quality is excellent ({raw_score:.0f}/100)"
        if raw_score >= 75:
            return f"{self.category.title()} quality is good ({raw_score:.0f}/100)"
        if raw_score >= 60:
            return (
                f"{self.category.title()} quality is fair ({raw_score:.0f}/100); "
                f"improve: {', '.join(failed_rules[:2])}"
            )
        if raw_score >= 40:
            return (
                f"{self.category.title()} quality is poor ({raw_score:.0f}/100); "
                f"fix: {', '.join(failed_rules[:3])}"
            )
        return (
            f"{self.category.title()} quality is critical ({raw_score:.0f}/100); "
            f"failing: {', '.join(failed_rules[:3])}"
        )
