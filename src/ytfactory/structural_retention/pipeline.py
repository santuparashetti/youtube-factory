"""StructuralRetentionPipeline — reshape an already-faithful, already-scoped
script for viewer retention. See STRUCTURAL_RETENTION_PASS_SPEC.md.

Runs AFTER the existing enhancer passes (Pass 1, and Pass 2 if enabled),
BEFORE scene_planner. It is a distinct pass, not a Pass 1 mode: no coverage
floor, no reorder ban — that is the entire point (Pass 1 architecturally
cannot do this work; see spec "Why this pass exists").

Governing rule: reshape structure freely, never change meaning. Reordering
and cutting are NOT meaning changes.

The faithfulness check is MEANING-ONLY and NON-BLOCKING: violations are
flagged to a report artifact and logs, never auto-reverted. An automatic
revert cannot reliably distinguish intended restructuring from meaning
drift, and a silent revert would sabotage the pass's purpose.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.prompts.structural_retention import (
    build_faithfulness_check_prompt,
    build_structural_pass_prompt,
)
from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shared.pipeline_status import get_writer
from ytfactory.shared.scripture import extract_scripture_spans, restore_scripture_spans
from video_core.providers.llm.factory import get_llm_provider

console = Console()

_MOVES_BLOCK_RE = re.compile(
    r"\s*---STRUCTURAL MOVES---\n(.*?)\n---END STRUCTURAL MOVES---",
    re.DOTALL,
)
_MOVE_KEYS = (
    "open_loop",
    "break_parallel_examples",
    "shadow_beat",
    "depth_over_coverage",
    "climax_breath",
)

_IDENTITY_WHITESPACE_RE = re.compile(r"\s+")
_IDENTITY_PUNCT_RE = re.compile(r"[’‘“”\"'.,;:!?…—–-]")


def _normalize_for_identity(text: str) -> str:
    """Normalize text for an identical-vs-changed comparison (case/whitespace/
    punctuation insensitive). Used to drop faithfulness flags raised against
    text that didn't actually change — a meaning-change flag on unchanged
    text is a false positive, not a real finding."""
    text = _IDENTITY_PUNCT_RE.sub("", text.lower())
    return _IDENTITY_WHITESPACE_RE.sub(" ", text).strip()


def _drop_identical_text_flags(flags: list[dict]) -> list[dict]:
    """Deterministic guard: an item whose input_meaning and output_meaning
    normalize to the same text cannot be a meaning-change flag (see spec —
    unchanged text cannot have changed meaning). Prompt-level instruction is
    the first line of defense; this is the code-level backstop."""
    kept = []
    for flag in flags:
        before = _normalize_for_identity(str(flag.get("input_meaning", "")))
        after = _normalize_for_identity(str(flag.get("output_meaning", "")))
        if before == after:
            logger.info(
                "Structural Retention Pass: dropped faithfulness flag on unchanged text ({})",
                flag.get("item", "?"),
            )
            continue
        kept.append(flag)
    return kept


def _parse_json_response(text: str) -> dict:
    """Extract a JSON object from an LLM response, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        return {}


def _parse_structural_moves(text: str) -> tuple[str, dict]:
    """Split the restructure-pass output into (narration, self_report_dict).

    self_report_dict has keys: moves (dict of the 5 move names -> {status, note}),
    stories_cut (list[str]), stories_reordered (list[str]). Falls back to empty
    values on missing/malformed block — never raises, this is diagnostic metadata.
    """
    m = _MOVES_BLOCK_RE.search(text)
    if not m:
        return text.strip(), {"moves": {}, "stories_cut": [], "stories_reordered": []}

    narration = text[: m.start()].rstrip()
    data = _parse_json_response(m.group(1))

    moves = {key: data.get(key, {}) for key in _MOVE_KEYS} if data else {}
    return narration, {
        "moves": moves,
        "stories_cut": data.get("stories_cut", []) if data else [],
        "stories_reordered": data.get("stories_reordered", []) if data else [],
    }


