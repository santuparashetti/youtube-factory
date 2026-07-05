"""Report generation for Auto Remediation Engine V1.

Produces four output files under workspace/jobs/<project_id>/remediation/:
  - remediation-plan.json      planned actions list
  - remediation-report.md      human-readable Markdown summary
  - retry-history.json         per-action execution attempts across cycles
  - regenerated-assets.json    all artifacts deleted and regenerated
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.shared.constants import WORKSPACE_DIR

from ytfactory.review.remediation.models import RemediationReport


def remediation_directory(project_id: str) -> Path:
    """Return (and create) workspace/jobs/<project_id>/remediation/."""
    directory = Path(WORKSPACE_DIR) / project_id / "remediation"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def remediation_plan_path(project_id: str) -> Path:
    return remediation_directory(project_id) / "remediation-plan.json"


def remediation_report_md_path(project_id: str) -> Path:
    return remediation_directory(project_id) / "remediation-report.md"


def retry_history_path(project_id: str) -> Path:
    return remediation_directory(project_id) / "retry-history.json"


def regenerated_assets_path(project_id: str) -> Path:
    return remediation_directory(project_id) / "regenerated-assets.json"


class RemediationReporter:
    """Write all Auto Remediation Engine V1 artefacts."""

    def write(self, report: RemediationReport) -> Path:
        """Write all four output files and return the remediation directory."""
        self._write_plan_json(report)
        self._write_report_md(report)
        self._write_retry_history(report)
        self._write_regenerated_assets(report)
        return remediation_directory(report.project_id)

    # ── remediation-plan.json ─────────────────────────────────────────────

    def _write_plan_json(self, report: RemediationReport) -> None:
        remediation_plan_path(report.project_id).write_text(
            json.dumps(report.plan.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── remediation-report.md ─────────────────────────────────────────────

    def _write_report_md(self, report: RemediationReport) -> None:
        dr = "🧪 DRY RUN — " if report.dry_run else ""
        verdict_icon = "✅" if report.final_verdict == "PASS" else "❌"

        score_str = (
            f"{report.final_quality_score:.1f}"
            if report.final_quality_score is not None
            else "N/A"
        )
        plan_score_str = (
            f"{report.plan.quality_score_before:.1f}"
            if report.plan.quality_score_before is not None
            else "N/A"
        )

        lines = [
            "# Auto Remediation Engine Report",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Status:** {dr}{verdict_icon} {report.final_verdict}  ",
            f"**Stopped reason:** `{report.stopped_reason}`  ",
            f"**Timestamp:** {report.timestamp}  ",
            f"**Processing time:** {report.processing_time_seconds:.3f}s  ",
            "",
            "---",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Quality score before | {plan_score_str} |",
            f"| Quality score after | {score_str} |",
            f"| Quality threshold | {report.plan.quality_threshold:.1f} |",
            f"| Total cycles | {report.total_cycles} |",
            f"| Total actions executed | {report.total_actions_executed} |",
            f"| Actions succeeded | {report.total_actions_succeeded} |",
            f"| Actions failed | {report.total_actions_failed} |",
            f"| Regenerated assets | {len(report.regenerated_assets)} |",
            f"| Dry run | {'Yes' if report.dry_run else 'No'} |",
            "",
        ]

        # Decision summary
        lines += [
            "## Decision Summary",
            "",
            report.plan.decision_summary or "—",
            "",
        ]

        # Planned actions
        if report.plan.actions:
            lines += [
                "---",
                "",
                f"## Planned Actions ({report.plan.total_actions})",
                "",
                "| ID | Strategy | Engine | Category | Severity | Confidence | Cost | Status |",
                "|----|----------|--------|----------|----------|------------|------|--------|",
            ]
            for a in report.plan.actions:
                scene_tag = (
                    f" (scene {a.scene_index})" if a.scene_index is not None else ""
                )
                lines.append(
                    f"| {a.action_id} | {a.strategy} | {a.engine_target}{scene_tag} | "
                    f"{a.category} | {a.severity} | {a.confidence}% | "
                    f"{a.estimated_cost:.2f} | {a.status} |"
                )
            lines.append("")
        else:
            lines += [
                "---",
                "",
                "> No actions planned.",
                "",
            ]

        # Cycle details
        if report.cycles:
            lines += ["---", "", "## Remediation Cycles", ""]
            for cycle in report.cycles:
                threshold_tag = " ✅ threshold met" if cycle.threshold_met else ""
                score_before_str = (
                    f"{cycle.quality_score_before:.1f}"
                    if cycle.quality_score_before is not None
                    else "N/A"
                )
                score_after_str = (
                    f"{cycle.quality_score_after:.1f}"
                    if cycle.quality_score_after is not None
                    else "N/A"
                )
                lines += [
                    f"### Cycle {cycle.cycle_number}{threshold_tag}",
                    "",
                    f"- **Score:** {score_before_str} → {score_after_str}  ",
                    f"- **Verdict:** {cycle.verdict_before} → {cycle.verdict_after}  ",
                    f"- **Actions:** {cycle.actions_succeeded}/{cycle.actions_attempted} succeeded  ",
                    f"- **Elapsed:** {cycle.elapsed_seconds:.3f}s  ",
                    "",
                ]

        # Regenerated assets
        if report.regenerated_assets:
            lines += [
                "---",
                "",
                f"## Regenerated Assets ({len(report.regenerated_assets)})",
                "",
                "| Cycle | Strategy | Category | File |",
                "|-------|----------|----------|------|",
            ]
            for asset in report.regenerated_assets:
                scene_tag = (
                    f" (scene {asset.scene_index})"
                    if asset.scene_index is not None
                    else ""
                )
                lines.append(
                    f"| {asset.cycle} | {asset.strategy} | {asset.category}{scene_tag} | "
                    f"`{asset.file_path}` |"
                )
            lines.append("")

        lines += [
            "---",
            "",
            "_Full details: `remediation/remediation-plan.json` · "
            "`remediation/retry-history.json` · "
            "`remediation/regenerated-assets.json`_",
            "",
        ]

        remediation_report_md_path(report.project_id).write_text(
            "\n".join(lines), encoding="utf-8"
        )

    # ── retry-history.json ────────────────────────────────────────────────

    def _write_retry_history(self, report: RemediationReport) -> None:
        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "total_entries": len(report.retry_history),
            "entries": [e.to_dict() for e in report.retry_history],
        }
        retry_history_path(report.project_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── regenerated-assets.json ───────────────────────────────────────────

    def _write_regenerated_assets(self, report: RemediationReport) -> None:
        payload = {
            "version": "v1",
            "project_id": report.project_id,
            "timestamp": report.timestamp,
            "total_assets": len(report.regenerated_assets),
            "assets": [a.to_dict() for a in report.regenerated_assets],
        }
        regenerated_assets_path(report.project_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
