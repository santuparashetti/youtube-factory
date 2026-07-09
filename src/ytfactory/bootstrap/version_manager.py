"""Version Manager — maintains bootstrap-manifest.json for version-aware startup."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

_MANIFEST_FILE = "bootstrap-manifest.json"
BOOTSTRAP_VERSION = "1.0.0"


def load_manifest(base_dir: Path | None = None) -> dict[str, Any]:
    root = base_dir or Path.cwd()
    path = root / _MANIFEST_FILE
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def save_manifest(manifest: dict[str, Any], base_dir: Path | None = None) -> None:
    root = base_dir or Path.cwd()
    path = root / _MANIFEST_FILE
    try:
        path.write_text(json.dumps(manifest, indent=2))
        logger.debug("Bootstrap manifest written: {}", path)
    except OSError as exc:
        logger.warning("Cannot write bootstrap manifest: {}", exc)


def build_manifest(base_dir: Path | None = None) -> dict[str, Any]:
    """Build a fresh bootstrap manifest capturing current environment state."""
    return {
        "bootstrap_version": BOOTSTRAP_VERSION,
        "project_version": _get_project_version(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "ffmpeg_version": _get_ffmpeg_version(),
        "torch_version": _get_torch_version(),
        "providers": _get_provider_info(),
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }


def is_manifest_current(manifest: dict[str, Any]) -> bool:
    """Return True if the manifest is still valid (same bootstrap version)."""
    return manifest.get("bootstrap_version") == BOOTSTRAP_VERSION


def _get_project_version() -> str:
    try:
        from importlib.metadata import version

        return version("youtube-factory")
    except Exception:
        return "0.1.0"


def _get_ffmpeg_version() -> str:
    try:
        r = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        first_line = r.stdout.splitlines()[0] if r.stdout else ""
        return first_line[:80]
    except Exception:
        return "unknown"


def _get_torch_version() -> str:
    try:
        import torch  # type: ignore[import]

        return torch.__version__
    except ImportError:
        return "not installed"


def _get_provider_info() -> dict[str, str]:
    try:
        from ytfactory.config.settings import Settings

        s = Settings()
        return {
            "llm": s.llm_provider,
            "search": s.search_provider,
            "image": s.image_provider,
            "tts": s.tts_provider,
        }
    except Exception:
        return {}
