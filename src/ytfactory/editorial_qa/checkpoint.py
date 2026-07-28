"""Human review checkpoint hash-guard.

Records script.md's content hash at review time so a later resume/re-run can
detect whether the human hand-edited the script during the pause. Pure code,
no LLM — same spirit as the QA ledger.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ytfactory.shared.constants import WORKSPACE_DIR


def _checkpoint_path(project_id: str) -> Path:
    return Path(WORKSPACE_DIR) / project_id / "qa" / "review-checkpoint.json"


def script_hash(script_text: str) -> str:
    return hashlib.sha256(script_text.encode("utf-8")).hexdigest()


def read_recorded_hash(project_id: str) -> str | None:
    path = _checkpoint_path(project_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data.get("script_hash")


def record_hash(project_id: str, script_text: str) -> None:
    path = _checkpoint_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"script_hash": script_hash(script_text)}, indent=2), encoding="utf-8"
    )


def clear(project_id: str) -> None:
    path = _checkpoint_path(project_id)
    if path.exists():
        path.unlink()
