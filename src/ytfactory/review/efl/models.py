"""Domain models for the Engine Feedback Loop V1.

Every identified issue becomes a FeedbackItem routed to a specific engine.
EngineFeedbackReport aggregates all items, engine summaries, recurring
patterns, and an improvement roadmap.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class FeedbackItem:
    """A single actionable feedback record assigned to a pipeline engine.

    Maps 1:1 from an RCAIssue; fields correspond to the spec's
    Feedback Record definition.
    """

    feedback_id: str  # sequential: "EFL-0001", "EFL-0002", …
    engine_owner: str  # canonical engine name (see EFL config)
    source_issue: str  # RCA issue_id (e.g. "RCA-0001") that produced this
    root_cause: str  # human-readable root cause description
    severity: str  # "critical" | "high" | "medium" | "low"
    confidence: int  # 0–100
    frequency: int  # number of scenes / occurrences affected
    evidence: str  # evidence supporting this finding
    recommended_fix: str  # actionable permanent fix for the engine
    suggested_tests: list[str]  # regression-prevention test ideas
    expected_outcome: str  # what success looks like after the fix
    priority: str  # "critical" | "high" | "medium" | "low"

    is_recurring: bool = False  # True if this issue was seen in prior runs
    category: str = ""  # validation category this came from
    rule_id: str = ""  # originating validation rule

    def to_dict(self) -> dict:
        return {
            "feedback_id": self.feedback_id,
            "engine_owner": self.engine_owner,
            "source_issue": self.source_issue,
            "root_cause": self.root_cause,
            "severity": self.severity,
            "confidence": self.confidence,
            "frequency": self.frequency,
            "evidence": self.evidence,
            "recommended_fix": self.recommended_fix,
            "suggested_tests": self.suggested_tests,
            "expected_outcome": self.expected_outcome,
            "priority": self.priority,
            "is_recurring": self.is_recurring,
            "category": self.category,
            "rule_id": self.rule_id,
        }


@dataclass
class EngineFeedbackSummary:
    """Aggregated feedback statistics for a single engine."""

    engine: str
    total_feedback: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    top_issues: list[str]  # up to 5 feedback_ids
    top_recommendations: list[str]  # unique recommended_fix strings

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecurringPattern:
    """A (engine, root_cause_code) pair that recurs across multiple runs or scenes.

    Persisted to recurring-patterns.json and accumulated across runs.
    """

    pattern_id: str  # "PAT-0001"
    engine: str
    root_cause_code: str
    total_occurrence_count: int  # cumulative across all runs
    current_run_count: int  # occurrences in this run alone
    affected_projects: list[str]  # project IDs where this was seen
    affected_scenes: list[int]  # scene indices from current run
    severity_distribution: dict[str, int]
    suggested_systemic_fix: str
    priority: str  # escalated priority
    first_seen: str  # ISO timestamp of first occurrence
    last_seen: str  # ISO timestamp of latest occurrence

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RoadmapItem:
    """A single improvement action in the improvement roadmap."""

    roadmap_id: str  # "RM-0001"
    priority: str  # "critical" | "high" | "medium" | "low"
    engine: str
    action: str  # imperative action sentence
    expected_impact: str  # what improves after this action
    source_feedback_ids: list[str]
    estimated_effort: str  # "low" | "medium" | "high"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EngineFeedbackReport:
    """Top-level Engine Feedback Loop V1 report."""

    project_id: str
    timestamp: str

    feedback_items: list[FeedbackItem] = field(default_factory=list)
    engine_summaries: dict[str, EngineFeedbackSummary] = field(default_factory=dict)
    recurring_patterns: list[RecurringPattern] = field(default_factory=list)
    improvement_roadmap: list[RoadmapItem] = field(default_factory=list)

    priority_distribution: dict[str, int] = field(default_factory=dict)
    total_feedback: int = 0
    total_engines_affected: int = 0
    processing_time_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "version": "v1",
            "project_id": self.project_id,
            "timestamp": self.timestamp,
            "total_feedback": self.total_feedback,
            "total_engines_affected": self.total_engines_affected,
            "priority_distribution": self.priority_distribution,
            "processing_time_seconds": self.processing_time_seconds,
            "feedback_items": [f.to_dict() for f in self.feedback_items],
            "engine_summaries": {
                k: v.to_dict() for k, v in self.engine_summaries.items()
            },
            "recurring_patterns": [r.to_dict() for r in self.recurring_patterns],
            "improvement_roadmap": [r.to_dict() for r in self.improvement_roadmap],
        }
