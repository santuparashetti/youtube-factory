"""Base classes and shared utilities for Root Cause Analysis Engine V1.

Each concrete RCAAnalyzer maps validation failures in one category to
structured RCAIssues with root cause, engine ownership, and fix guidance.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ytfactory.review.rca.config import RCAConfig
from ytfactory.review.rca.models import RCAIssue
from ytfactory.review.validation.models import ValidationResult


@dataclass
class RuleMapping:
    """Static metadata mapping a validation rule to a root cause."""

    root_cause_code: str
    root_cause_description: str
    rca_category: str  # one of the 7 RCA categories
    primary_engine: str
    secondary_engines: list[str] = field(default_factory=list)
    base_confidence: int = 80
    suggested_fix: str = ""
    suggested_tests: list[str] = field(default_factory=list)


class BaseRCAAnalyzer(ABC):
    """Abstract base for per-category root cause analyzers.

    Subclasses declare ``validation_category`` to filter validation results
    and implement ``_analyze_one`` to produce an RCAIssue for each failure.
    """

    validation_category: str = "unknown"

    def __init__(self, config: RCAConfig) -> None:
        self._config = config

    # ── Public API ────────────────────────────────────────────────────────

    def analyze(
        self,
        results: list[ValidationResult],
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[RCAIssue]:
        """Return RCA issues for every failed/warned result in this category."""
        statuses = {"FAIL"}
        if self._config.include_warnings:
            statuses.add("WARNING")

        my_results = [
            r
            for r in results
            if r.category == self.validation_category and r.status in statuses
        ]

        issues: list[RCAIssue] = []
        for result in my_results:
            if not self._config.is_rule_enabled(result.rule_id):
                continue
            try:
                issue = self._analyze_one(result, project_dir, scenes, context)
            except Exception as exc:
                issue = self._unknown_issue(result, f"analyzer exception: {exc}")
            if issue and issue.confidence >= self._config.min_confidence_to_report:
                issues.append(issue)
        return issues

    # ── Abstract ──────────────────────────────────────────────────────────

    @abstractmethod
    def _analyze_one(
        self,
        result: ValidationResult,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> RCAIssue | None:
        """Map a single validation failure to an RCAIssue, or None to skip."""
        ...

    # ── Helpers ───────────────────────────────────────────────────────────

    def _from_mapping(
        self,
        result: ValidationResult,
        mapping: RuleMapping,
        extra_evidence: str = "",
        confidence_adj: int = 0,
    ) -> RCAIssue:
        """Construct an RCAIssue from a RuleMapping."""
        evidence = result.evidence
        if extra_evidence:
            evidence = f"{evidence}; {extra_evidence}"
        confidence = min(100, max(0, mapping.base_confidence + confidence_adj))
        if result.status == "WARNING":
            confidence = max(0, confidence - 10)
        return RCAIssue(
            issue_id="",  # engine assigns sequential IDs
            rule_id=result.rule_id,
            category=mapping.rca_category,
            root_cause_code=mapping.root_cause_code,
            root_cause_description=mapping.root_cause_description,
            confidence=confidence,
            severity=result.severity,
            evidence=evidence,
            primary_engine=mapping.primary_engine,
            secondary_engines=list(mapping.secondary_engines),
            suggested_fix=mapping.suggested_fix,
            suggested_tests=list(mapping.suggested_tests),
            timestamp=datetime.now(timezone.utc).isoformat(),
            scene_index=result.scene_index,
            timestamp_seconds=result.timestamp_seconds,
            debug_metadata={"validation_description": result.description},
        )

    def _unknown_issue(self, result: ValidationResult, reason: str = "") -> RCAIssue:
        """Produce an Unknown-class issue when no mapping matches."""
        detail = reason or "no matching rule mapping"
        return RCAIssue(
            issue_id="",
            rule_id=result.rule_id,
            category=result.category,
            root_cause_code="unknown",
            root_cause_description=(
                "Root cause could not be determined automatically; manual investigation required"
            ),
            confidence=0,
            severity=result.severity,
            evidence=f"{result.evidence}; rca_note: {detail}",
            primary_engine=result.responsible_engine,
            secondary_engines=[],
            suggested_fix=(
                "Investigate manually; review validation evidence and debug logs"
            ),
            suggested_tests=[
                "Add a test reproducing this exact failure",
                "Verify the responsible engine's output for this rule",
            ],
            timestamp=datetime.now(timezone.utc).isoformat(),
            scene_index=result.scene_index,
            timestamp_seconds=result.timestamp_seconds,
            debug_metadata={
                "validation_description": result.description,
                "rca_reason": detail,
            },
        )
