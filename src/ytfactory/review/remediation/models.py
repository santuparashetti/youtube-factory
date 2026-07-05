"""Domain models for Auto Remediation Engine V1.

RemediationAction   — a single planned fix for one failed component
RemediationPlan     — the full set of actions for a remediation run
RemediationCycle    — outcome of one execute + re-validate iteration
RetryHistoryEntry   — record of a single action execution attempt
RemediationReport   — top-level report produced by AutoRemediationEngine
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Action status values ──────────────────────────────────────────────────────

ACTION_STATUSES = ("pending", "in_progress", "completed", "failed", "skipped")

# ── Stopped reasons ───────────────────────────────────────────────────────────

STOPPED_REASONS = (
    "quality_threshold_met",
    "max_retries_reached",
    "no_actions_needed",
    "dry_run",
    "cost_limit_exceeded",
    "all_actions_failed",
)


@dataclass
class RemediationAction:
    """A single planned remediation action for one failed pipeline component."""

    action_id: str  # sequential: "ARE-0001", "ARE-0002", …
    strategy: str  # from config.STRATEGIES
    engine_target: str  # canonical EFL engine name
    category: str  # validation category
    severity: str  # "critical" | "high" | "medium" | "low"
    confidence: int  # 0–100
    rationale: str  # why this action was chosen
    estimated_cost: float = 0.0  # relative cost estimate

    scene_index: int | None = None  # None = affects all scenes
    rule_id: str = ""  # originating validation rule
    source_issue: str = ""  # RCA issue ID (e.g. "RCA-0001")
    source_feedback: str = ""  # EFL feedback ID (e.g. "EFL-0001")

    # Execution state (updated during execution)
    status: str = "pending"  # see ACTION_STATUSES
    attempt_count: int = 0
    outcome: str = ""  # human-readable outcome after execution

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "strategy": self.strategy,
            "engine_target": self.engine_target,
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "estimated_cost": round(self.estimated_cost, 3),
            "scene_index": self.scene_index,
            "rule_id": self.rule_id,
            "source_issue": self.source_issue,
            "source_feedback": self.source_feedback,
            "status": self.status,
            "attempt_count": self.attempt_count,
            "outcome": self.outcome,
        }


@dataclass
class RemediationPlan:
    """The full set of actions planned for one remediation pass."""

    project_id: str
    timestamp: str
    actions: list[RemediationAction] = field(default_factory=list)
    quality_score_before: float | None = None
    quality_threshold: float = 70.0
    max_retries: int = 3
    estimated_total_cost: float = 0.0
    decision_summary: str = ""

    @property
    def total_actions(self) -> int:
        return len(self.actions)

    def to_dict(self) -> dict:
        return {
            "version": "v1",
            "project_id": self.project_id,
            "timestamp": self.timestamp,
            "total_actions": self.total_actions,
            "quality_score_before": self.quality_score_before,
            "quality_threshold": self.quality_threshold,
            "max_retries": self.max_retries,
            "estimated_total_cost": round(self.estimated_total_cost, 3),
            "decision_summary": self.decision_summary,
            "actions": [a.to_dict() for a in self.actions],
        }


@dataclass
class RetryHistoryEntry:
    """Record of a single action execution attempt."""

    cycle: int
    action_id: str
    strategy: str
    engine_target: str
    category: str
    scene_index: int | None
    timestamp: str
    success: bool
    outcome: str
    elapsed_seconds: float

    def to_dict(self) -> dict:
        return {
            "cycle": self.cycle,
            "action_id": self.action_id,
            "strategy": self.strategy,
            "engine_target": self.engine_target,
            "category": self.category,
            "scene_index": self.scene_index,
            "timestamp": self.timestamp,
            "success": self.success,
            "outcome": self.outcome,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


@dataclass
class RemediationCycle:
    """Outcome of one remediation iteration (execute + re-validate)."""

    cycle_number: int
    timestamp: str
    actions_attempted: int
    actions_succeeded: int
    actions_failed: int
    quality_score_before: float | None
    quality_score_after: float | None
    verdict_before: str
    verdict_after: str
    elapsed_seconds: float
    threshold_met: bool = False

    def to_dict(self) -> dict:
        return {
            "cycle_number": self.cycle_number,
            "timestamp": self.timestamp,
            "actions_attempted": self.actions_attempted,
            "actions_succeeded": self.actions_succeeded,
            "actions_failed": self.actions_failed,
            "quality_score_before": self.quality_score_before,
            "quality_score_after": self.quality_score_after,
            "verdict_before": self.verdict_before,
            "verdict_after": self.verdict_after,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "threshold_met": self.threshold_met,
        }


@dataclass
class RegeneratedAsset:
    """Record of a single artifact that was regenerated."""

    cycle: int
    strategy: str
    category: str
    scene_index: int | None
    file_path: str
    backed_up_to: str = ""

    def to_dict(self) -> dict:
        return {
            "cycle": self.cycle,
            "strategy": self.strategy,
            "category": self.category,
            "scene_index": self.scene_index,
            "file_path": self.file_path,
            "backed_up_to": self.backed_up_to,
        }


@dataclass
class RemediationReport:
    """Top-level report produced by AutoRemediationEngine.remediate()."""

    project_id: str
    timestamp: str

    plan: RemediationPlan = field(default_factory=lambda: RemediationPlan("", ""))

    # Cycle history
    cycles: list[RemediationCycle] = field(default_factory=list)

    # Final state
    final_verdict: str = "UNKNOWN"
    final_quality_score: float | None = None
    stopped_reason: str = "no_actions_needed"

    # Aggregates
    total_cycles: int = 0
    total_actions_executed: int = 0
    total_actions_succeeded: int = 0
    total_actions_failed: int = 0

    # Detail records
    retry_history: list[RetryHistoryEntry] = field(default_factory=list)
    regenerated_assets: list[RegeneratedAsset] = field(default_factory=list)

    # Meta
    processing_time_seconds: float = 0.0
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {
            "version": "v1",
            "project_id": self.project_id,
            "timestamp": self.timestamp,
            "final_verdict": self.final_verdict,
            "final_quality_score": self.final_quality_score,
            "stopped_reason": self.stopped_reason,
            "total_cycles": self.total_cycles,
            "total_actions_executed": self.total_actions_executed,
            "total_actions_succeeded": self.total_actions_succeeded,
            "total_actions_failed": self.total_actions_failed,
            "processing_time_seconds": round(self.processing_time_seconds, 3),
            "dry_run": self.dry_run,
            "plan": self.plan.to_dict(),
            "cycles": [c.to_dict() for c in self.cycles],
            "retry_history": [r.to_dict() for r in self.retry_history],
            "regenerated_assets": [a.to_dict() for a in self.regenerated_assets],
        }
