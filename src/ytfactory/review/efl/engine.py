"""Engine Feedback Loop V1 — orchestrator.

Consumes the full review pipeline output (Validation + RCA + Quality Scoring)
and produces structured, engine-specific feedback with actionable recommendations,
priority escalation for recurring issues, and an improvement roadmap.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ytfactory.review.efl.config import (
    EFLConfig,
    escalate_priority,
    normalize_engine,
    severity_to_priority,
)
from ytfactory.review.efl.models import (
    EngineFeedbackReport,
    EngineFeedbackSummary,
    FeedbackItem,
    RecurringPattern,
    RoadmapItem,
)
from ytfactory.review.rca.models import RCAReport
from ytfactory.review.scoring.models import QualityScoreReport
from ytfactory.review.validation.models import ValidationReport


class EngineFeedbackLoopEngine:
    """Generate engine-specific feedback from all prior review layers.

    Usage:
        engine = EngineFeedbackLoopEngine()
        efl_report = engine.generate(
            project_dir, scenes, validation_report, rca_report, score_report, context
        )
    """

    def __init__(self, config: EFLConfig | None = None) -> None:
        self._config = config or EFLConfig()

    # ── Public API ────────────────────────────────────────────────────────

    def generate(
        self,
        project_dir: Path,
        scenes: list[dict],
        validation_report: ValidationReport,
        rca_report: RCAReport,
        score_report: QualityScoreReport,
        context: dict,
    ) -> EngineFeedbackReport:
        """Run the feedback loop and return a complete EngineFeedbackReport."""
        t0 = time.perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Build a set of recurring (engine, root_cause_code) pairs for lookup
        recurring_keys: set[tuple[str, str]] = {
            (r.engine, r.root_cause_code)
            for r in rca_report.recurring_issues
            if r.occurrence_count >= self._config.recurring_escalation_threshold
        }

        # Track frequency per (engine, root_cause_code) in current run
        freq_map: dict[tuple[str, str], int] = defaultdict(int)
        for issue in rca_report.issues:
            key = (normalize_engine(issue.primary_engine), issue.root_cause_code)
            freq_map[key] += 1

        # Convert each RCA issue to a FeedbackItem
        raw_items: list[FeedbackItem] = []
        for rca_issue in rca_report.issues:
            if not self._config.is_rule_enabled(rca_issue.rule_id):
                continue
            if rca_issue.confidence < self._config.min_confidence_to_report:
                continue
            item = self._from_rca_issue(rca_issue, recurring_keys, freq_map)
            raw_items.append(item)

        # Assign sequential feedback IDs
        items: list[FeedbackItem] = []
        for seq, item in enumerate(raw_items, start=1):
            item.feedback_id = f"EFL-{seq:04d}"
            items.append(item)

        # Build engine summaries
        engine_summaries = _build_engine_summaries(items)

        # Compute priority distribution
        priority_dist: dict[str, int] = defaultdict(int)
        for item in items:
            priority_dist[item.priority] += 1

        # Build recurring patterns (current run)
        recurring_patterns = _build_recurring_patterns(
            rca_report, validation_report.project_id, timestamp
        )

        # Build improvement roadmap
        roadmap = _build_roadmap(items, engine_summaries)

        elapsed = time.perf_counter() - t0

        return EngineFeedbackReport(
            project_id=validation_report.project_id,
            timestamp=timestamp,
            feedback_items=items,
            engine_summaries=engine_summaries,
            recurring_patterns=recurring_patterns,
            improvement_roadmap=roadmap,
            priority_distribution=dict(priority_dist),
            total_feedback=len(items),
            total_engines_affected=len(engine_summaries),
            processing_time_seconds=round(elapsed, 3),
        )

    # ── Private helpers ───────────────────────────────────────────────────

    def _from_rca_issue(
        self,
        rca_issue,
        recurring_keys: set[tuple[str, str]],
        freq_map: dict[tuple[str, str], int],
    ) -> FeedbackItem:
        engine = normalize_engine(rca_issue.primary_engine)
        base_priority = severity_to_priority(rca_issue.severity)
        key = (engine, rca_issue.root_cause_code)
        is_recurring = key in recurring_keys
        priority = escalate_priority(base_priority) if is_recurring else base_priority
        frequency = freq_map.get(key, 1)

        expected_outcome = _derive_expected_outcome(
            rca_issue.suggested_fix, rca_issue.root_cause_code
        )

        return FeedbackItem(
            feedback_id="",  # assigned after collection
            engine_owner=engine,
            source_issue=rca_issue.issue_id or rca_issue.rule_id,
            root_cause=rca_issue.root_cause_description,
            severity=rca_issue.severity,
            confidence=rca_issue.confidence,
            frequency=frequency,
            evidence=rca_issue.evidence,
            recommended_fix=rca_issue.suggested_fix,
            suggested_tests=list(rca_issue.suggested_tests),
            expected_outcome=expected_outcome,
            priority=priority,
            is_recurring=is_recurring,
            category=rca_issue.category,
            rule_id=rca_issue.rule_id,
        )


# ── Aggregation helpers ───────────────────────────────────────────────────────


def _build_engine_summaries(
    items: list[FeedbackItem],
) -> dict[str, EngineFeedbackSummary]:
    groups: dict[str, list[FeedbackItem]] = defaultdict(list)
    for item in items:
        groups[item.engine_owner].append(item)

    summaries: dict[str, EngineFeedbackSummary] = {}
    for engine, eng_items in sorted(groups.items()):
        seen_fixes: set[str] = set()
        recs: list[str] = []
        top_ids: list[str] = []
        for item in sorted(eng_items, key=lambda x: _priority_rank(x.priority)):
            if len(top_ids) < 5:
                top_ids.append(item.feedback_id)
            fix = item.recommended_fix.strip()
            if fix and fix not in seen_fixes:
                seen_fixes.add(fix)
                recs.append(fix)
            if len(recs) >= 5:
                break

        summaries[engine] = EngineFeedbackSummary(
            engine=engine,
            total_feedback=len(eng_items),
            critical_count=sum(1 for i in eng_items if i.priority == "critical"),
            high_count=sum(1 for i in eng_items if i.priority == "high"),
            medium_count=sum(1 for i in eng_items if i.priority == "medium"),
            low_count=sum(1 for i in eng_items if i.priority == "low"),
            top_issues=top_ids,
            top_recommendations=recs,
        )
    return summaries


def _build_recurring_patterns(
    rca_report: RCAReport,
    project_id: str,
    timestamp: str,
) -> list[RecurringPattern]:
    patterns: list[RecurringPattern] = []
    for seq, rec in enumerate(rca_report.recurring_issues, start=1):
        engine = normalize_engine(rec.engine)
        sev_dist = dict(rec.severity_distribution)
        worst_severity = _worst_severity(sev_dist)
        base_priority = severity_to_priority(worst_severity)
        priority = escalate_priority(base_priority)  # recurring → always escalate

        patterns.append(
            RecurringPattern(
                pattern_id=f"PAT-{seq:04d}",
                engine=engine,
                root_cause_code=rec.root_cause_code,
                total_occurrence_count=rec.occurrence_count,
                current_run_count=rec.occurrence_count,
                affected_projects=[project_id],
                affected_scenes=list(rec.affected_scenes),
                severity_distribution=sev_dist,
                suggested_systemic_fix=rec.suggested_systemic_fix,
                priority=priority,
                first_seen=timestamp,
                last_seen=timestamp,
            )
        )
    return patterns


def _build_roadmap(
    items: list[FeedbackItem],
    summaries: dict[str, EngineFeedbackSummary],
) -> list[RoadmapItem]:
    """Build an improvement roadmap from the highest-priority feedback."""
    if not items:
        return []

    # Group feedback by (priority, engine) → pick the best recommended_fix
    group: dict[tuple[str, str], list[FeedbackItem]] = defaultdict(list)
    for item in items:
        group[(item.priority, item.engine_owner)].append(item)

    roadmap: list[RoadmapItem] = []
    seen_actions: set[str] = set()
    # Sort: critical first, then by total count descending
    sorted_keys = sorted(
        group.keys(),
        key=lambda k: (_priority_rank(k[0]), -len(group[k])),
    )

    seq = 1
    for priority, engine in sorted_keys:
        eng_items = group[(priority, engine)]
        # Deduplicate by recommended_fix; pick highest-confidence item's fix
        best = max(eng_items, key=lambda x: x.confidence)
        action = best.recommended_fix.strip() or f"Review {engine} output quality"
        if action in seen_actions:
            continue
        seen_actions.add(action)

        expected_impact = best.expected_outcome
        effort = _estimate_effort(eng_items)
        source_ids = [i.feedback_id for i in eng_items[:5]]

        roadmap.append(
            RoadmapItem(
                roadmap_id=f"RM-{seq:04d}",
                priority=priority,
                engine=engine,
                action=action,
                expected_impact=expected_impact,
                source_feedback_ids=source_ids,
                estimated_effort=effort,
            )
        )
        seq += 1
        if seq > 20:  # cap roadmap length to keep it actionable
            break

    return roadmap


# ── Utility helpers ───────────────────────────────────────────────────────────


def _priority_rank(priority: str) -> int:
    """Lower number = higher priority (for sorting)."""
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(priority, 4)


def _worst_severity(sev_dist: dict[str, int]) -> str:
    for sev in ("critical", "high", "medium", "low"):
        if sev_dist.get(sev, 0) > 0:
            return sev
    return "low"


def _derive_expected_outcome(suggested_fix: str, root_cause_code: str) -> str:
    """Convert a suggested fix into a positive expected-outcome statement."""
    if not suggested_fix:
        return f"Elimination of '{root_cause_code}' defect from future runs"
    # Take the first sentence of the fix and rephrase as an outcome
    first = suggested_fix.split(";")[0].split(".")[0].strip()
    if len(first) < 20:
        return f"Permanent resolution of {root_cause_code} defect"
    return f"After applying fix: {first.lower().rstrip('.')} will no longer fail validation"


def _estimate_effort(items: list[FeedbackItem]) -> str:
    """Heuristic: more items or higher confidence → more effort to fix."""
    if any(i.priority == "critical" for i in items):
        return "high"
    if len(items) >= 3 or any(i.is_recurring for i in items):
        return "medium"
    return "low"
