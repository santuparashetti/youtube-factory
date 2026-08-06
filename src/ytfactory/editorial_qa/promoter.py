"""Pattern Promoter — Layer 3 of the Editorial QA Stage. See
EDITORIAL_QA_STAGE_SPEC.md.

Trigger: a check FLAGGED in >= N of the last M ledger entries (defaults
4/5) — a recurring weakness, not a one-off. A single or occasional flag
NEVER promotes. On trigger, ONE small LLM call drafts a proposed
generation-prompt addition, surfaced to a HUMAN for approve/edit/dismiss.

Never auto-applies. Never edits a prompt or framework file itself — approval
just clears the pending state; the human (or an agent they direct) adds the
text. Dismissal starts a cooldown so the same pattern doesn't re-nag every
run unless its flag-rate has risen since the dismissal.
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.agents.prompts.editorial_qa import build_promotion_proposal_prompt
from ytfactory.config.settings import Settings
from ytfactory.editorial_qa.ledger import QALedger
from ytfactory.shared.constants import WORKSPACE_DIR
from video_core.providers.llm.factory import get_llm_for_role

_DEFAULT_STATE_PATH = Path(WORKSPACE_DIR).parent / "editorial_qa" / "promotions.json"
_DEFAULT_QA_ROOT = Path(WORKSPACE_DIR)


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


def _gather_evidence_examples(
    script_ids: list[str], check_name: str, qa_root: Path, limit: int = 3
) -> list[str]:
    """Pull real quoted evidence (the check's "note") from recent flagged
    scripts' full reports — the ledger itself only stores flagged/invalid
    booleans, not quotes, to stay cheap."""
    examples: list[str] = []
    for script_id in reversed(script_ids):  # most recent first
        report_path = qa_root / script_id / "qa" / "editorial-qa-report.json"
        if not report_path.exists():
            continue
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        check = (report.get("checks") or {}).get(check_name) or {}
        note = check.get("note")
        if check.get("flagged") and note:
            examples.append(f"{script_id}: {note}")
        if len(examples) >= limit:
            break
    return examples


class PatternPromoter:
    def __init__(self, settings: Settings, state_path: Path | None = None, qa_root: Path | None = None) -> None:
        self._settings = settings
        self._llm = get_llm_for_role(settings, "validator")
        self._state_path = state_path or _DEFAULT_STATE_PATH
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._qa_root = qa_root or _DEFAULT_QA_ROOT

    def _load_state(self) -> dict:
        if not self._state_path.exists():
            return {"run_count": 0, "dismissed": {}, "pending": {}}
        try:
            state = json.loads(self._state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
        state.setdefault("run_count", 0)
        state.setdefault("dismissed", {})
        state.setdefault("pending", {})
        return state

    def _save_state(self, state: dict) -> None:
        self._state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def evaluate(self, ledger: QALedger) -> list[dict]:
        """Called once per Editorial QA run. Returns newly generated
        proposals this run — empty on almost every call; proposals are rare
        by design."""
        state = self._load_state()
        state["run_count"] += 1
        run_count = state["run_count"]

        n = getattr(self._settings, "qa_promote_n", 4)
        m = getattr(self._settings, "qa_promote_m", 5)
        cooldown = getattr(self._settings, "qa_promote_cooldown_runs", 5)
        callback_required = getattr(self._settings, "qa_callback_required", False)

        new_proposals: list[dict] = []
        for check_name in ledger.check_names():
            if check_name == "callback_to_opening" and not callback_required:
                continue  # report-only until opted in as a house-style requirement
            if check_name in state["pending"]:
                continue  # already awaiting a human decision

            rollup = ledger.rollup(check_name, m)
            if rollup["flag_count"] < n:
                continue  # not a recurring pattern — a single flag never promotes

            dismissal = state["dismissed"].get(check_name)
            if dismissal:
                runs_since = run_count - dismissal["dismissed_at_run"]
                rate_risen = rollup["flag_rate"] > dismissal["dismissed_flag_rate"]
                if runs_since < cooldown and not rate_risen:
                    continue  # cooldown active, flag-rate hasn't risen

            examples = _gather_evidence_examples(rollup["scripts"], check_name, self._qa_root)
            prompt = build_promotion_proposal_prompt(
                check_name, rollup["flag_count"], rollup["total"], rollup["flag_rate"], examples
            )
            response = self._llm.generate(prompt, temperature=0.3)
            parsed = _parse_json_response(response.text)

            proposal = {
                "check_name": check_name,
                "flag_count": rollup["flag_count"],
                "total": rollup["total"],
                "flag_rate": rollup["flag_rate"],
                "summary": parsed.get("summary", ""),
                "proposed_prompt_addition": parsed.get("proposed_prompt_addition", ""),
                "status": "pending",
            }
            state["pending"][check_name] = proposal
            new_proposals.append(proposal)

        self._save_state(state)
        return new_proposals

    def list_pending(self) -> dict:
        return self._load_state()["pending"]

    def approve(self, check_name: str) -> dict | None:
        """Human approved. Clears pending — does NOT edit any prompt file;
        the human (or a coding agent they direct) still applies the text."""
        state = self._load_state()
        proposal = state["pending"].pop(check_name, None)
        if proposal is None:
            return None
        proposal["status"] = "approved"
        state.setdefault("approved", {})[check_name] = proposal
        self._save_state(state)
        return proposal

    def dismiss(self, check_name: str) -> dict | None:
        """Human dismissed. Starts a cooldown so this check doesn't re-nag
        every run unless its flag-rate rises above the rate at dismissal."""
        state = self._load_state()
        proposal = state["pending"].pop(check_name, None)
        if proposal is None:
            return None
        state["dismissed"][check_name] = {
            "dismissed_at_run": state["run_count"],
            "dismissed_flag_rate": proposal["flag_rate"],
        }
        self._save_state(state)
        return proposal
