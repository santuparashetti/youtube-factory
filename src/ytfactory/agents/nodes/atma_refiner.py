"""Graph nodes for the Atma Theory 7-Beat Script Refinement Pipeline.

Production path nodes (wired into agents/graph.py):
  script_identity_node      — deterministic ScriptIdentity extraction
  atma_7beat_refiner_node   — 7-Beat LLM editing pass
  script_validator_node     — pre-review validation
  human_review_atma_script_node — human Accept/Reject + targeted refinement loop

The old A/B composition path (source_refiner → composer → script_selector_polisher)
remains importable and test-passable but is no longer wired as the default route.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from loguru import logger
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from ytfactory.agents.state import VideoState
from ytfactory.atma_refiner.identity import extract_script_identity
from ytfactory.atma_refiner.pipeline import AtmaRefinerPipeline
from ytfactory.atma_refiner.revision_store import RevisionStore
from ytfactory.atma_refiner.validator import ScriptValidator
from ytfactory.config.settings import Settings
from ytfactory.domain.script_revision import ScriptIdentity
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()


# ── Node 1: Script Identity extraction ──────────────────────────────────────


def script_identity_node(state: VideoState) -> dict:
    """Extract ScriptIdentity deterministically from the base/raw script.

    Runs before any LLM refinement call. No LLM is invoked here.
    Writes script-identity.json for observability.
    """
    project_id = state["project_id"]
    script_dir = Path(WORKSPACE_DIR) / project_id / "script"
    script_dir.mkdir(parents=True, exist_ok=True)

    source_script = state.get("script_md", "")
    if not source_script:
        script_file = script_dir / "script.md"
        if script_file.exists():
            source_script = script_file.read_text(encoding="utf-8")

    if not source_script:
        raise FileNotFoundError(
            f"ScriptIdentityNode: no source script in state or at "
            f"{script_dir / 'script.md'}. Run import-script first."
        )

    topic = state.get("topic", "")
    identity = extract_script_identity(source_script, topic=topic)

    identity_dict = identity.to_dict()
    (script_dir / "script-identity.json").write_text(
        json.dumps(identity_dict, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    logger.info(
        "ScriptIdentityNode: extracted identity — topic={!r}, thesis={!r}",
        identity.core_topic[:60] if identity.core_topic else "",
        identity.core_thesis[:80] if identity.core_thesis else "",
    )
    console.print(
        Panel(
            f"[green]✓[/green] Script identity extracted\n"
            f"  Topic: {identity.core_topic[:80] or '(inferred)'}\n"
            f"  Thesis: {(identity.core_thesis[:100] + '...') if len(identity.core_thesis) > 100 else identity.core_thesis or '(none found)'}\n"
            f"  Key facts: {len(identity.important_factual_details)}\n"
            f"  Visual moments: {len(identity.important_visual_moments)}",
            title="Script Identity",
            border_style="blue",
        )
    )

    return {"script_identity": identity_dict}


# ── Node 2: Atma 7-Beat refinement ──────────────────────────────────────────


def atma_7beat_refiner_node(state: VideoState) -> dict:
    """Run the 7-Beat editor pass on the base/raw script.

    Uses ScriptIdentity (from state) as a protected constraint. Writes
    atma-refined.md and atma-refinement-report.json. Saves the revision
    to the RevisionStore for lineage tracking.

    When state contains atma_reviewer_feedback and atma_current_refined,
    runs a targeted refinement addressing only the flagged issues.
    """
    project_id = state["project_id"]
    settings = Settings()

    base_script = state.get("script_md", "")
    if not base_script:
        script_file = Path(WORKSPACE_DIR) / project_id / "script" / "script.md"
        if script_file.exists():
            base_script = script_file.read_text(encoding="utf-8")

    identity_dict = state.get("script_identity") or {}
    identity = ScriptIdentity.from_dict(identity_dict)
    beats = state.get("beats") or []
    target_minutes = int(state.get("target_minutes", 5))

    # Targeted refinement after rejection
    reviewer_feedback = state.get("atma_reviewer_feedback")
    current_refined = state.get("atma_current_refined")

    pipeline = AtmaRefinerPipeline(settings)
    refined, validation = pipeline.run(
        project_id,
        base_script=base_script,
        identity=identity,
        beats=beats,
        reviewer_feedback=reviewer_feedback,
        current_refined=current_refined,
        target_minutes=target_minutes,
    )

    store = RevisionStore(project_id)
    parent_id: str | None = None
    existing = store.list_revisions()
    if existing:
        parent_id = existing[-1].revision_id

    revision = store.save_revision(refined, parent_id=parent_id)

    logger.info(
        "Atma7BeatRefinerNode: revision #{} saved ({})",
        revision.revision_number,
        revision.revision_id,
    )

    return {
        "script_md": refined,
        "atma_validation": validation.to_dict(),
        "atma_current_refined": refined,
        "atma_current_revision_id": revision.revision_id,
        "atma_revision_number": revision.revision_number,
        # Clear feedback after it has been consumed
        "atma_reviewer_feedback": None,
    }


# ── Node 3: Script validator ─────────────────────────────────────────────────


def script_validator_node(state: VideoState) -> dict:
    """Re-validate the current script and surface flags to the human reviewer.

    The validator never silently discards the script. Issues that cannot be
    safely auto-fixed are passed forward with the script to human review.
    """
    project_id = state["project_id"]
    script_text: str = state.get("script_md") or state.get("atma_current_refined") or ""
    identity_dict = state.get("script_identity") or {}
    identity = ScriptIdentity.from_dict(identity_dict)

    base_script = ""
    script_file = Path(WORKSPACE_DIR) / project_id / "script" / "script.md"
    if script_file.exists():
        base_script = script_file.read_text(encoding="utf-8")

    validator = ScriptValidator()
    validation = validator.validate(script_text, identity, base_script)

    script_dir = Path(WORKSPACE_DIR) / project_id / "script"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "atma-validation.json").write_text(
        json.dumps(validation.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if validation.flags:
        console.print(
            f"\n[yellow]⚠  Script Validator:[/yellow] "
            f"{len(validation.flags)} flag(s) — status: {validation.status}"
        )
        for flag in validation.flags:
            icon = "✗" if flag.severity == "error" else "⚠"
            console.print(f"  [{icon}] [{flag.flag_type.value}] {flag.message}")
    else:
        console.print(
            f"\n[green]✓  Script Validator: PASS[/green] — "
            f"{validation.spoken_word_count} spoken words"
        )

    return {"atma_validation": validation.to_dict()}


# ── Node 4: Human review with Accept/Reject loop ─────────────────────────────


def _render_validation_table(validation_dict: dict) -> None:
    """Render validation flags as a Rich table."""
    flags = validation_dict.get("flags", [])
    if not flags:
        console.print("[green]✓ Validation: PASS[/green]")
        return

    table = Table(title="Validation Flags", show_lines=True)
    table.add_column("Type", style="yellow", width=20)
    table.add_column("Location", width=14)
    table.add_column("Issue", max_width=60)
    table.add_column("Sev", width=8)

    for f in flags:
        sev_color = "red" if f.get("severity") == "error" else "yellow"
        table.add_row(
            f.get("type", ""),
            f.get("location", ""),
            f.get("message", ""),
            f"[{sev_color}]{f.get('severity', '')}[/{sev_color}]",
        )
    console.print(table)


def _collect_feedback() -> str:
    """Prompt the human reviewer for structured rejection feedback."""
    console.print(
        "\n[bold yellow]Rejection Feedback[/bold yellow]\n"
        "Provide specific feedback for the targeted refinement.\n"
        "Example: 'Beat 1 hook is weak. Beat 5 needs a third principle. "
        "The ending is generic.'\n"
        "Enter feedback (press Enter twice when done):"
    )
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line and lines and not lines[-1]:
            break
        lines.append(line)
    return "\n".join(lines).strip()


def human_review_atma_script_node(state: VideoState) -> dict:
    """Human review gate for the Atma Theory refined script.

    In auto_mode: accepts immediately (no terminal prompt).

    Interactive:
      [a] Accept → script becomes canonical, pipeline continues.
      [r] Reject → human provides feedback → targeted refinement runs inline.
                   The refined script is presented again for review.
      [q] Quit   → abort pipeline.

    The reject → refine loop runs inside this node (not as a graph cycle)
    to keep the interactive experience linear and avoid LangGraph state
    management complexity for the rejection flow.

    Feedback and revision decisions are stored in RevisionStore (revisions.json)
    for full lineage tracking regardless of which branch is taken.
    """
    auto_mode = state.get("auto_mode", False)
    project_id = state["project_id"]
    settings = Settings()

    script_text: str = state.get("script_md") or state.get("atma_current_refined") or ""
    identity_dict = state.get("script_identity") or {}
    identity = ScriptIdentity.from_dict(identity_dict)
    validation_dict = state.get("atma_validation") or {}
    beats = state.get("beats") or []
    target_minutes = int(state.get("target_minutes", 5))
    current_revision_id: str | None = state.get("atma_current_revision_id")

    base_script = ""
    script_file_path = Path(WORKSPACE_DIR) / project_id / "script" / "script.md"
    if script_file_path.exists():
        base_script = script_file_path.read_text(encoding="utf-8")

    store = RevisionStore(project_id)
    pipeline = AtmaRefinerPipeline(settings)

    iteration = 0
    current_script: str = script_text
    current_rev_id = current_revision_id

    while True:
        iteration += 1

        validation_status = validation_dict.get("status", "UNKNOWN")
        if auto_mode and validation_status == "PASS":
            # Only auto-accept when the validator is clean — REVIEW_REQUIRED
            # always drops into interactive review regardless of auto_mode.
            if current_rev_id:
                store.record_acceptance(current_rev_id)
            _write_canonical(project_id, current_script)
            logger.info(
                "HumanReviewAtmaScript: auto-accepted revision {} (iteration {})",
                current_rev_id,
                iteration,
            )
            return {"script_md": current_script}

        if auto_mode and validation_status != "PASS":
            console.print(
                "\n[bold yellow]⚠  Auto-mode paused:[/bold yellow] "
                f"Script validation status is [red]{validation_status}[/red]. "
                "Human review required before the pipeline can continue.\n"
            )

        # ── Show the script ──────────────────────────────────────────────────
        word_count = len(current_script.split())
        revision_number = store.get_latest_revision()
        rev_label = (
            f"Revision #{revision_number.revision_number}" if revision_number else ""
        )

        console.print(
            Panel(
                f"[bold]Atma Theory Script Review[/bold] {rev_label}\n"
                f"Words: {word_count} (~{word_count / 130:.1f} min)\n"
                f"Validation: {validation_dict.get('status', 'UNKNOWN')}\n"
                f"Beat coverage (green=covered, red=missing): "
                + ", ".join(
                    f"[green]{b}[/green]" if v else f"[red]{b}[/red]"
                    for b, v in (validation_dict.get("beat_coverage") or {}).items()
                ),
                title="Human Review Gate — Atma Theory Script",
                border_style="yellow",
            )
        )

        _render_validation_table(validation_dict)
        console.print()
        console.print(
            Markdown(
                current_script[:3500]
                + (
                    "\n\n*[...truncated for review]*"
                    if len(current_script) > 3500
                    else ""
                )
            )
        )
        console.print()

        action = (
            typer.prompt(
                "Action? [a]ccept / [r]eject (with feedback) / [q]uit",
                default="a",
            )
            .strip()
            .lower()
        )

        if action.startswith("q"):
            raise typer.Abort()

        if action.startswith("a"):
            # Accept: record canonical
            if current_rev_id:
                store.record_acceptance(current_rev_id)
            _write_canonical(project_id, current_script)
            console.print("[green]✓ Script accepted as canonical.[/green]")
            return {"script_md": current_script}

        # Reject: collect feedback and run targeted refinement
        feedback = _collect_feedback()
        if not feedback:
            console.print(
                "[yellow]No feedback provided — please enter specific feedback "
                "so the refiner can make targeted improvements.[/yellow]"
            )
            continue

        if current_rev_id:
            store.record_rejection(current_rev_id, feedback)

        console.print("\n[bold magenta]Running targeted refinement...[/bold magenta]")

        refined, validation = pipeline.run(
            project_id,
            base_script=base_script,
            identity=identity,
            beats=beats,
            reviewer_feedback=feedback,
            current_refined=current_script,
            target_minutes=target_minutes,
            force=True,
        )

        # Save the new revision
        parent_id = current_rev_id
        new_revision = store.save_revision(refined, parent_id=parent_id)
        current_rev_id = new_revision.revision_id
        current_script = refined
        validation_dict = validation.to_dict()

        console.print(
            f"[dim]New revision #{new_revision.revision_number} ready for review.[/dim]"
        )


def _write_canonical(project_id: str, script_text: str) -> None:
    """Write the accepted canonical script to script.md for downstream use."""
    script_dir = Path(WORKSPACE_DIR) / project_id / "script"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "script.md").write_text(script_text, encoding="utf-8")
    (script_dir / "atma-canonical.md").write_text(script_text, encoding="utf-8")
    logger.info("Canonical script written to script.md and atma-canonical.md")
