"""Domain models for the Root Cause Analysis Engine V1.

Every identified root cause is captured as an RCAIssue.
RCAReport aggregates all issues, engine summaries, and recurring patterns.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class RCAIssue:
    """A single identified root cause linked to a validation failure."""

    issue_id: str                   # assigned by engine, e.g. "RCA-0001"
    rule_id: str                    # source ValidationResult.rule_id
    category: str                   # RCA category: script|narration|subtitle|image|motion|audio|rendering
    root_cause_code: str            # snake_case code, e.g. "wrong_duration"
    root_cause_description: str     # human-readable explanation of the root cause
    confidence: int                 # 0–100
    severity: str                   # "critical" | "high" | "medium" | "low"
    evidence: str                   # what evidence supports this root cause
    primary_engine: str             # engine primarily responsible
    secondary_engines: list[str]    # engines with secondary responsibility
    suggested_fix: str              # recommended permanent fix
    suggested_tests: list[str]      # tests to prevent recurrence
    timestamp: str                  # ISO-8601 UTC

    scene_index: int | None = None
    timestamp_seconds: float | None = None
    debug_metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "issue_id": self.issue_id,
            "rule_id": self.rule_id,
            "category": self.category,
            "root_cause_code": self.root_cause_code,
            "root_cause_description": self.root_cause_description,
            "confidence": self.confidence,
            "severity": self.severity,
            "evidence": self.evidence,
            "primary_engine": self.primary_engine,
            "secondary_engines": self.secondary_engines,
            "suggested_fix": self.suggested_fix,
            "suggested_tests": self.suggested_tests,
            "timestamp": self.timestamp,
            "scene_index": self.scene_index,
            "timestamp_seconds": self.timestamp_seconds,
            "debug_metadata": self.debug_metadata,
        }


@dataclass
class EngineOwnerSummary:
    """Per-engine aggregation of all assigned root causes."""

    engine: str
    total_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int
    root_causes: dict[str, int]     # root_cause_code → occurrence count
    avg_confidence: float
    primary_recommendations: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecurringIssue:
    """A root cause that recurs across multiple scenes (systemic defect)."""

    engine: str
    root_cause_code: str
    occurrence_count: int
    affected_scenes: list[int]
    severity_distribution: dict[str, int]   # severity → count
    suggested_systemic_fix: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RCAReport:
    """Top-level Root Cause Analysis report."""

    project_id: str
    timestamp: str

    total_issues: int = 0
    critical_issues: int = 0
    high_issues: int = 0
    medium_issues: int = 0
    low_issues: int = 0

    issues: list[RCAIssue] = field(default_factory=list)
    engine_summaries: dict[str, EngineOwnerSummary] = field(default_factory=dict)
    recurring_issues: list[RecurringIssue] = field(default_factory=list)
    processing_time_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "version": "v1",
            "project_id": self.project_id,
            "timestamp": self.timestamp,
            "total_issues": self.total_issues,
            "critical_issues": self.critical_issues,
            "high_issues": self.high_issues,
            "medium_issues": self.medium_issues,
            "low_issues": self.low_issues,
            "issues": [i.to_dict() for i in self.issues],
            "engine_summaries": {k: v.to_dict() for k, v in self.engine_summaries.items()},
            "recurring_issues": [r.to_dict() for r in self.recurring_issues],
            "processing_time_seconds": self.processing_time_seconds,
        }
