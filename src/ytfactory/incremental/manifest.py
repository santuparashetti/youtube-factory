"""Pipeline Manifest — tracks checksums and metadata for all generated assets.

Stored at workspace/jobs/<project-id>/.pipeline-manifest.json.

The manifest drives smart change detection: when an asset's checksum differs
from the stored value, it is considered modified and all downstream stages are
invalidated.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import ManifestEntry

MANIFEST_FILENAME = ".pipeline-manifest.json"
MANIFEST_VERSION = "1"


class PipelineManifest:
    """Read/write the per-project pipeline manifest."""

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._path = project_dir / MANIFEST_FILENAME
        self._entries: dict[str, ManifestEntry] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for rel_path, entry_data in data.get("entries", {}).items():
                try:
                    self._entries[rel_path] = ManifestEntry(**entry_data)
                except TypeError:
                    pass
        except (json.JSONDecodeError, OSError):
            pass

    def save(self) -> None:
        self._project_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "version": MANIFEST_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "entries": {
                k: {
                    "stage": v.stage,
                    "path": v.path,
                    "checksum": v.checksum,
                    "mtime": v.mtime,
                    "generated_at": v.generated_at,
                    "engine_version": v.engine_version,
                }
                for k, v in self._entries.items()
            },
        }
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def get(self, rel_path: str) -> ManifestEntry | None:
        return self._entries.get(rel_path)

    def set(self, rel_path: str, entry: ManifestEntry) -> None:
        self._entries[rel_path] = entry

    def remove(self, rel_path: str) -> None:
        self._entries.pop(rel_path, None)

    @property
    def entries(self) -> dict[str, ManifestEntry]:
        return dict(self._entries)

    # ── Checksum helpers ──────────────────────────────────────────────────────

    @staticmethod
    def compute_checksum(path: Path) -> str:
        """SHA-256 of file contents, hex-encoded (first 16 chars for brevity)."""
        if not path.exists():
            return ""
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:16]

    # ── Record & check ────────────────────────────────────────────────────────

    def record(self, rel_path: str, stage: str) -> ManifestEntry:
        """Snapshot current on-disk state of rel_path into the manifest."""
        abs_path = self._project_dir / rel_path
        entry = ManifestEntry(
            stage=stage,
            path=rel_path,
            checksum=self.compute_checksum(abs_path),
            mtime=abs_path.stat().st_mtime if abs_path.exists() else 0.0,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        self._entries[rel_path] = entry
        return entry

    def is_changed(self, rel_path: str) -> bool:
        """True when the asset differs from its manifest snapshot (or is new)."""
        entry = self._entries.get(rel_path)
        if entry is None:
            return True
        abs_path = self._project_dir / rel_path
        if not abs_path.exists():
            return True
        return self.compute_checksum(abs_path) != entry.checksum

    def is_missing(self, rel_path: str) -> bool:
        """True when an asset is in the manifest but no longer on disk."""
        entry = self._entries.get(rel_path)
        if entry is None:
            return False
        return not (self._project_dir / rel_path).exists()
