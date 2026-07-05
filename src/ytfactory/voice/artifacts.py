from __future__ import annotations

from pathlib import Path


def audio_directory(project: str) -> Path:
    directory = Path("workspace") / "jobs" / project / "audio"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
