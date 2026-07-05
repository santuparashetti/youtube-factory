"""Report generation for the Root Cause Analysis Engine V1.

Produces four output files under workspace/jobs/<project_id>/review/:
  - root-cause-report.md      human-readable Markdown summary
  - root-cause.json           all RCAIssues as machine-readable JSON
  - engine-owner-summary.json per-engine aggregation
  - recurring-issues.json     cross-scene recurring defect patterns
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.review.rca.models import RCAReport
from ytfactory.review.artifacts import review_directory


def root_cause_report_md_path(project_id: str) -> Path:
    return review_directory(project_id) / "root-cause-report.md"


def root_cause_json_path(project_id: str) -> Path:
    return review_directory(project_id) / "root-cause.json"


def engine_owner_summary_path(project_id: str) -> Path:
    return review_directory(project_id) / "engine-owner-summary.json"


def recurring_issues_path(project_id: str) -> Path:
    return review_directory(project_id) / "recurring-issues.json"


class RCAReporter:
    """Write all Root Cause Analysis artefacts."""

    def write(self, report: RCAReport) -> Path:
        """Write all four output files and return the review directory."""
        review_dir = review_directory(report.project_id)
        self._write_report_md(report)
        self._write_root_cause_json(report)
        self._write_engine_owner_summary(report)
        self._write_recurring_issues(report)
        return review_dir

    # ── root-cause-report.md ──────────────────────────────────────────────

    def _write_report_md(self, report: RCAReport) -> None:
        lines = [
            "# Root Cause Analysis Report",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Timestamp:** {report.timestamp}  ",
            f"**Processing time:** {report.processing_time_seconds:.3f}s  ",
            "",
            "---",
            "",
            "## Summary",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| Total issues | {report.total_issues} |",
            f"| Critical | {report.critical_issues} |",
            f"| High | {report.high_issues} |",
            f"| Medium | {report.medium_issues} |",
            f"| Low | {report.low_issues} |",
            f"| Recurring patterns | {len(report.recurring_issues)} |",
            "",
        ]

        if not report.issues:
            lines += [
                "> ✅ No root causes identified — all validation checks passed.",
                "",
            ]
        else:
            # Issues by category
            lines += ["---", "", "## Issues by Category", ""]
            by_category: dict[str, list] = {}
            for issue in report.issues:
                by_category.setdefault(issue.category, []).append(issue)
            for cat in sorted(by_category):
                issues = by_category[cat]
                lines += [f"### {cat.title()} ({len(issues)} issue(s))", ""]
                for issue in issues:
                    sev_icon = {
                        "critical": "🔴",
                        "high": "🟠",
                        "medium": "🟡",
                        "low": "🔵",
                    }.get(issue.severity, "⚪")
                    lines += [
                        f"#### `{issue.issue_id}` — {issue.root_cause_code} ({sev_icon} {issue.severity})",
                        "",
                        f"**Rule:** `{issue.rule_id}`  ",
                        f"**Root Cause:** {issue.root_cause_description}  ",
                        f"**Confidence:** {issue.confidence}%  ",
                        f"**Primary Engine:** {issue.primary_engine}  ",
                    ]
                    if issue.secondary_engines:
                        lines.append(
                            f"**Secondary Engines:** {', '.join(issue.secondary_engines)}  "
                        )
                    if issue.scene_index is not None:
                        lines.append(f"**Scene:** {issue.scene_index}  ")
                    lines += [
                        f"**Evidence:** {issue.evidence}  ",
                        "",
                        f"**Suggested Fix:** {issue.suggested_fix}  ",
                        "",
                    ]
                    if issue.suggested_tests:
                        lines.append("**Suggested Tests:**")
                        for test in issue.suggested_tests:
                            lines.append(f"- {test}")
                        lines.append("")

            # Engine Owner Summary
            if report.engine_summaries:
                lines += ["---", "", "## Engine Owner Summary", ""]
                lines += [
                    "| Engine | Total | Critical | High | Medium | Low | Avg Confidence |",
                    "|--------|-------|----------|------|--------|-----|----------------|",
                ]
                for engine, summary in sorted(report.engine_summaries.items()):
                    lines.append(
                        f"| {engine} | {summary.total_issues} | "
                        f"{summary.critical_issues} | {summary.high_issues} | "
                        f"{summary.medium_issues} | {summary.low_issues} | "
                        f"{summary.avg_confidence:.0f}% |"
                    )
                lines.append("")

            # Recurring Issues
            if report.recurring_issues:
                lines += ["---", "", "## Recurring Issues (Systemic Defects)", ""]
                for rec in report.recurring_issues:
                    lines += [
                        f"### {rec.engine} — `{rec.root_cause_code}` ({rec.occurrence_count}×)",
                        "",
                        f"**Affected scenes:** {rec.affected_scenes}  ",
                        f"**Severity distribution:** {rec.severity_distribution}  ",
                        f"**Suggested systemic fix:** {rec.suggested_systemic_fix}  ",
                        "",
                    ]

        lines += [
            "---",
            "",
            "_Full details: `review/root-cause.json` · "
            "`review/engine-owner-summary.json` · `review/recurring-issues.json`_",
            "",
        ]

        root_cause_report_md_path(report.project_id).write_text(
            "\n".join(lines), encoding="utf-8"
        )

    # ── root-cause.json ───────────────────────────────────────────────────

    def _write_root_cause_json(self, report: RCAReport) -> None:
        root_cause_json_path(report.project_id).write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── engine-owner-summary.json ─────────────────────────────────────────

    def _write_engine_owner_summary(self, report: RCAReport) -> None:
        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "engines": {k: v.to_dict() for k, v in report.engine_summaries.items()},
        }
        engine_owner_summary_path(report.project_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── recurring-issues.json ─────────────────────────────────────────────

    def _write_recurring_issues(self, report: RCAReport) -> None:
        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "recurring_count": len(report.recurring_issues),
            "recurring_issues": [r.to_dict() for r in report.recurring_issues],
        }
        recurring_issues_path(report.project_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
