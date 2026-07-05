"""Root Cause Analysis Engine V1 — orchestrator.

Consumes a ValidationReport, runs per-category analyzers, assigns sequential
issue IDs, detects recurring patterns, and builds engine owner summaries.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ytfactory.review.rca.analyzers.audio import AudioRCAAnalyzer
from ytfactory.review.rca.analyzers.image import ImageRCAAnalyzer
from ytfactory.review.rca.analyzers.motion import MotionRCAAnalyzer
from ytfactory.review.rca.analyzers.narration import NarrationRCAAnalyzer
from ytfactory.review.rca.analyzers.rendering import RenderingRCAAnalyzer
from ytfactory.review.rca.analyzers.script import ScriptRCAAnalyzer
from ytfactory.review.rca.analyzers.story import StoryRCAAnalyzer
from ytfactory.review.rca.analyzers.subtitle import SubtitleRCAAnalyzer
from ytfactory.review.rca.config import RCAConfig
from ytfactory.review.rca.framework import BaseRCAAnalyzer
from ytfactory.review.rca.models import EngineOwnerSummary, RCAIssue, RCAReport, RecurringIssue
from ytfactory.review.validation.models import ValidationReport


class RootCauseAnalysisEngine:
    """Orchestrate all RCA analyzers and produce a structured RCAReport.

    Usage:
        engine = RootCauseAnalysisEngine()
        rca_report = engine.analyze(project_dir, scenes, validation_report, context)
    """

    def __init__(self, config: RCAConfig | None = None) -> None:
        self._config = config or RCAConfig()
        self._analyzers: list[BaseRCAAnalyzer] = [
            ScriptRCAAnalyzer(self._config),
            NarrationRCAAnalyzer(self._config),
            SubtitleRCAAnalyzer(self._config),
            ImageRCAAnalyzer(self._config),
            MotionRCAAnalyzer(self._config),
            AudioRCAAnalyzer(self._config),
            RenderingRCAAnalyzer(self._config),
            StoryRCAAnalyzer(self._config),
        ]

    # ── Public API ────────────────────────────────────────────────────────

    def analyze(
        self,
        project_dir: Path,
        scenes: list[dict],
        validation_report: ValidationReport,
        context: dict,
    ) -> RCAReport:
        """Analyze validation failures and return a complete RCAReport."""
        t0 = time.perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Collect raw issues from every analyzer
        raw_issues: list[RCAIssue] = []
        for analyzer in self._analyzers:
            try:
                issues = analyzer.analyze(
                    validation_report.results,
                    project_dir,
                    scenes,
                    context,
                )
                raw_issues.extend(issues)
            except Exception:
                pass  # one broken analyzer must not stop the others

        # Assign sequential IDs
        numbered: list[RCAIssue] = []
        for seq, issue in enumerate(raw_issues, start=1):
            issue.issue_id = f"RCA-{seq:04d}"
            numbered.append(issue)

        # Build aggregations
        engine_summaries = _build_engine_summaries(numbered)
        recurring = _detect_recurring(numbered, self._config)

        elapsed = time.perf_counter() - t0

        return RCAReport(
            project_id=validation_report.project_id,
            timestamp=timestamp,
            total_issues=len(numbered),
            critical_issues=sum(1 for i in numbered if i.severity == "critical"),
            high_issues=sum(1 for i in numbered if i.severity == "high"),
            medium_issues=sum(1 for i in numbered if i.severity == "medium"),
            low_issues=sum(1 for i in numbered if i.severity == "low"),
            issues=numbered,
            engine_summaries=engine_summaries,
            recurring_issues=recurring,
            processing_time_seconds=round(elapsed, 3),
        )


# ── Aggregation helpers ───────────────────────────────────────────────────────


def _build_engine_summaries(
    issues: list[RCAIssue],
) -> dict[str, EngineOwnerSummary]:
    engine_groups: dict[str, list[RCAIssue]] = defaultdict(list)
    for issue in issues:
        engine_groups[issue.primary_engine].append(issue)

    summaries: dict[str, EngineOwnerSummary] = {}
    for engine, eng_issues in engine_groups.items():
        root_causes: dict[str, int] = defaultdict(int)
        for issue in eng_issues:
            root_causes[issue.root_cause_code] += 1

        avg_conf = (
            sum(i.confidence for i in eng_issues) / len(eng_issues)
            if eng_issues
            else 0.0
        )

        seen_fixes: set[str] = set()
        recs: list[str] = []
        for issue in eng_issues:
            fix = issue.suggested_fix.strip()
            if fix and fix not in seen_fixes:
                seen_fixes.add(fix)
                recs.append(fix)
            if len(recs) >= 5:
                break

        summaries[engine] = EngineOwnerSummary(
            engine=engine,
            total_issues=len(eng_issues),
            critical_issues=sum(1 for i in eng_issues if i.severity == "critical"),
            high_issues=sum(1 for i in eng_issues if i.severity == "high"),
            medium_issues=sum(1 for i in eng_issues if i.severity == "medium"),
            low_issues=sum(1 for i in eng_issues if i.severity == "low"),
            root_causes=dict(root_causes),
            avg_confidence=round(avg_conf, 1),
            primary_recommendations=recs,
        )
    return summaries


def _detect_recurring(
    issues: list[RCAIssue],
    config: RCAConfig,
) -> list[RecurringIssue]:
    groups: dict[tuple[str, str], list[RCAIssue]] = defaultdict(list)
    for issue in issues:
        key = (issue.primary_engine, issue.root_cause_code)
        groups[key].append(issue)

    recurring: list[RecurringIssue] = []
    for (engine, code), group in groups.items():
        # Only flag as recurring if it spans multiple distinct scenes
        scene_indices = [i.scene_index for i in group if i.scene_index is not None]
        distinct_scenes = len(set(scene_indices))
        if len(group) < config.recurring_threshold or distinct_scenes < 2:
            continue

        sev_dist: dict[str, int] = defaultdict(int)
        for issue in group:
            sev_dist[issue.severity] += 1

        fix_counts: dict[str, int] = defaultdict(int)
        for issue in group:
            if issue.suggested_fix:
                fix_counts[issue.suggested_fix] += 1
        systemic_fix = (
            max(fix_counts, key=lambda k: fix_counts[k])
            if fix_counts
            else "Investigate root cause across all affected scenes"
        )

        recurring.append(
            RecurringIssue(
                engine=engine,
                root_cause_code=code,
                occurrence_count=len(group),
                affected_scenes=sorted(set(s for s in scene_indices)),
                severity_distribution=dict(sev_dist),
                suggested_systemic_fix=systemic_fix,
            )
        )

    return sorted(recurring, key=lambda r: r.occurrence_count, reverse=True)
