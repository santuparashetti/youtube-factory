"""Report generation for the Video Quality Review Engine V1.

Produces:
  - review-report.md  — human-readable Markdown summary
  - scene-review.json — per-scene detail
  - review-debug.json — full machine-readable diagnostics

Implemented (written by dedicated reporters, not stubs):
  - quality-score.json / quality-report.md / score-breakdown.json /
    score-history.json — written by QualityScoringReporter
  - root-cause-report.md / root-cause.json / engine-owner-summary.json /
    recurring-issues.json — written by RCAReporter
  - engine-feedback.json / engine-feedback.md / engine-priority-report.json /
    recurring-patterns.json / improvement-roadmap.md — written by EFLReporter
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.review.artifacts import (
    review_debug_path,
    review_directory,
    review_report_path,
    scene_review_path,
)
from ytfactory.review.models import ReviewReport


class ReviewReporter:
    """Write all review artefacts to workspace/jobs/<project_id>/review/."""

    def write(self, report: ReviewReport) -> Path:
        """Write all output files and return the review directory path."""
        project_id = report.project_id
        _dir = review_directory(project_id)

        self._write_report_md(report)
        self._write_scene_review(report)
        self._write_debug_json(report)
        self._write_extension_stubs(report)

        return _dir

    # ── Review report (Markdown) ──────────────────────────────────────────

    def _write_report_md(self, report: ReviewReport) -> None:
        verdict_icon = "✅ PASS" if report.verdict == "PASS" else "❌ FAIL"
        lines = [
            "# Video Quality Review Report",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Verdict:** {verdict_icon}  ",
            f"**Timestamp:** {report.timestamp}  ",
            f"**Processing time:** {report.processing_time_seconds:.2f}s  ",
            "",
            "---",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total scenes | {report.total_scenes} |",
            f"| Scenes passed | {report.scenes_passed} |",
            f"| Scenes failed | {report.scenes_failed} |",
            f"| Critical errors | {len(report.all_errors)} |",
            f"| Warnings | {len(report.all_warnings)} |",
            f"| Final video | {report.final_video_path or '—'} |",
            f"| Final video size | {report.final_video_size_mb:.1f} MB |",
        ]
        if report.final_video_duration_seconds:
            m, s = divmod(int(report.final_video_duration_seconds), 60)
            lines.append(f"| Final video duration | {m}m {s}s |")
        lines += ["", "---", ""]

        # Stage results
        lines += ["## Stage Results", ""]
        for stage in report.stage_results:
            status = "✅ PASS" if stage.passed else "❌ FAIL"
            lines.append(
                f"### Stage: {stage.stage_name.replace('_', ' ').title()} — {status}"
            )
            lines.append(
                f"- Checks: {stage.checks_passed}/{stage.checks_run} passed  "
                f"({stage.duration_seconds:.3f}s)"
            )
            if stage.errors:
                lines.append("- **Errors:**")
                for e in stage.errors:
                    lines.append(f"  - ❌ {e}")
            if stage.warnings:
                lines.append("- **Warnings:**")
                for w in stage.warnings:
                    lines.append(f"  - ⚠️  {w}")
            lines.append("")

        # Errors section
        if report.all_errors:
            lines += ["---", "", "## Critical Errors", ""]
            for e in report.all_errors:
                lines.append(f"- ❌ {e}")
            lines.append("")

        # Warnings section
        if report.all_warnings:
            lines += ["---", "", "## Warnings", ""]
            for w in report.all_warnings:
                lines.append(f"- ⚠️  {w}")
            lines.append("")

        # Validation Rules V1 summary
        val = report.validation_report
        if val:
            lines += ["---", "", "## Validation Rules V1", ""]
            val_verdict_icon = "✅ PASS" if val.get("verdict") == "PASS" else "❌ FAIL"
            lines += [
                f"**Validation verdict:** {val_verdict_icon}  ",
                f"**Rules run:** {val.get('total_rules_run', 0)}  ",
                f"**Passed:** {val.get('total_passed', 0)} | "
                f"**Failed:** {val.get('total_failed', 0)} | "
                f"**Warnings:** {val.get('total_warnings', 0)} | "
                f"**Skipped:** {val.get('total_skipped', 0)}  ",
                "",
            ]
            scores = val.get("category_scores", {})
            if scores:
                lines += [
                    "### Category Scores",
                    "",
                    "| Category | Pass Rate |",
                    "|----------|-----------|",
                ]
                for cat, score in sorted(scores.items()):
                    bar = "✅" if score >= 1.0 else ("⚠️" if score >= 0.7 else "❌")
                    lines.append(f"| {cat} | {bar} {score:.0%} |")
                lines.append("")
            critical = val.get("critical_failures", [])
            if critical:
                lines += ["### Critical Validation Failures", ""]
                for f in critical:
                    lines.append(
                        f"- ❌ `{f['rule_id']}` ({f['severity']}): {f['description']}"
                    )
                lines.append("")
            lines += ["_Full details: `review/validation-report.json`_", ""]

        # Extension points note
        lines += [
            "---",
            "",
            "## Module Status",
            "",
            "Status of all review-layer V1 modules:",
            "",
            "| Module | Status | Output file |",
            "|--------|--------|-------------|",
            "| Quality Scoring Engine V1 | ✅ implemented | `quality-score.json`, `quality-report.md`, `score-breakdown.json`, `score-history.json` |",
            "| Root Cause Analysis Engine V1 | ✅ implemented | `root-cause-report.md`, `root-cause.json`, `engine-owner-summary.json`, `recurring-issues.json` |",
            "| Engine Feedback Loop V1 | ✅ implemented | `engine-feedback.json`, `engine-feedback.md`, `engine-priority-report.json`, `recurring-patterns.json`, `improvement-roadmap.md` |",
            "| Video Review Debug Mode V1 | ✅ implemented | `debug/debug-report.md`, `debug/debug-summary.json`, `debug/scene-debug.json`, `debug/validation-debug.json`, `debug/scoring-debug.json`, `debug/feedback-debug.json`, `debug/execution-timeline.json` |",
            "| Auto Remediation Engine V1 | ✅ implemented | `remediation/remediation-plan.json`, `remediation/remediation-report.md`, `remediation/retry-history.json`, `remediation/regenerated-assets.json` |",
            "",
        ]

        review_report_path(report.project_id).write_text(
            "\n".join(lines), encoding="utf-8"
        )

    # ── scene-review.json ─────────────────────────────────────────────────

    def _write_scene_review(self, report: ReviewReport) -> None:
        payload = {
            "project_id": report.project_id,
            "verdict": report.verdict,
            "timestamp": report.timestamp,
            "total_scenes": report.total_scenes,
            "scenes_passed": report.scenes_passed,
            "scenes_failed": report.scenes_failed,
            "scenes": [sv.to_dict() for sv in report.scene_reviews],
        }
        scene_review_path(report.project_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── review-debug.json ─────────────────────────────────────────────────

    def _write_debug_json(self, report: ReviewReport) -> None:
        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "verdict": report.verdict,
            "timestamp": report.timestamp,
            "processing_time_seconds": report.processing_time_seconds,
            "total_scenes": report.total_scenes,
            "scenes_passed": report.scenes_passed,
            "scenes_failed": report.scenes_failed,
            "final_video_path": report.final_video_path,
            "final_video_size_mb": report.final_video_size_mb,
            "final_video_duration_seconds": report.final_video_duration_seconds,
            "all_errors": report.all_errors,
            "all_warnings": report.all_warnings,
            "stage_results": [s.to_dict() for s in report.stage_results],
            "scene_reviews": [s.to_dict() for s in report.scene_reviews],
            # Extension point fields — populated by future modules
            "quality_score": report.quality_score,
            "root_cause_hint": report.root_cause_hint,
            "feedback_payload": report.feedback_payload,
        }
        review_debug_path(report.project_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── Extension-point stub files ────────────────────────────────────────

    def _write_extension_stubs(self, _report: ReviewReport) -> None:
        """All extension-point engines are now implemented; no stubs remain.

        Formerly wrote quality-score.json, root-cause-report.json, and
        engine-feedback.json as "not_implemented" stubs. All three are now
        written by their dedicated reporters (QualityScoringReporter,
        RCAReporter, EFLReporter). This method is retained so that tests
        relying on the call graph continue to work without modification.
        """