class StructuralRetentionPipeline:
    """Reshape a clean, faithful script's structure for viewer retention.

    Distinct pass, its own prompt, its own permissions. NOT a Pass 1 mode.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = get_llm_provider(settings)

    def run(self, project_id: str, script_text: str | None = None) -> str:
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_dir.mkdir(parents=True, exist_ok=True)

        if script_text is None:
            script_file = script_dir / "script.md"
            if not script_file.exists():
                raise FileNotFoundError(
                    f"StructuralRetentionPipeline: no script found at {script_file}"
                )
            script_text = script_file.read_text(encoding="utf-8")

        if not getattr(self._settings, "structural_pass_enabled", True):
            logger.info(
                "Structural Retention Pass disabled (STRUCTURAL_PASS_ENABLED=false) — skipping."
            )
            console.print("  [dim]Structural Retention Pass: disabled — skipping[/dim]")
            return script_text

        _w = get_writer()
        if _w:
            _w.stage_start("structural_retention_pass")

        console.print(
            "\n[bold magenta]🧩 Structural Retention Pass[/bold magenta] — "
            "reshaping structure for retention..."
        )

        input_words = len(script_text.split())

        # ── Restructure (single LLM call) ───────────────────────────────────
        placeholder_text, placeholders = extract_scripture_spans(script_text)
        prompt = build_structural_pass_prompt(placeholder_text, placeholders)
        response = self._llm.generate(prompt, temperature=0.5)
        raw_output = response.text.strip()

        restructured_ph_text, self_report = _parse_structural_moves(raw_output)
        restructured_text = restore_scripture_spans(restructured_ph_text, placeholders)

        output_words = len(restructured_text.split())
        console.print(
            f"  [dim]Input:[/dim] {input_words} words → [dim]Output:[/dim] {output_words} words"
        )

        for move_name in _MOVE_KEYS:
            detail = self_report["moves"].get(move_name, {}) or {}
            status = detail.get("status", "?")
            note = detail.get("note", "")
            color = "green" if status == "fired" else "dim"
            icon = "✓" if status == "fired" else "·"
            console.print(f"    [{color}]{icon} {move_name}: {status}[/{color}] — {note}")

        # ── Faithfulness check — meaning-only, NON-BLOCKING (never auto-revert) ──
        faithfulness_flags: list[dict] = []
        structural_score: float | None = None
        faithfulness_enabled = getattr(self._settings, "structural_pass_faithfulness_check", True)

        if faithfulness_enabled:
            console.print("  [cyan]Faithfulness check:[/cyan] meaning-only, non-blocking...")
            check_prompt = build_faithfulness_check_prompt(script_text, restructured_text)
            check_response = self._llm.generate(check_prompt, temperature=0.2)
            check_result = _parse_json_response(check_response.text)
            faithfulness_flags = _drop_identical_text_flags(
                check_result.get("faithfulness_flags") or []
            )
            raw_score = check_result.get("structural_score")
            if raw_score is not None:
                try:
                    structural_score = float(raw_score)
                except (TypeError, ValueError):
                    structural_score = None

            if faithfulness_flags:
                logger.warning(
                    "Structural Retention Pass: {} faithfulness flag(s) — "
                    "non-blocking, human review recommended",
                    len(faithfulness_flags),
                )
                console.print(
                    f"  [yellow]⚠ {len(faithfulness_flags)} faithfulness flag(s) — "
                    f"non-blocking, see structural-retention-report.json[/yellow]"
                )
                for flag in faithfulness_flags:
                    console.print(
                        f"    [dim yellow]{flag.get('item', '?')}: "
                        f"{flag.get('input_meaning', '')!r} -> "
                        f"{flag.get('output_meaning', '')!r} "
                        f"({flag.get('severity', '?')})[/dim yellow]"
                    )
            else:
                console.print("  [green]✓ Faithfulness check clean — no meaning-change flags[/green]")
        else:
            console.print(
                "  [dim]Faithfulness check: disabled "
                "(STRUCTURAL_PASS_FAITHFULNESS_CHECK=false)[/dim]"
            )

        # No auto-revert on flags — spec-mandated. Flag + report only; a human
        # judges. See module docstring for rationale.

        (script_dir / "pre-structural-retention.md").write_text(script_text, encoding="utf-8")
        (script_dir / "script.md").write_text(restructured_text, encoding="utf-8")

        report = {
            "enabled": True,
            "faithfulness_check_enabled": faithfulness_enabled,
            "input_words": input_words,
            "output_words": output_words,
            "moves_applied": [
                {
                    "move": name,
                    "status": (self_report["moves"].get(name) or {}).get("status"),
                    "note": (self_report["moves"].get(name) or {}).get("note"),
                }
                for name in _MOVE_KEYS
            ],
            "stories_cut": self_report["stories_cut"],
            "stories_reordered": self_report["stories_reordered"],
            "faithfulness_flags": faithfulness_flags,
            "structural_score": structural_score,
        }
        (script_dir / "structural-retention-report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )

        if _w:
            _w.stage_complete()

        console.print(
            Panel(
                f"Structural Retention Pass complete — {input_words} → {output_words} words\n"
                f"[dim]Output -> script.md | Pre-pass snapshot -> pre-structural-retention.md | "
                f"Report -> structural-retention-report.json[/dim]",
                title="Structural Retention Pass",
                border_style="magenta",
            )
        )

        return restructured_text
