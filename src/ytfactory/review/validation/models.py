"""Domain models for Video Validation Rules V1.

Every validation rule produces a ValidationResult with full structured data.
ValidationReport aggregates results across all 8 categories.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ValidationResult:
    """Structured result for a single validation rule check.

    Designed to feed the Root Cause Analysis Engine and Engine Feedback Loop
    when those V1 specifications are implemented.
    """

    rule_id: str  # e.g. "SCRIPT_001"
    category: str  # "script" | "narration" | "subtitle" | ...
    status: str  # "PASS" | "FAIL" | "WARNING" | "SKIP"
    severity: str  # "critical" | "high" | "medium" | "low"
    description: str  # human-readable rule description
    evidence: str  # what was found / why rule failed
    confidence: float  # 0.0–1.0
    responsible_engine: str  # placeholder for RCA routing
    timestamp: str  # ISO-8601 UTC

    # Optional positional context
    scene_index: int | None = None
    timestamp_seconds: float | None = None  # position within video/scene

    # Arbitrary key-value data for RCA and debugging
    debug_metadata: dict = field(default_factory=dict)

    # ── Convenience properties ────────────────────────────────────────────

    @property
    def is_critical_failure(self) -> bool:
        return self.status == "FAIL" and self.severity == "critical"

    @property
    def passed(self) -> bool:
        return self.status in ("PASS", "SKIP")

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "status": self.status,
            "severity": self.severity,
            "description": self.description,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "responsible_engine": self.responsible_engine,
            "timestamp": self.timestamp,
            "scene_index": self.scene_index,
            "timestamp_seconds": self.timestamp_seconds,
            "debug_metadata": self.debug_metadata,
        }


@dataclass
class ValidationReport:
    """Aggregate report produced by ValidationRunner across all 8 categories."""

    project_id: str
    timestamp: str

    # Rule tallies
    total_rules_run: int = 0
    total_passed: int = 0
    total_failed: int = 0
    total_warnings: int = 0
    total_skipped: int = 0

    # Failures that block publishing
    critical_failures: list[ValidationResult] = field(default_factory=list)

    # Per-category pass rates (0.0–1.0); SKIP results are excluded
    category_scores: dict[str, float] = field(default_factory=dict)

    # Full flat list of all results across all categories
    results: list[ValidationResult] = field(default_factory=list)

    processing_time_seconds: float = 0.0

    @property
    def verdict(self) -> str:
        return "FAIL" if self.critical_failures else "PASS"

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "timestamp": self.timestamp,
            "verdict": self.verdict,
            "total_rules_run": self.total_rules_run,
            "total_passed": self.total_passed,
            "total_failed": self.total_failed,
            "total_warnings": self.total_warnings,
            "total_skipped": self.total_skipped,
            "critical_failures": [r.to_dict() for r in self.critical_failures],
            "category_scores": self.category_scores,
            "results": [r.to_dict() for r in self.results],
            "processing_time_seconds": self.processing_time_seconds,
        }
