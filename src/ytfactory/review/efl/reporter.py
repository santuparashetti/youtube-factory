"""Report generation for the Engine Feedback Loop V1.

Produces five output files under workspace/jobs/<project_id>/review/:
  - engine-feedback.json          full structured EFL report (replaces stub)
  - engine-feedback.md            human-readable feedback summary
  - engine-priority-report.json   items sorted/grouped by priority
  - recurring-patterns.json       cross-run recurring patterns (accumulated)
  - improvement-roadmap.md        actionable roadmap in Markdown
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.review.artifacts import review_directory
from ytfactory.review.efl.models import EngineFeedbackReport, RecurringPattern


def engine_feedback_json_path(project_id: str) -> Path:
    return review_directory(project_id) / "engine-feedback.json"


def engine_feedback_md_path(project_id: str) -> Path:
    return review_directory(project_id) / "engine-feedback.md"


def engine_priority_report_path(project_id: str) -> Path:
    return review_directory(project_id) / "engine-priority-report.json"


def efl_recurring_patterns_path(project_id: str) -> Path:
    return review_directory(project_id) / "recurring-patterns.json"


def improvement_roadmap_md_path(project_id: str) -> Path:
    return review_directory(project_id) / "improvement-roadmap.md"


class EFLReporter:
    """Write all Engine Feedback Loop V1 artefacts."""

    def write(self, report: EngineFeedbackReport) -> Path:
        """Write all five output files and return the review directory."""
        review_dir = review_directory(report.project_id)
        self._write_engine_feedback_json(report)
        self._write_engine_feedback_md(report)
        self._write_priority_report(report)
        self._write_recurring_patterns(report)
        self._write_improvement_roadmap(report)
        return review_dir

    # ── engine-feedback.json ──────────────────────────────────────────────

    def _write_engine_feedback_json(self, report: EngineFeedbackReport) -> None:
        engine_feedback_json_path(report.project_id).write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── engine-feedback.md ────────────────────────────────────────────────

    def _write_engine_feedback_md(self, report: EngineFeedbackReport) -> None:
        lines = [
            "# Engine Feedback Loop Report",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Timestamp:** {report.timestamp}  ",
            f"**Processing time:** {report.processing_time_seconds:.3f}s  ",
            "",
            "---",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total feedback items | {report.total_feedback} |",
            f"| Engines affected | {report.total_engines_affected} |",
            f"| Recurring patterns | {len(report.recurring_patterns)} |",
            f"| Roadmap items | {len(report.improvement_roadmap)} |",
            "",
            "### Priority Distribution",
            "",
            "| Priority | Count |",
            "|----------|-------|",
        ]
        for p in ("critical", "high", "medium", "low"):
            count = report.priority_distribution.get(p, 0)
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}[p]
            lines.append(f"| {icon} {p.title()} | {count} |")
        lines.append("")

        if not report.feedback_items:
            lines += [
                "> ✅ No feedback items — all validation checks passed.",
                "",
            ]
        else:
            # Feedback grouped by engine
            lines += ["---", "", "## Feedback by Engine", ""]
            by_engine: dict[str, list] = {}
            for item in report.feedback_items:
                by_engine.setdefault(item.engine_owner, []).append(item)

            for engine in sorted(
                by_engine, key=lambda e: _engine_priority(by_engine[e])
            ):
                eng_items = by_engine[engine]
                lines += [f"### {engine} ({len(eng_items)} item(s))", ""]
                for item in sorted(eng_items, key=lambda x: _rank(x.priority)):
                    p_icon = {
                        "critical": "🔴",
                        "high": "🟠",
                        "medium": "🟡",
                        "low": "🔵",
                    }.get(item.priority, "⚪")
                    recurring_tag = " ♻️ _recurring_" if item.is_recurring else ""
                    lines += [
                        f"#### `{item.feedback_id}` — {p_icon} {item.priority.upper()}"
                        f"{recurring_tag}",
                        "",
                        f"**Source:** `{item.source_issue}`  ",
                        f"**Category:** {item.category}  ",
                        f"**Rule:** `{item.rule_id}`  ",
                        f"**Root Cause:** {item.root_cause}  ",
                        f"**Severity:** {item.severity} | **Confidence:** {item.confidence}% |"
                        f" **Frequency:** {item.frequency}×  ",
                        f"**Evidence:** {item.evidence}  ",
                        "",
                        "**Recommended Fix:**  ",
                        f"> {item.recommended_fix}",
                        "",
                        "**Expected Outcome:**  ",
                        f"> {item.expected_outcome}",
                        "",
                    ]
                    if item.suggested_tests:
                        lines.append("**Suggested Tests:**")
                        for t in item.suggested_tests[:3]:
                            lines.append(f"- {t}")
                        lines.append("")

            # Engine summaries table
            if report.engine_summaries:
                lines += [
                    "---",
                    "",
                    "## Engine Summary",
                    "",
                    "| Engine | Total | Critical | High | Medium | Low |",
                    "|--------|-------|----------|------|--------|-----|",
                ]
                for engine, summary in sorted(report.engine_summaries.items()):
                    lines.append(
                        f"| {engine} | {summary.total_feedback} | "
                        f"{summary.critical_count} | {summary.high_count} | "
                        f"{summary.medium_count} | {summary.low_count} |"
                    )
                lines.append("")

            # Recurring patterns
            if report.recurring_patterns:
                lines += ["---", "", "## Recurring Patterns", ""]
                for pat in report.recurring_patterns:
                    lines += [
                        f"### {pat.pattern_id} — {pat.engine} / `{pat.root_cause_code}`",
                        "",
                        f"**Priority:** {pat.priority.upper()} | "
                        f"**Occurrences:** {pat.total_occurrence_count} |  ",
                        f"**Affected scenes:** {pat.affected_scenes}  ",
                        f"**Systemic fix:** {pat.suggested_systemic_fix}  ",
                        "",
                    ]

        lines += [
            "---",
            "",
            "_Full details: `review/engine-feedback.json` · "
            "`review/engine-priority-report.json` · "
            "`review/recurring-patterns.json`_",
            "",
            "_Roadmap: `review/improvement-roadmap.md`_",
            "",
        ]

        engine_feedback_md_path(report.project_id).write_text(
            "\n".join(lines), encoding="utf-8"
        )

    # ── engine-priority-report.json ───────────────────────────────────────

    def _write_priority_report(self, report: EngineFeedbackReport) -> None:
        by_priority: dict[str, list[dict]] = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
        }
        for item in report.feedback_items:
            bucket = by_priority.get(item.priority, by_priority["low"])
            bucket.append(item.to_dict())

        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "total_feedback": report.total_feedback,
            "priority_distribution": report.priority_distribution,
            "engine_summary": {
                engine: {
                    "total": s.total_feedback,
                    "critical": s.critical_count,
                    "high": s.high_count,
                    "medium": s.medium_count,
                    "low": s.low_count,
                }
                for engine, s in report.engine_summaries.items()
            },
            "by_priority": by_priority,
        }
        engine_priority_report_path(report.project_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── recurring-patterns.json ───────────────────────────────────────────

    def _write_recurring_patterns(self, report: EngineFeedbackReport) -> None:
        """Accumulate recurring patterns across runs (read-modify-write)."""
        path = efl_recurring_patterns_path(report.project_id)

        # Load existing history
        try:
            existing = (
                json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            )
            history: list[dict] = existing.get("patterns", [])
        except (json.JSONDecodeError, OSError):
            history = []

        # Merge current run patterns into history
        current_keys: dict[tuple[str, str], RecurringPattern] = {
            (p.engine, p.root_cause_code): p for p in report.recurring_patterns
        }

        merged: list[dict] = []
        for existing_pat in history:
            key = (
                existing_pat.get("engine", ""),
                existing_pat.get("root_cause_code", ""),
            )
            if key in current_keys:
                cur = current_keys.pop(key)
                # Merge: accumulate occurrence count, extend project list
                existing_pat["total_occurrence_count"] = (
                    existing_pat.get("total_occurrence_count", 0)
                    + cur.current_run_count
                )
                existing_pat["current_run_count"] = cur.current_run_count
                existing_pat["last_seen"] = report.timestamp
                prior_projects = existing_pat.get("affected_projects", [])
                if report.project_id not in prior_projects:
                    prior_projects.append(report.project_id)
                existing_pat["affected_projects"] = prior_projects
                existing_pat["affected_scenes"] = cur.affected_scenes
                existing_pat["priority"] = cur.priority
            merged.append(existing_pat)

        # Append brand-new patterns
        for pat in current_keys.values():
            merged.append(pat.to_dict())

        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "total_patterns": len(merged),
            "patterns": merged,
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── improvement-roadmap.md ────────────────────────────────────────────

    def _write_improvement_roadmap(self, report: EngineFeedbackReport) -> None:
        lines = [
            "# Improvement Roadmap",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Generated:** {report.timestamp}  ",
            f"**Items:** {len(report.improvement_roadmap)}  ",
            "",
            "This roadmap lists the highest-impact improvements, sorted by priority.",
            "Each item targets a specific engine with an actionable permanent fix.",
            "",
        ]

        if not report.improvement_roadmap:
            lines += [
                "> ✅ No improvements required — all checks passed.",
                "",
            ]
        else:
            for p in ("critical", "high", "medium", "low"):
                p_items = [r for r in report.improvement_roadmap if r.priority == p]
                if not p_items:
                    continue
                p_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}[
                    p
                ]
                lines += [
                    "---",
                    "",
                    f"## {p_icon} {p.title()} Priority",
                    "",
                ]
                for item in p_items:
                    effort_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(
                        item.estimated_effort, "⚪"
                    )
                    lines += [
                        f"### `{item.roadmap_id}` — {item.engine}",
                        "",
                        f"**Action:** {item.action}  ",
                        f"**Expected Impact:** {item.expected_impact}  ",
                        f"**Effort:** {effort_icon} {item.estimated_effort.title()}  ",
                        f"**Source Feedback:** {', '.join(item.source_feedback_ids)}  ",
                        "",
                    ]

        lines += [
            "---",
            "",
            "_Source data: `review/engine-feedback.json`_",
            "",
        ]

        improvement_roadmap_md_path(report.project_id).write_text(
            "\n".join(lines), encoding="utf-8"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _rank(priority: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(priority, 4)


def _engine_priority(items: list) -> int:
    """Return the sort key for an engine group — lower = higher priority."""
    return min((_rank(i.priority) for i in items), default=4)
