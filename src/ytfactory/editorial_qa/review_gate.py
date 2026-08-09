"""Final Script Review Gate — human review checkpoint between script
finalization (post Editorial QA) and scene planning.

FLAGS/PAUSES, never auto-rewrites (same rule as the QA stage itself). The
hash-guard means a hand-edit to script.md during the pause gets the same QA
scrutiny as generated text: unchanged since last review -> QA already valid,
skip straight through; changed -> re-run Editorial QA on the edit first
(report-only, no gating), then present the new report before continuing.

Callable from both the LangGraph node (agents/nodes/human_review.py) and the
direct BuildPipeline/TwoPhasePipeline call paths.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from loguru import logger
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from ytfactory.agents.prompts.script_writer import NARRATION_WPM
from ytfactory.config.settings import Settings
from ytfactory.editorial_qa import checkpoint as qa_checkpoint
from ytfactory.editorial_qa.pipeline import EditorialQAPipeline
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()


def _run_editorial_fix_loop(
    project_id: str,
    script_text: str,
    qa_report: dict,
    settings: Settings,
) -> str:
    """After Editorial QA, attempt one targeted fix pass for flagged issues.

    - Reads flagged checks from the QA report.
    - Calls the polisher's targeted fix function with those checks as context.
    - Saves the fixed script and re-runs QA once to confirm.
    - Returns the (possibly fixed) script. Never raises.
    """
    checks = qa_report.get("checks") or {}
    flagged = [
        (name, check)
        for name, check in checks.items()
        if check.get("flagged") and not check.get("invalid")
    ]
    if not flagged:
        return script_text

    flag_names = ", ".join(name for name, _ in flagged)
    console.print(
        f"\n[bold magenta]✏️  Editorial Fix Pass[/bold magenta] — "
        f"fixing: [yellow]{flag_names}[/yellow]"
    )

    from ytfactory.agents.nodes.script_selector_polisher import apply_editorial_fixes

    fixed = apply_editorial_fixes(script_text, flagged, settings)
    if not fixed or fixed.strip() == script_text.strip():
        console.print("[dim]  Fix pass produced no changes — keeping original.[/dim]")
        return script_text

    # Persist the fixed script
    script_dir = Path(WORKSPACE_DIR) / project_id / "script"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "script.md").write_text(fixed, encoding="utf-8")
    console.print("[green]  ✓[/green] Fix applied — re-running Editorial QA to verify...")

    # One confirmation pass (no further fix loop)
    try:
        EditorialQAPipeline(settings).run(project_id, script_text=fixed)
    except Exception as exc:  # noqa: BLE001
        logger.error("Editorial QA re-run after fix failed: {}", exc)

    return fixed


def _format_qa_summary(project_id: str) -> str:
    report_path = Path(WORKSPACE_DIR) / project_id / "qa" / "editorial-qa-report.json"
    if not report_path.exists():
        return "[dim]No Editorial QA report found.[/dim]"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "[dim]Editorial QA report unreadable.[/dim]"

    checks = report.get("checks", {})
    flagged = [name for name, c in checks.items() if c.get("flagged")]
    invalid = report.get("invalid_checks", [])
    lines = [
        f"Editorial QA: {len(flagged)} flagged, {len(invalid)} invalid, "
        f"score {report.get('editorial_score', 'n/a')}"
    ]
    for name in flagged:
        lines.append(f"  [yellow]⚠[/yellow] {name}: {checks[name].get('note', '')}")
    return "\n".join(lines)


def _load_judge_report(project_id: str) -> dict | None:
    report_path = Path(WORKSPACE_DIR) / project_id / "judge-report.json"
    if not report_path.exists():
        return None
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _format_judge_summary(report: dict | None) -> str:
    if not report:
        return ""
    outcome = report.get("outcome", "unknown")
    winner = report.get("winner", "?")
    a_score = report.get("script_a_score", "?")
    b_score = report.get("script_b_score", "?")
    summary = report.get("verdict_summary", "")
    lines = [
        f"[bold]Script Judge Report[/bold] — outcome: {outcome}",
        f"  Script A: {a_score}/10  |  Script B: {b_score}/10  |  Winner: Script {winner}",
    ]
    if summary:
        lines.append(f"  {summary}")
    sections = report.get("sections") or []
    if sections:
        lines.append("  Sections:")
        for s in sections:
            lines.append(f"    {s.get('name', '?')} → Script {s.get('winner', '?')}: {s.get('reason', '')}")
    return "\n".join(lines)


class FinalScriptReviewGate:
    """Presents the finalized script + its QA report; hash-guards against a
    hand-edit since the last review. Never rewrites the script — continue /
    stop / regenerate are the only actions, and none of them touch the text."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def run(self, project_id: str, script_text: str, *, auto_mode: bool = False) -> str:
        recorded_hash = qa_checkpoint.read_recorded_hash(project_id)
        current_hash = qa_checkpoint.script_hash(script_text)

        if recorded_hash is not None:
            if current_hash == recorded_hash:
                # Unchanged since last review — QA already valid, skip straight through.
                return script_text
            # Hash changed (polisher ran, or hand-edited) — QA + auto-fix loop.
            console.print(
                Panel(
                    "script.md changed since the last review — re-running "
                    "Editorial QA on the edit before continuing (report-only, "
                    "no gating).",
                    title="Human Review Gate — Script Changed",
                    border_style="yellow",
                )
            )
            qa_report = EditorialQAPipeline(self._settings).run(
                project_id, script_text=script_text
            )
            # Auto-fix loop: targeted polish for flagged issues, then one QA re-run.
            script_text = _run_editorial_fix_loop(
                project_id, script_text, qa_report, self._settings
            )

        # Judge report — load once and force review for recomposed scripts.
        judge_report = _load_judge_report(project_id)
        if judge_report and judge_report.get("outcome") == "recomposed" and auto_mode:
            logger.warning(
                "Auto-mode disabled for recomposed scripts — human review required."
            )
            auto_mode = False

        if auto_mode:
            qa_checkpoint.record_hash(project_id, script_text)
            return script_text

        word_count = len(script_text.split())
        minutes = word_count / NARRATION_WPM
        judge_summary = _format_judge_summary(judge_report)
        console.print(
            Panel(
                f"[bold]Final Script Review[/bold]\nWords: {word_count} (~{minutes:.1f} min)\n\n"
                f"{_format_qa_summary(project_id)}"
                + (f"\n\n{judge_summary}" if judge_summary else ""),
                title="Human Review Gate",
                border_style="yellow",
            )
        )
        console.print(
            Markdown(
                script_text[:3000]
                + ("\n\n*[...truncated for review]*" if len(script_text) > 3000 else "")
            )
        )
        console.print()

        action = (
            typer.prompt(
                "Action? [c]ontinue / [s]top (leave for manual edit) / [r]egenerate",
                default="c",
            )
            .strip()
            .lower()
        )

        if action.startswith("s"):
            raise typer.Abort()
        if action.startswith("r"):
            qa_checkpoint.clear(project_id)
            console.print(
                "[yellow]Regenerate requested — checkpoint cleared. Re-run "
                "script generation (enhancer / structural pass), then resume.[/yellow]"
            )
            raise typer.Abort()

        qa_checkpoint.record_hash(project_id, script_text)
        return script_text
