"""EditorialQAPipeline — Layer 1 (reviewer), orchestrating Layer 2 (ledger)
and Layer 3 (promoter). See EDITORIAL_QA_STAGE_SPEC.md.

Runs AFTER the Structural Retention Pass. FLAG, NEVER GATE: this stage never
blocks, rejects, reverts, or rewrites a script — editorial_score is
information only. A check's verdict with no cited evidence is INVALID and
treated as "not evaluated" (never counted as a flag or a pass) — same lesson
as the Structural Retention Pass's naming-requirement fix.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.prompts.editorial_qa import build_editorial_qa_prompt
from ytfactory.config.settings import Settings
from ytfactory.editorial_qa.ledger import QALedger
from ytfactory.editorial_qa.promoter import PatternPromoter
from ytfactory.shared.constants import WORKSPACE_DIR
from video_core.providers.llm.factory import get_llm_for_role

console = Console()

CHECK_NAMES = (
    "ending_vs_opening",
    "every_story_earns_place",
    "unnecessary_explanation",
    "callback_to_opening",
    "sounds_translated",
    "open_loop_payoff",
)

EDITORIAL_SCORE_MIN = 0.0
EDITORIAL_SCORE_MAX = 10.0
EDITORIAL_SCORE_START = 10.0

# Flat per-check penalties — flag-count arithmetic, not a per-check-type
# weighting model. Invalid weighs more than flagged: a check with no cited
# evidence tells us less than a check that positively found and named a
# problem, but "we couldn't verify this at all" is still worse than clean.
FLAGGED_PENALTY = 1.5
INVALID_PENALTY = 2.0


def _derive_editorial_score(checks: dict) -> float:
    """Deterministic, code-derived score — replaces asking the model for one
    (it reliably inverted the sign; see EDITORIAL_QA_STAGE_SPEC.md history).
    Always present, always in [0, 10], never model-dependent.

    Start at 10.0. Subtract FLAGGED_PENALTY per flagged check, INVALID_PENALTY
    per invalid (no-evidence) check — mutually exclusive per check by
    construction (see run() below). Clamp to [0, 10].
    """
    score = EDITORIAL_SCORE_START
    for check in checks.values():
        if check.get("invalid"):
            score -= INVALID_PENALTY
        elif check.get("flagged"):
            score -= FLAGGED_PENALTY
    return max(EDITORIAL_SCORE_MIN, min(EDITORIAL_SCORE_MAX, score))


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        return {}


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _validate_evidence(check_name: str, check: dict) -> bool:
    """True if the verdict is backed by the evidence this check requires.
    Missing evidence => INVALID => "not evaluated", never a flag."""
    if not isinstance(check, dict):
        return False
    note_ok = _nonempty(check.get("note"))

    if check_name == "ending_vs_opening":
        return _nonempty(check.get("opening_beat")) and _nonempty(check.get("closing_beat"))
    if check_name == "every_story_earns_place":
        stories = check.get("stories")
        return (
            isinstance(stories, list)
            and len(stories) > 0
            and all(
                isinstance(s, dict) and _nonempty(s.get("name")) and _nonempty(s.get("function"))
                for s in stories
            )
        )
    if check_name == "unnecessary_explanation":
        violations = check.get("violations") or []
        verdict = str(check.get("verdict", "")).strip().lower()
        if verdict not in ("clean", "") and not violations:
            return False  # claims violations but cites none
        return note_ok or bool(violations)
    if check_name == "callback_to_opening":
        return _nonempty(check.get("opening_image")) and _nonempty(check.get("ending_quote"))
    if check_name == "sounds_translated":
        flagged = check.get("flagged") or []
        verdict = str(check.get("verdict", "")).strip().lower()
        if verdict not in ("clean", "") and not flagged:
            return False
        return note_ok or bool(flagged)
    if check_name == "open_loop_payoff":
        verdict = str(check.get("verdict", "")).strip().lower()
        if verdict == "never resolved":
            # No resolution exists to quote by definition — question alone is the evidence.
            return _nonempty(check.get("question"))
        return _nonempty(check.get("question")) and _nonempty(check.get("resolution"))
    return False


def _is_flagged(check_name: str, check: dict) -> bool:
    """Per-check flag logic per spec. Report-only — computed truthfully
    regardless of any config; qa_callback_required only affects whether the
    Pattern Promoter considers callback_to_opening, not whether it's flagged."""
    verdict = str(check.get("verdict", "")).strip().lower()
    if check_name == "ending_vs_opening":
        return verdict in ("equal", "weaker")
    if check_name == "every_story_earns_place":
        stories = check.get("stories") or []
        return any(s.get("duplicate_of") for s in stories if isinstance(s, dict))
    if check_name == "unnecessary_explanation":
        return bool(check.get("violations"))
    if check_name == "callback_to_opening":
        return verdict != "yes"
    if check_name == "sounds_translated":
        return bool(check.get("flagged"))
    if check_name == "open_loop_payoff":
        return verdict in ("paid off early", "never resolved")
    return False


def _locate_quote(script_text: str, quote: str) -> dict:
    """Deterministic, no LLM. Locate a cited quote in the script so a future
    scoped auto-fixer (Phase 2, not built here) has a targetable span —
    character offset + paragraph index — not just quoted text."""
    quote = quote.strip()
    if not quote:
        return {"paragraph_index": None, "char_start": None, "char_end": None}
    idx = script_text.find(quote)
    if idx == -1:
        return {"paragraph_index": None, "char_start": None, "char_end": None}
    return {
        "paragraph_index": script_text[:idx].count("\n\n"),
        "char_start": idx,
        "char_end": idx + len(quote),
    }


