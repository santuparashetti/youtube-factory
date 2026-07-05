"""Report generation for the Quality Scoring Engine V1.

Produces four output files under workspace/jobs/<project_id>/review/:
  - quality-score.json      overall score + grade + verdict (replaces stub)
  - quality-report.md       human-readable Markdown summary
  - score-breakdown.json    per-category detail
  - score-history.json      cumulative run history (appended on each run)
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.review.artifacts import review_directory
from ytfactory.review.scoring.models import QualityScoreReport


def quality_score_path(project_id: str) -> Path:
    return review_directory(project_id) / "quality-score.json"


def quality_report_md_path(project_id: str) -> Path:
    return review_directory(project_id) / "quality-report.md"


def score_breakdown_path(project_id: str) -> Path:
    return review_directory(project_id) / "score-breakdown.json"


def score_history_path(project_id: str) -> Path:
    return review_directory(project_id) / "score-history.json"


class QualityScoringReporter:
    """Write all Quality Scoring Engine V1 artefacts."""

    def write(self, report: QualityScoreReport) -> Path:
        """Write all four output files and return the review directory."""
        review_dir = review_directory(report.project_id)
        self._write_quality_score(report)
        self._write_quality_report_md(report)
        self._write_score_breakdown(report)
        self._append_score_history(report)
        return review_dir

    # ── quality-score.json ────────────────────────────────────────────────

    def _write_quality_score(self, report: QualityScoreReport) -> None:
        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "overall_score": report.overall_score,
            "letter_grade": report.letter_grade,
            "verdict": report.verdict,
            "publish_threshold": report.publish_threshold,
            "warning_threshold": report.warning_threshold,
            "critical_threshold": report.critical_threshold,
            "processing_time_seconds": report.processing_time_seconds,
        }
        quality_score_path(report.project_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── quality-report.md ─────────────────────────────────────────────────

    def _write_quality_report_md(self, report: QualityScoreReport) -> None:
        verdict_icon = "✅ PASS" if report.verdict == "PASS" else "❌ FAIL"
        grade_emoji = {
            "A+": "🏆", "A": "🥇", "B": "🥈", "C": "🥉", "D": "⚠️", "F": "❌"
        }.get(report.letter_grade, "")

        lines = [
            "# Quality Scoring Report",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Verdict:** {verdict_icon}  ",
            f"**Overall Score:** {report.overall_score:.1f}/100  ",
            f"**Grade:** {grade_emoji} {report.letter_grade}  ",
            f"**Timestamp:** {report.timestamp}  ",
            f"**Processing time:** {report.processing_time_seconds:.3f}s  ",
            "",
            "---",
            "",
            "## Score Summary",
            "",
            "| Threshold | Value | Status |",
            "|-----------|-------|--------|",
            f"| Publish (PASS) | {report.publish_threshold:.0f} | "
            f"{'✅ met' if report.overall_score >= report.publish_threshold else '❌ not met'} |",
            f"| Warning | {report.warning_threshold:.0f} | "
            f"{'✅ OK' if report.overall_score >= report.warning_threshold else '⚠️ below'} |",
            f"| Critical | {report.critical_threshold:.0f} | "
            f"{'✅ OK' if report.overall_score >= report.critical_threshold else '🔴 critical'} |",
            "",
            "---",
            "",
            "## Category Scores",
            "",
            "| Category | Raw Score | Weight | Weighted | Grade | Confidence |",
            "|----------|-----------|--------|----------|-------|------------|",
        ]

        for cat, cs in sorted(report.category_scores.items()):
            grade = _grade_from_score(cs.raw_score)
            grade_icon = {"A+": "🏆", "A": "🥇", "B": "🥈", "C": "🥉", "D": "⚠️", "F": "❌"}.get(grade, "")
            lines.append(
                f"| {cat.title()} | {cs.raw_score:.1f} | {cs.weight:.0%} | "
                f"{cs.weighted_score:.2f} | {grade_icon} {grade} | {cs.confidence:.0%} |"
            )

        lines += ["", "---", ""]

        # Per-category detail
        lines += ["## Category Details", ""]
        for cat, cs in sorted(report.category_scores.items()):
            lines += [
                f"### {cat.title()} — {cs.raw_score:.1f}/100",
                "",
                f"_{cs.summary}_",
                "",
            ]
            if cs.evidence:
                lines.append("**Issues found:**")
                for ev in cs.evidence[:5]:
                    lines.append(f"- {ev}")
                lines.append("")

        # Improvement recommendations
        if report.improvement_recommendations:
            lines += ["---", "", "## Improvement Recommendations", ""]
            for i, rec in enumerate(report.improvement_recommendations, start=1):
                lines.append(f"{i}. {rec}")
            lines.append("")

        lines += [
            "---",
            "",
            "_Full details: `review/score-breakdown.json` · `review/score-history.json`_",
            "",
        ]

        quality_report_md_path(report.project_id).write_text(
            "\n".join(lines), encoding="utf-8"
        )

    # ── score-breakdown.json ──────────────────────────────────────────────

    def _write_score_breakdown(self, report: QualityScoreReport) -> None:
        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "overall_score": report.overall_score,
            "letter_grade": report.letter_grade,
            "verdict": report.verdict,
            "weights": {
                cat: cs.weight for cat, cs in report.category_scores.items()
            },
            "categories": {
                cat: cs.to_dict() for cat, cs in report.category_scores.items()
            },
            "improvement_recommendations": report.improvement_recommendations,
            "weight_distribution": {
                cat: f"{cs.weight:.0%}" for cat, cs in report.category_scores.items()
            },
            "confidence_distribution": {
                cat: round(cs.confidence, 3) for cat, cs in report.category_scores.items()
            },
            "failed_category_summary": {
                cat: cs.failed_rules
                for cat, cs in report.category_scores.items()
                if cs.failed_rules
            },
        }
        score_breakdown_path(report.project_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── score-history.json ────────────────────────────────────────────────

    def _append_score_history(self, report: QualityScoreReport) -> None:
        history_file = score_history_path(report.project_id)
        if history_file.exists():
            try:
                existing = json.loads(history_file.read_text(encoding="utf-8"))
                runs = existing.get("history", [])
            except (json.JSONDecodeError, OSError):
                runs = []
        else:
            runs = []

        runs.append(
            {
                "timestamp": report.timestamp,
                "run_number": len(runs) + 1,
                "overall_score": report.overall_score,
                "letter_grade": report.letter_grade,
                "verdict": report.verdict,
            }
        )

        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "total_runs": len(runs),
            "history": runs,
        }
        history_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _grade_from_score(score: float) -> str:
    if score >= 95:
        return "A+"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"
