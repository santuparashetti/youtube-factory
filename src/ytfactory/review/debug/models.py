"""Domain models for Video Review Debug Mode V1.

Every review run with debug enabled produces a DebugReport containing:
- ExecutionTimelineEntry  — ordered pipeline events with timestamps/durations
- SceneDebugInfo          — per-scene asset presence and validation summary
- ValidationRuleDebugEntry — per-rule execution data
- CategoryScoringDebugEntry — per-category scoring breakdown
- FeedbackDebugEntry      — EFL feedback items for debug inspection
- DebugDiagnostics        — aggregate timing and missing-artifact info
- DebugReport             — top-level container for all debug data
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExecutionTimelineEntry:
    """A single event in the pipeline execution timeline."""

    event: str                    # e.g. "stages:start", "validation:end"
    layer: str                    # e.g. "stages", "validation", "rca", "scoring", "efl"
    timestamp: str                # ISO-8601 UTC
    duration_seconds: float | None = None  # set only on ":end" events
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "layer": self.layer,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "details": self.details,
        }


@dataclass
class SceneDebugInfo:
    """Debug information for a single scene."""

    scene_index: int
    has_image: bool
    has_audio: bool
    has_subtitle: bool
    has_video_clip: bool
    narration_word_count: int
    declared_duration_seconds: float
    validation_rule_ids: list[str]    # all rule IDs that ran for this scene
    failed_rule_ids: list[str]        # rules that FAIL or WARNING for this scene
    issues: list[str]                 # issues from SceneReview

    def to_dict(self) -> dict:
        return {
            "scene_index": self.scene_index,
            "has_image": self.has_image,
            "has_audio": self.has_audio,
            "has_subtitle": self.has_subtitle,
            "has_video_clip": self.has_video_clip,
            "narration_word_count": self.narration_word_count,
            "declared_duration_seconds": self.declared_duration_seconds,
            "validation_rule_ids": self.validation_rule_ids,
            "failed_rule_ids": self.failed_rule_ids,
            "issues": self.issues,
        }


@dataclass
class ValidationRuleDebugEntry:
    """Debug entry for a single validation rule execution."""

    rule_id: str
    category: str
    status: str               # PASS | FAIL | WARNING | SKIP
    severity: str
    confidence: float
    evidence: str
    responsible_engine: str
    description: str
    scene_index: int | None = None
    debug_metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "status": self.status,
            "severity": self.severity,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "responsible_engine": self.responsible_engine,
            "description": self.description,
            "scene_index": self.scene_index,
            "debug_metadata": self.debug_metadata,
        }


@dataclass
class CategoryScoringDebugEntry:
    """Debug entry for a single category's quality score."""

    category: str
    raw_score: float
    weighted_score: float
    weight: float
    confidence: float
    summary: str
    failed_rules: list[str]
    contributions_count: int
    contributions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "raw_score": round(self.raw_score, 2),
            "weighted_score": round(self.weighted_score, 2),
            "weight": self.weight,
            "confidence": round(self.confidence, 3),
            "summary": self.summary,
            "failed_rules": self.failed_rules,
            "contributions_count": self.contributions_count,
            "contributions": self.contributions,
        }


@dataclass
class FeedbackDebugEntry:
    """Debug entry for a single EFL feedback item."""

    feedback_id: str
    engine_owner: str
    priority: str
    root_cause: str
    is_recurring: bool
    severity: str
    confidence: int
    category: str
    rule_id: str
    frequency: int
    recommended_fix: str

    def to_dict(self) -> dict:
        return {
            "feedback_id": self.feedback_id,
            "engine_owner": self.engine_owner,
            "priority": self.priority,
            "root_cause": self.root_cause,
            "is_recurring": self.is_recurring,
            "severity": self.severity,
            "confidence": self.confidence,
            "category": self.category,
            "rule_id": self.rule_id,
            "frequency": self.frequency,
            "recommended_fix": self.recommended_fix,
        }


@dataclass
class DebugDiagnostics:
    """Aggregate timing and artifact-availability diagnostics."""

    total_processing_seconds: float
    layer_timings: dict[str, float]    # layer_name → elapsed seconds
    stage_timings: dict[str, float]    # stage_name → elapsed seconds
    missing_artifacts: list[str]       # e.g. ["scene-003: no image"]
    error_count: int
    warning_count: int
    total_scenes: int
    scenes_missing_assets: int

    def to_dict(self) -> dict:
        return {
            "total_processing_seconds": round(self.total_processing_seconds, 3),
            "layer_timings": {k: round(v, 3) for k, v in self.layer_timings.items()},
            "stage_timings": {k: round(v, 3) for k, v in self.stage_timings.items()},
            "missing_artifacts": self.missing_artifacts,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "total_scenes": self.total_scenes,
            "scenes_missing_assets": self.scenes_missing_assets,
        }


@dataclass
class DebugReport:
    """Top-level debug report produced by the DebugCollector."""

    project_id: str
    timestamp: str
    debug_level: str

    # Overall outcome
    overall_verdict: str
    overall_score: float | None
    letter_grade: str | None
    total_scenes: int
    total_errors: int
    total_warnings: int

    # Timing and artifact diagnostics
    diagnostics: DebugDiagnostics

    # Ordered execution events (all levels when not OFF)
    timeline: list[ExecutionTimelineEntry] = field(default_factory=list)

    # Per-artifact debug data (populated at BASIC and above)
    scene_debug: list[SceneDebugInfo] = field(default_factory=list)
    validation_debug: list[ValidationRuleDebugEntry] = field(default_factory=list)
    scoring_debug: list[CategoryScoringDebugEntry] = field(default_factory=list)
    feedback_debug: list[FeedbackDebugEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": "v1",
            "project_id": self.project_id,
            "timestamp": self.timestamp,
            "debug_level": self.debug_level,
            "overall_verdict": self.overall_verdict,
            "overall_score": self.overall_score,
            "letter_grade": self.letter_grade,
            "total_scenes": self.total_scenes,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "diagnostics": self.diagnostics.to_dict(),
            "timeline": [e.to_dict() for e in self.timeline],
            "scene_debug": [s.to_dict() for s in self.scene_debug],
            "validation_debug": [r.to_dict() for r in self.validation_debug],
            "scoring_debug": [c.to_dict() for c in self.scoring_debug],
            "feedback_debug": [f.to_dict() for f in self.feedback_debug],
        }