def _quotes_for_check(check_name: str, check: dict) -> list[str]:
    """The evidence text(s) a check cites, per its own shape."""
    if check_name == "ending_vs_opening":
        return [check.get("opening_beat", ""), check.get("closing_beat", "")]
    if check_name == "every_story_earns_place":
        return [s.get("name", "") for s in (check.get("stories") or []) if isinstance(s, dict)]
    if check_name == "unnecessary_explanation":
        return list(check.get("violations") or [])
    if check_name == "callback_to_opening":
        return [check.get("opening_image", ""), check.get("ending_quote", "")]
    if check_name == "sounds_translated":
        return list(check.get("flagged") or [])
    if check_name == "open_loop_payoff":
        return [check.get("question", ""), check.get("resolution", "")]
    return []


def _build_evidence_spans(check_name: str, check: dict, script_text: str) -> list[dict]:
    """Phase 1 hook for the (not-yet-built) Phase 2 scoped auto-fixer: each
    flag's cited evidence exposed as a targetable span (quote + location),
    not just quoted text. See EDITORIAL_QA_STAGE_SPEC.md 'Build note for
    Phase 1'."""
    return [
        {"quote": q, "location": _locate_quote(script_text, q)}
        for q in _quotes_for_check(check_name, check)
        if q
    ]


class EditorialQAPipeline:
    """Layer 1: per-script reviewer. Also drives Layer 2 (ledger append) and
    Layer 3 (promoter evaluation) after building the report."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = get_llm_for_role(settings, "validator")

    def run(self, project_id: str, script_text: str | None = None) -> dict:
        if not getattr(self._settings, "editorial_qa_enabled", True):
            logger.info("Editorial QA disabled (EDITORIAL_QA_ENABLED=false) — skipping.")
            console.print("  [dim]Editorial QA: disabled — skipping[/dim]")
            return {}

        if script_text is None:
            script_file = Path(WORKSPACE_DIR) / project_id / "script" / "script.md"
            if not script_file.exists():
                raise FileNotFoundError(f"EditorialQAPipeline: no script found at {script_file}")
            script_text = script_file.read_text(encoding="utf-8")

        console.print("\n[bold magenta]🔍 Editorial QA[/bold magenta] — reviewing finished script...")

        response = self._llm.generate(build_editorial_qa_prompt(script_text), temperature=0.2)
        raw = _parse_json_response(response.text)
        checks_raw = raw.get("checks") or {}

        checks: dict = {}
        invalid_checks: list[str] = []
        for name in CHECK_NAMES:
            check = checks_raw.get(name) or {}
            valid = _validate_evidence(name, check)
            check_out = dict(check)
            check_out["flagged"] = _is_flagged(name, check) if valid else False
            check_out["invalid"] = not valid
            check_out["evidence_spans"] = _build_evidence_spans(name, check, script_text)
            checks[name] = check_out
            if not valid:
                invalid_checks.append(name)

        # Code-derived, not model-emitted — the model reliably inverted the
        # sign on this field. Cheap insurance: should never fire now that the
        # value comes from our own arithmetic, but free to keep.
        editorial_score = _derive_editorial_score(checks)
        assert EDITORIAL_SCORE_MIN <= editorial_score <= EDITORIAL_SCORE_MAX, (
            f"editorial_score {editorial_score} outside valid "
            f"{EDITORIAL_SCORE_MIN}-{EDITORIAL_SCORE_MAX} range — must not reach the report"
        )

        report = {
            "script_id": project_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "editorial_score": editorial_score,
            "invalid_checks": invalid_checks,
        }

        for name in CHECK_NAMES:
            c = checks[name]
            if c["invalid"]:
                label, color = "INVALID (no evidence)", "red"
            elif c["flagged"]:
                label, color = "FLAGGED", "yellow"
            else:
                label, color = "clean", "green"
            console.print(f"    [{color}]{name}: {label}[/{color}]")

        qa_dir = Path(WORKSPACE_DIR) / project_id / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        (qa_dir / "editorial-qa-report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )

        # ── Layer 2: append-only ledger (deterministic, no LLM) ─────────────
        ledger = QALedger()
        ledger.append(report)

        # ── Layer 3: pattern promoter (LLM only if a pattern actually triggers) ──
        proposals = PatternPromoter(self._settings).evaluate(ledger)
        for p in proposals:
            console.print(
                Panel(
                    f"[bold]{p['check_name']}[/bold] flagged in {p['flag_count']} of "
                    f"{p['total']} recent scripts (rate {p['flag_rate']:.0%}).\n\n"
                    f"{p['summary']}\n\n"
                    f"[dim]Proposed addition:[/dim]\n{p['proposed_prompt_addition']}\n\n"
                    "[yellow]Human decision required[/yellow] — see "
                    "`ytfactory qa-promotions list` (approve/dismiss). Never auto-applied.",
                    title="Pattern Promoter — New Proposal",
                    border_style="yellow",
                )
            )

        flagged_count = sum(1 for c in checks.values() if c["flagged"])
        console.print(
            Panel(
                f"Editorial QA complete — {flagged_count} flagged, "
                f"{len(invalid_checks)} invalid, "
                f"score {editorial_score:.1f}\n"
                "[dim]Report -> qa/editorial-qa-report.json (flags only — nothing blocked, "
                "nothing rewritten)[/dim]",
                title="Editorial QA",
                border_style="magenta",
            )
        )

        return report
