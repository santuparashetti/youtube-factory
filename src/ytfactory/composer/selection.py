"""A/B script selection with Script Judge + Guided Recomposer.

Flow:
  Composer A → Script B (graceful rehook degradation) → Script Judge
  → if hybrid: Guided Recomposer → rehook check → fallback to winner on failure
  → write script.md + judge-report.json
  → Human review (always, with judge evidence displayed)

Fallback chain (never raises to pipeline):
  1. Recomposed script → if passes QA + rehook → use it
  2. Recomposed fails → use judge winner (already passed)
  3. Judge errors → use Script A (first pass, already validated)
  4. Script B fails rehook → skip judge entirely, return Script A
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from loguru import logger
from rich.console import Console
from rich.table import Table

from ytfactory.composer.judge import JudgeVerdict, judge_scripts
from ytfactory.composer.pipeline import ComposerPipeline, ComposerRehookMissingError
from ytfactory.composer.recomposer import guided_recompose
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shared.pipeline_status import PipelineAbort

console = Console()

DIVIDER = "━" * 40
WORDS_PER_MINUTE = 140  # display estimate only


def run_composer_with_ab_selection(
    composer: ComposerPipeline,
    project_id: str,
    base_script_text: str | None = None,
) -> str:
    """Run the composer twice, judge the results, optionally recompose, write script.md.

    ``base_script_text`` is the source to compose from. When ``None`` it is read
    from ``script.md`` on disk.

    Returns the final script text (the chosen / recomposed version)."""
    script_dir = Path(WORKSPACE_DIR) / project_id / "script"
    script_dir.mkdir(parents=True, exist_ok=True)
    script_file = script_dir / "script.md"
    if base_script_text is None:
        base_script_text = script_file.read_text(encoding="utf-8")

    provider = composer.provider
    settings = composer._settings

    # ── Generate Script A ────────────────────────────────────────────────────
    composer.run(project_id, script_text=base_script_text)
    script_a_path = script_dir / "script-a.md"
    script_a_path.write_text(script_file.read_text(encoding="utf-8"), encoding="utf-8")
    script_a = script_a_path.read_text(encoding="utf-8")

    # ── Generate Script B (graceful rehook degradation) ──────────────────────
    script_b: Optional[str] = None
    try:
        composer.run(project_id, script_text=base_script_text)
        script_b_path = script_dir / "script-b.md"
        script_b_path.write_text(script_file.read_text(encoding="utf-8"), encoding="utf-8")
        script_b = script_b_path.read_text(encoding="utf-8")
    except ComposerRehookMissingError as exc:
        logger.warning(
            "A/B selection: Script B failed rehook validation — returning Script A automatically. "
            "Reason: {}",
            exc,
        )
        console.print(
            "\n[yellow]⚠ Script B failed rehook validation — Script A selected automatically.[/yellow]\n"
        )
        _write_final(script_a, script_file)
        # Exit path 1: Script B missing — no script-b.md exists, skip cleanup
        return script_a

    # ── Judge ────────────────────────────────────────────────────────────────
    verdict: Optional[JudgeVerdict] = judge_scripts(script_a, script_b, provider, settings)

    if verdict is None:
        logger.warning("Judge returned None — using Script A as safe default.")
        _write_final(script_a, script_file)
        # Exit path 2: Judge failed — winner is A, rename script-b-rejected
        _cleanup_ab_files(script_dir, winner="A", outcome="winner_A")
        return script_a

    _log_verdict(verdict)

    # ── Determine output ─────────────────────────────────────────────────────
    winner_text = script_a if verdict.winner == "A" else script_b

    if verdict.hybrid_recommended:
        recomposed = guided_recompose(script_a, script_b, verdict, provider, settings)
        if recomposed is not None:
            # Quality gate: verify recomposed doesn't regress from the original winner.
            # Compare winner_text (safe baseline) vs recomposed (candidate).
            # winner=="A" means baseline beat recomposed → regression → fall back.
            # winner=="B" or None (judge failed) → recomposed is as good or better → accept.
            quality_check = judge_scripts(winner_text, recomposed, provider, settings)
            if quality_check is not None and quality_check.winner == "A":
                logger.warning(
                    "Recomposed script failed quality gate "
                    "(baseline {:.1f} > recomposed {:.1f}) — falling back to judge winner.",
                    quality_check.script_a_score,
                    quality_check.script_b_score,
                )
                console.print(
                    "\n[yellow]⚠ Recomposed script lost quality check — "
                    "reverting to judge winner.[/yellow]\n"
                )
            else:
                _write_final(recomposed, script_file)
                _write_judge_report(verdict, project_id, outcome="recomposed")
                # Exit path 4: Recomposed — both were source material
                _cleanup_ab_files(script_dir, winner=None, outcome="recomposed")
                return recomposed
        else:
            logger.warning("Recomposer failed or skipped — falling back to judge winner.")

    _write_final(winner_text, script_file)
    _write_judge_report(verdict, project_id, outcome=f"winner_{verdict.winner}")
    # Exit path 3: Clean winner — rename the losing file
    _cleanup_ab_files(script_dir, winner=verdict.winner, outcome=f"winner_{verdict.winner}")
    return winner_text


def _cleanup_ab_files(
    script_dir: Path,
    winner: str | None,  # "A", "B", or None if recomposed
    outcome: str,        # "winner_A", "winner_B", "recomposed"
) -> None:
    script_a = script_dir / "script-a.md"
    script_b = script_dir / "script-b.md"

    if outcome == "recomposed":
        if script_a.exists():
            script_a.rename(script_dir / "script-a-source.md")
        if script_b.exists():
            script_b.rename(script_dir / "script-b-source.md")
    elif winner == "A":
        if script_b.exists():
            script_b.rename(script_dir / "script-b-rejected.md")
    elif winner == "B":
        if script_a.exists():
            script_a.rename(script_dir / "script-a-rejected.md")


def _write_final(text: str, script_file: Path) -> None:
    script_file.write_text(text, encoding="utf-8")


def _write_judge_report(verdict: JudgeVerdict, project_id: str, outcome: str) -> None:
    report_path = Path(WORKSPACE_DIR) / project_id / "judge-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"outcome": outcome, **verdict.model_dump()}, indent=2),
        encoding="utf-8",
    )
    logger.info("Judge report written: {}", report_path)


def _log_verdict(verdict: JudgeVerdict) -> None:
    console.print(f"\n{DIVIDER}")
    console.print("  [bold]Script Judge Verdict[/bold]")
    console.print(f"{DIVIDER}")
    console.print(f"  Script A: {verdict.script_a_score}/10")
    console.print(f"  Script B: {verdict.script_b_score}/10")
    console.print(f"  Winner: Script {verdict.winner}")
    console.print(f"  Hybrid recommended: {verdict.hybrid_recommended}")
    console.print(f"  {verdict.verdict_summary}")

    if verdict.sections:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Section")
        table.add_column("Winner")
        table.add_column("Reason")
        for s in verdict.sections:
            table.add_row(s.name, f"Script {s.winner}", s.reason)
        console.print(table)

    console.print(f"{DIVIDER}\n")
