"""RevisionStore — manages script revision lineage on disk.

Stores revisions in workspace/jobs/<id>/script/revisions.json.
Each revision's script text is written to revision-<N>.md.
The canonical (accepted) revision is identified by canonical_revision_id.

The store is intentionally simple: one project → one revisions.json file.
No database, no YAML — follows the project's existing JSON workspace convention.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from ytfactory.domain.script_revision import (
    ReviewDecision,
    RevisionStatus,
    ScriptRevision,
)
from ytfactory.shared.constants import WORKSPACE_DIR


class RevisionStore:
    """Read and write script revision lineage for a project."""

    def __init__(self, project_id: str) -> None:
        self._project_id = project_id
        self._script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        self._revisions_file = self._script_dir / "revisions.json"

    def _ensure_dir(self) -> None:
        self._script_dir.mkdir(parents=True, exist_ok=True)

    def _load_store(self) -> dict:
        if self._revisions_file.exists():
            try:
                return json.loads(self._revisions_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {"revisions": [], "canonical_revision_id": None}

    def _save_store(self, store: dict) -> None:
        self._ensure_dir()
        self._revisions_file.write_text(
            json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def save_revision(
        self,
        script_text: str,
        *,
        parent_id: Optional[str] = None,
    ) -> ScriptRevision:
        """Persist a new revision and return the ScriptRevision object."""
        self._ensure_dir()
        store = self._load_store()
        existing = store.get("revisions", [])

        revision_number = len(existing) + 1
        revision_id = str(uuid.uuid4())
        script_file = f"revision-{revision_number}.md"

        (self._script_dir / script_file).write_text(script_text, encoding="utf-8")

        revision = ScriptRevision(
            revision_id=revision_id,
            revision_number=revision_number,
            parent_id=parent_id,
            status=RevisionStatus.PENDING,
            reviewer_decision=None,
            reviewer_feedback=None,
            script_file=script_file,
        )
        existing.append(revision.to_dict())
        store["revisions"] = existing
        self._save_store(store)
        return revision

    def record_rejection(
        self,
        revision_id: str,
        feedback: str,
    ) -> None:
        """Record that a revision was rejected with structured feedback."""
        store = self._load_store()
        for rev in store.get("revisions", []):
            if rev["revision_id"] == revision_id:
                rev["status"] = RevisionStatus.REJECTED.value
                rev["reviewer_decision"] = ReviewDecision.REJECT.value
                rev["reviewer_feedback"] = feedback
                break
        self._save_store(store)

    def record_acceptance(self, revision_id: str) -> None:
        """Record that a revision was accepted as canonical."""
        store = self._load_store()
        for rev in store.get("revisions", []):
            if rev["revision_id"] == revision_id:
                rev["status"] = RevisionStatus.ACCEPTED.value
                rev["reviewer_decision"] = ReviewDecision.ACCEPT.value
                break
        store["canonical_revision_id"] = revision_id
        self._save_store(store)

    def get_canonical_script(self) -> Optional[str]:
        """Return the text of the accepted canonical revision, or None."""
        store = self._load_store()
        canonical_id = store.get("canonical_revision_id")
        if not canonical_id:
            return None
        for rev in store.get("revisions", []):
            if rev["revision_id"] == canonical_id:
                script_file = self._script_dir / rev["script_file"]
                if script_file.exists():
                    return script_file.read_text(encoding="utf-8")
        return None

    def get_revision_text(self, revision_id: str) -> Optional[str]:
        store = self._load_store()
        for rev in store.get("revisions", []):
            if rev["revision_id"] == revision_id:
                f = self._script_dir / rev["script_file"]
                return f.read_text(encoding="utf-8") if f.exists() else None
        return None

    def list_revisions(self) -> list[ScriptRevision]:
        store = self._load_store()
        return [ScriptRevision.from_dict(r) for r in store.get("revisions", [])]

    def get_latest_revision(self) -> Optional[ScriptRevision]:
        revisions = self.list_revisions()
        return revisions[-1] if revisions else None

    def get_canonical_revision_id(self) -> Optional[str]:
        return self._load_store().get("canonical_revision_id")
