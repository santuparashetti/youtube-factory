"""QA Ledger — Layer 2 of the Editorial QA Stage. See EDITORIAL_QA_STAGE_SPEC.md.

Cheap, append-only, deterministic. No LLM, no interpretation — just
accumulation and a per-check rollup. This is the ONLY component in the
Editorial QA stage that persists across scripts/projects (every other module
here is scoped to one project's workspace dir).

Check-name-agnostic by design: it stores and rolls up whatever check keys
appear in each report's "checks" dict, so it never needs updating when a
check is added or renamed upstream.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from ytfactory.shared.constants import WORKSPACE_DIR

_DEFAULT_LEDGER_PATH = Path(WORKSPACE_DIR).parent / "editorial_qa" / "ledger.jsonl"

# Duplicated from editorial_qa.pipeline (not imported, to avoid a cycle —
# pipeline.py imports this module). editorial_score is information only,
# never a gate, but out-of-range data must not be persisted regardless.
_SCORE_MIN = 0.0
_SCORE_MAX = 10.0


def _sanitize_editorial_score(raw_score) -> float | None:
    if raw_score is None:
        return None
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return None
    if not (_SCORE_MIN <= score <= _SCORE_MAX):
        logger.warning(
            "QALedger: refusing to persist editorial_score {} outside valid "
            "{}-{} range",
            score, _SCORE_MIN, _SCORE_MAX,
        )
        return None
    return score


class QALedger:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_LEDGER_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, report: dict) -> None:
        """Append a slim record: script_id, timestamp, editorial_score, and
        per-check {flagged, invalid}. The full quoted-evidence report stays
        in that project's own qa/editorial-qa-report.json — the ledger
        itself never grows text-heavy, however many scripts accumulate."""
        editorial_score = _sanitize_editorial_score(report.get("editorial_score"))
        assert editorial_score is None or _SCORE_MIN <= editorial_score <= _SCORE_MAX, (
            f"editorial_score {editorial_score} outside valid {_SCORE_MIN}-{_SCORE_MAX} "
            "range — must not reach the ledger"
        )
        entry = {
            "script_id": report.get("script_id"),
            "timestamp": report.get("timestamp"),
            "editorial_score": editorial_score,
            "checks": {
                name: {
                    "flagged": bool(check.get("flagged", False)),
                    "invalid": bool(check.get("invalid", False)),
                }
                for name, check in (report.get("checks") or {}).items()
            },
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        entries = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def check_names(self) -> list[str]:
        """All check names ever seen in the ledger, first-seen order."""
        seen: list[str] = []
        for entry in self.read_all():
            for name in entry.get("checks", {}):
                if name not in seen:
                    seen.append(name)
        return seen

    def rollup(self, check_name: str, m: int) -> dict:
        """Last M VALID entries for this check, most recent first internally.

        An invalid check ("not evaluated") is excluded from both the
        numerator and the denominator — same rule as everywhere else in this
        stage: no evidence means it doesn't count.

        Returns {"total": int, "flag_count": int, "flag_rate": float,
        "scripts": [script_id, ...]} (scripts oldest-to-newest of the window).
        """
        valid_entries = []
        for entry in reversed(self.read_all()):
            check = entry.get("checks", {}).get(check_name)
            if check is None or check.get("invalid"):
                continue
            valid_entries.append(entry)
            if len(valid_entries) >= m:
                break
        valid_entries.reverse()  # oldest-to-newest within the window

        total = len(valid_entries)
        flag_count = sum(1 for e in valid_entries if e["checks"][check_name]["flagged"])
        return {
            "total": total,
            "flag_count": flag_count,
            "flag_rate": (flag_count / total) if total else 0.0,
            "scripts": [e["script_id"] for e in valid_entries],
        }
