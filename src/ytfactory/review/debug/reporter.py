"""Report generation for Video Review Debug Mode V1.

Produces seven output files under workspace/jobs/<project_id>/review/debug/:
  - debug-report.md         human-readable debug summary
  - debug-summary.json      high-level JSON with verdicts, scores, diagnostics
  - scene-debug.json        per-scene asset presence + validation summary
  - validation-debug.json   per-rule execution data grouped by category
  - scoring-debug.json      per-category scoring breakdown with weights
  - feedback-debug.json     EFL feedback items for debug inspection
  - execution-timeline.json ordered pipeline events with timestamps/durations
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.review.artifacts import review_directory
from ytfactory.review.debug.models import DebugReport


def debug_directory(project_id: str) -> Path:
    """Return (and create) workspace/jobs/<project_id>/review/debug/."""
    directory = review_directory(project_id) / "debug"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


class DebugReporter:
    """Write all seven Video Review Debug Mode V1 output files."""

    def write(self, report: DebugReport) -> Path:
        """Write all output files and return the debug directory path."""
        debug_dir = debug_directory(report.project_id)
        self._write_debug_summary(report, debug_dir)
        self._write_debug_report_md(report, debug_dir)
        self._write_scene_debug(report, debug_dir)
        self._write_validation_debug(report, debug_dir)
        self._write_scoring_debug(report, debug_dir)
        self._write_feedback_debug(report, debug_dir)
        self._write_execution_timeline(report, debug_dir)
        return debug_dir

    # ── debug-summary.json ────────────────────────────────────────────────────

    def _write_debug_summary(self, report: DebugReport, debug_dir: Path) -> None:
        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "debug_level": report.debug_level,
            "overall_verdict": report.overall_verdict,
            "overall_score": report.overall_score,
            "letter_grade": report.letter_grade,
            "total_scenes": report.total_scenes,
            "total_errors": report.total_errors,
            "total_warnings": report.total_warnings,
            "diagnostics": report.diagnostics.to_dict(),
        }
        (debug_dir / "debug-summary.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── debug-report.md ───────────────────────────────────────────────────────

    def _write_debug_report_md(self, report: DebugReport, debug_dir: Path) -> None:
        verdict_icon = "✅ PASS" if report.overall_verdict == "PASS" else "❌ FAIL"
        d = report.diagnostics
        lines = [
            "# Video Review Debug Report",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Timestamp:** {report.timestamp}  ",
            f"**Debug Level:** `{report.debug_level.upper()}`  ",
            f"**Verdict:** {verdict_icon}  ",
            "",
            "---",
            "",
            "## Diagnostics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total processing time | {d.total_processing_seconds:.3f}s |",
            f"| Total scenes | {d.total_scenes} |",
            f"| Errors | {d.error_count} |",
            f"| Warnings | {d.warning_count} |",
            f"| Scenes with missing assets | {d.scenes_missing_assets} |",
            "",
        ]

        if d.layer_timings:
            lines += ["### Layer Timings", "", "| Layer | Duration |", "|-------|----------|"]
            for layer, secs in sorted(d.layer_timings.items()):
                lines.append(f"| {layer} | {secs:.3f}s |")
            lines.append("")

        if d.stage_timings:
            lines += ["### Stage Timings", "", "| Stage | Duration |", "|-------|----------|"]
            for stage, secs in sorted(d.stage_timings.items()):
                lines.append(f"| {stage} | {secs:.3f}s |")
            lines.append("")

        if d.missing_artifacts:
            lines += ["---", "", "## Missing Artifacts", ""]
            for art in d.missing_artifacts:
                lines.append(f"- ⚠️  {art}")
            lines.append("")

        if report.overall_score is not None:
            lines += [
                "---",
                "",
                "## Quality Score",
                "",
                f"**Overall Score:** {report.overall_score:.1f}/100  ",
                f"**Grade:** {report.letter_grade}  ",
                "",
            ]

        if report.scoring_debug:
            lines += [
                "### Category Scores",
                "",
                "| Category | Score | Weight |",
                "|----------|-------|--------|",
            ]
            for cs in sorted(report.scoring_debug, key=lambda x: x.raw_score):
                grade_icon = "✅" if cs.raw_score >= 70 else ("⚠️" if cs.raw_score >= 50 else "❌")
                lines.append(f"| {cs.category} | {cs.raw_score:.1f} {grade_icon} | {cs.weight:.2f} |")
            lines.append("")

        if report.validation_debug:
            n_pass = sum(1 for v in report.validation_debug if v.status == "PASS")
            n_fail = sum(1 for v in report.validation_debug if v.status == "FAIL")
            n_warn = sum(1 for v in report.validation_debug if v.status == "WARNING")
            n_skip = sum(1 for v in report.validation_debug if v.status == "SKIP")
            lines += [
                "---",
                "",
                "## Validation Summary",
                "",
                f"**Rules run:** {len(report.validation_debug)} | "
                f"**Pass:** {n_pass} | **Fail:** {n_fail} | "
                f"**Warning:** {n_warn} | **Skip:** {n_skip}  ",
                "",
            ]
            failed = [v for v in report.validation_debug if v.status in ("FAIL", "WARNING")]
            if failed:
                lines += [
                    "### Failed / Warning Rules",
                    "",
                    "| Rule | Category | Status | Severity |",
                    "|------|----------|--------|----------|",
                ]
                for v in failed:
                    lines.append(
                        f"| `{v.rule_id}` | {v.category} | {v.status} | {v.severity} |"
                    )
                lines.append("")

        if report.feedback_debug:
            recurring_count = sum(1 for f in report.feedback_debug if f.is_recurring)
            lines += [
                "---",
                "",
                "## Engine Feedback",
                "",
                f"**Feedback items:** {len(report.feedback_debug)} | "
                f"**Recurring:** {recurring_count}  ",
                "",
                "| ID | Engine | Priority | Recurring |",
                "|----|--------|----------|-----------|",
            ]
            for f in report.feedback_debug:
                recurring_label = "♻️ yes" if f.is_recurring else "no"
                lines.append(
                    f"| `{f.feedback_id}` | {f.engine_owner} | {f.priority} | {recurring_label} |"
                )
            lines.append("")

        lines += [
            "---",
            "",
            "_Full debug data: `review/debug/` subdirectory_",
            "",
            "Files: `debug-summary.json` · `scene-debug.json` · `validation-debug.json`"
            " · `scoring-debug.json` · `feedback-debug.json` · `execution-timeline.json`",
            "",
        ]
        (debug_dir / "debug-report.md").write_text("\n".join(lines), encoding="utf-8")

    # ── scene-debug.json ──────────────────────────────────────────────────────

    def _write_scene_debug(self, report: DebugReport, debug_dir: Path) -> None:
        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "total_scenes": report.total_scenes,
            "scenes": [s.to_dict() for s in report.scene_debug],
        }
        (debug_dir / "scene-debug.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── validation-debug.json ─────────────────────────────────────────────────

    def _write_validation_debug(self, report: DebugReport, debug_dir: Path) -> None:
        n_pass = sum(1 for v in report.validation_debug if v.status == "PASS")
        n_fail = sum(1 for v in report.validation_debug if v.status == "FAIL")
        n_warn = sum(1 for v in report.validation_debug if v.status == "WARNING")
        n_skip = sum(1 for v in report.validation_debug if v.status == "SKIP")

        by_category: dict[str, list[dict]] = {}
        for v in report.validation_debug:
            by_category.setdefault(v.category, []).append(v.to_dict())

        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "total_rules": len(report.validation_debug),
            "passed": n_pass,
            "failed": n_fail,
            "warnings": n_warn,
            "skipped": n_skip,
            "by_category": by_category,
            "rules": [v.to_dict() for v in report.validation_debug],
        }
        (debug_dir / "validation-debug.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── scoring-debug.json ────────────────────────────────────────────────────

    def _write_scoring_debug(self, report: DebugReport, debug_dir: Path) -> None:
        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "overall_score": report.overall_score,
            "letter_grade": report.letter_grade,
            "categories": [c.to_dict() for c in report.scoring_debug],
        }
        (debug_dir / "scoring-debug.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── feedback-debug.json ───────────────────────────────────────────────────

    def _write_feedback_debug(self, report: DebugReport, debug_dir: Path) -> None:
        recurring_count = sum(1 for f in report.feedback_debug if f.is_recurring)
        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "total_feedback": len(report.feedback_debug),
            "recurring_count": recurring_count,
            "feedback": [f.to_dict() for f in report.feedback_debug],
        }
        (debug_dir / "feedback-debug.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── execution-timeline.json ───────────────────────────────────────────────

    def _write_execution_timeline(self, report: DebugReport, debug_dir: Path) -> None:
        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "total_events": len(report.timeline),
            "total_processing_seconds": report.diagnostics.total_processing_seconds,
            "events": [e.to_dict() for e in report.timeline],
        }
        (debug_dir / "execution-timeline.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
