"""Report generation for the Video Quality Review Engine V1.

Produces:
  - review-report.md  — human-readable Markdown summary
  - scene-review.json — per-scene detail
  - review-debug.json — full machine-readable diagnostics

Stubs (written by future modules):
  - quality-score.json
  - root-cause-report.json
  - engine-feedback.json
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.review.artifacts import (
    engine_feedback_path,
    quality_score_path,
    review_debug_path,
    review_directory,
    review_report_path,
    root_cause_report_path,
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

        # Extension points note
        lines += [
            "---",
            "",
            "## Extension Points (Future Modules)",
            "",
            "The following modules are designed as integration points for future V1 specifications:",
            "",
            "| Module | Status | Output file |",
            "|--------|--------|-------------|",
            "| Quality Scoring Engine V1 | _not implemented_ | `quality-score.json` |",
            "| Root Cause Analysis Engine V1 | _not implemented_ | `root-cause-report.json` |",
            "| Engine Feedback Loop V1 | _not implemented_ | `engine-feedback.json` |",
            "| Auto Remediation Engine V1 | _not implemented_ | — |",
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

    def _write_extension_stubs(self, report: ReviewReport) -> None:
        """Write placeholder JSON for future module outputs.

        These files mark the extension points so downstream tools can detect
        them even before the respective engines are implemented.
        """
        stub_meta = {
            "version": "stub",
            "project_id": report.project_id,
            "verdict": report.verdict,
            "timestamp": report.timestamp,
            "status": "not_implemented",
            "message": "This file will be populated by the corresponding V1 engine.",
        }

        quality_score_path(report.project_id).write_text(
            json.dumps({**stub_meta, "engine": "Quality Scoring Engine V1"}, indent=2),
            encoding="utf-8",
        )
        root_cause_report_path(report.project_id).write_text(
            json.dumps(
                {**stub_meta, "engine": "Root Cause Analysis Engine V1"}, indent=2
            ),
            encoding="utf-8",
        )
        engine_feedback_path(report.project_id).write_text(
            json.dumps({**stub_meta, "engine": "Engine Feedback Loop V1"}, indent=2),
            encoding="utf-8",
        )
