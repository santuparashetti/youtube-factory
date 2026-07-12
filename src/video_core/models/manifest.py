"""Model manifest — tracks download state for all managed models.

Bundle Architecture extension
------------------------------
The manifest now records additional per-model fields:

  capabilities      — declared capability list (for diagnostics)
  checksum_verified — True when sha256 checksum matched during provisioning
  warm_inference_ok — True when post-download warm inference succeeded
  bundle_artifacts  — dict mapping artifact_name → local filesystem path
  failure_reason    — FailureReason value when status == ERROR

All new fields have safe defaults so existing manifests load without error.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import ModelState, ModelStatus

_MANIFEST_FILE = "models/model-manifest.json"


def load_manifest(base_dir: Path) -> dict[str, ModelState]:
    """Load per-model state from the manifest file."""
    path = base_dir / _MANIFEST_FILE
    if not path.exists():
        return {}
    try:
        raw: dict = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    result: dict[str, ModelState] = {}
    for name, entry in (raw.get("models") or {}).items():
        result[name] = ModelState(
            name=name,
            status=ModelStatus(entry.get("status", ModelStatus.UNKNOWN)),
            backend=entry.get("backend", "cpu"),
            cache_path=entry.get("cache_path", ""),
            revision=entry.get("revision", ""),
            error=entry.get("error", ""),
            packages_ok=bool(entry.get("packages_ok", False)),
            # Bundle Architecture fields (backward-compatible: missing → defaults)
            capabilities=list(entry.get("capabilities") or []),
            checksum_verified=bool(entry.get("checksum_verified", False)),
            warm_inference_ok=bool(entry.get("warm_inference_ok", False)),
            bundle_artifacts=dict(entry.get("bundle_artifacts") or {}),
            failure_reason=str(entry.get("failure_reason", "")),
        )
    return result


def save_manifest(base_dir: Path, states: dict[str, ModelState]) -> None:
    """Persist model state to manifest file."""
    path = base_dir / _MANIFEST_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "2",
        "models": {
            name: {
                "status": state.status.value,
                "backend": state.backend,
                "cache_path": state.cache_path,
                "revision": state.revision,
                "error": state.error,
                "packages_ok": state.packages_ok,
                # Bundle Architecture fields
                "capabilities": state.capabilities,
                "checksum_verified": state.checksum_verified,
                "warm_inference_ok": state.warm_inference_ok,
                "bundle_artifacts": state.bundle_artifacts,
                "failure_reason": state.failure_reason,
            }
            for name, state in states.items()
        },
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def get_state(base_dir: Path, model_name: str) -> ModelState | None:
    """Return the current state for one model, or None if not in manifest."""
    manifest = load_manifest(base_dir)
    return manifest.get(model_name)


def update_state(base_dir: Path, state: ModelState) -> None:
    """Update a single model's state in the manifest."""
    manifest = load_manifest(base_dir)
    manifest[state.name] = state
    save_manifest(base_dir, manifest)
