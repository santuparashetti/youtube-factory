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
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from ytfactory.config.settings import Settings
from ytfactory.editorial_qa import checkpoint as qa_checkpoint
from ytfactory.editorial_qa.pipeline import EditorialQAPipeline
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()


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
            # Hand-edited during the pause — same QA scrutiny as generated text.
            console.print(
                Panel(
                    "script.md changed since the last review — re-running "
                    "Editorial QA on the edit before continuing (report-only, "
                    "no gating).",
                    title="Human Review Gate — Script Changed",
                    border_style="yellow",
                )
            )
            EditorialQAPipeline(self._settings).run(project_id, script_text=script_text)

        if auto_mode:
            qa_checkpoint.record_hash(project_id, script_text)
            return script_text

        word_count = len(script_text.split())
        console.print(
            Panel(
                f"[bold]Final Script Review[/bold]\nWords: {word_count}\n\n"
                f"{_format_qa_summary(project_id)}",
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
