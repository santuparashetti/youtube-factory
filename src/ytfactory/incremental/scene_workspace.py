"""Scene Workspace — per-scene approval state management.

Stores scene states in workspace/jobs/<project-id>/scenes/scene-status.json.

States (spec section 10):
  Draft          — initial state after generation
  Needs Review   — generated, ready for creator review
  Needs Revision — failed quality review or rejected by creator
  Approved       — creator-approved, safe to include in final video
  Locked         — highest state; never auto-regenerated
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import SceneState

STATUS_FILENAME = "scene-status.json"


class SceneWorkspace:
    """Manage per-scene approval states with persistent JSON storage."""

    def __init__(self, project_dir: Path) -> None:
        self._path = project_dir / "scenes" / STATUS_FILENAME
        self._states: dict[int, dict] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._states = {int(k): v for k, v in raw.items()}
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({str(k): v for k, v in sorted(self._states.items())}, indent=2),
            encoding="utf-8",
        )

    # ── State access ──────────────────────────────────────────────────────────

    def get_state(self, index: int) -> SceneState:
        entry = self._states.get(index, {})
        try:
            return SceneState(entry.get("state", SceneState.DRAFT))
        except ValueError:
            return SceneState.DRAFT

    def set_state(self, index: int, state: SceneState, notes: str = "") -> None:
        self._states[index] = {
            "state": state.value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        }
        self.save()

    def get_notes(self, index: int) -> str:
        return self._states.get(index, {}).get("notes", "")

    def is_locked(self, index: int) -> bool:
        return self.get_state(index) == SceneState.LOCKED

    def all_states(self) -> dict[int, SceneState]:
        return {idx: self.get_state(idx) for idx in self._states}

    # ── Bulk helpers ──────────────────────────────────────────────────────────

    def initialize_scenes(self, scene_indices: list[int]) -> None:
        """Ensure every scene index has an entry (defaults to DRAFT)."""
        changed = False
        for idx in scene_indices:
            if idx not in self._states:
                self._states[idx] = {
                    "state": SceneState.DRAFT.value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "notes": "",
                }
                changed = True
        if changed:
            self.save()

    def mark_needs_revision(self, index: int, notes: str = "") -> None:
        """Mark a scene as Needs Revision unless it is Locked."""
        if not self.is_locked(index):
            self.set_state(index, SceneState.NEEDS_REVISION, notes)

    def mark_needs_review(self, index: int) -> None:
        """Advance a DRAFT scene to Needs Review unless it is Locked or already approved."""
        current = self.get_state(index)
        if current == SceneState.DRAFT:
            self.set_state(index, SceneState.NEEDS_REVIEW)
